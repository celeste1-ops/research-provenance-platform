# Install the built setup silently, start the app without browser or tray icon, and check it
# end to end over HTTP: set-up (signing key in Windows Credential Manager), a step, an
# evidence bundle that the bundled verify.py accepts. Then uninstall and check the data stays.
#   pwsh packaging/smoke_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$setup = Get-ChildItem dist\ResearchHistory-*-windows-x64-setup.exe | Select-Object -First 1
if (-not $setup) { throw "no installer in dist\" }
Write-Host "Installing $($setup.Name)"
Start-Process $setup.FullName -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
$appDir = Join-Path $env:LOCALAPPDATA "Programs\Research History"
$exe = Join-Path $appDir "Research History.exe"
if (-not (Test-Path $exe)) { throw "not installed at $exe" }

$data = Join-Path $env:RUNNER_TEMP "rprov-smoke"
if (-not $env:RUNNER_TEMP) { $data = Join-Path $env:TEMP "rprov-smoke" }
Remove-Item -Recurse -Force $data -ErrorAction SilentlyContinue
$env:RPROV_HOME = $data
$env:RPROV_TSA = "off"   # no outside services needed for this check
$env:RPROV_BTC = "off"
$proc = Start-Process $exe -ArgumentList "--no-browser", "--no-tray", "--port", "8799" -PassThru
$base = "http://127.0.0.1:8799"
try {
  $status = $null
  for ($i = 0; $i -lt 90 -and -not $status; $i++) {
    try { $status = Invoke-RestMethod "$base/api/status" } catch { Start-Sleep -Seconds 1 }
  }
  if (-not $status) { Get-Content (Join-Path $data "logs\app.log") -ErrorAction SilentlyContinue; throw "app did not start" }
  Write-Host "Running: device=$($status.device) initialized=$($status.initialized)"
  if ($status.device -ne "PC") { throw "expected device word PC, got $($status.device)" }

  $html = (Invoke-WebRequest "$base/" -UseBasicParsing).Content
  if ($html -notmatch 'name="rprov-session-token" content="([^"]+)"') { throw "no session token in page" }
  $h = @{ "X-RPROV-Token" = $Matches[1] }
  Invoke-RestMethod -Method Post "$base/api/identity" -Headers $h -ContentType "application/json" -Body '{"author_label":"Smoke test"}' | Out-Null
  $project = Invoke-RestMethod -Method Post "$base/api/projects" -Headers $h -ContentType "application/json" -Body '{"title":"Smoke"}'
  $form = @{ project_id = $project.id; node_type = "idea"; title = "Smoke step — ünïcode"; body = "hello" }
  Invoke-RestMethod -Method Post "$base/api/entries" -Headers $h -Form $form | Out-Null
  $status = Invoke-RestMethod "$base/api/status"
  if ($status.entry_count -ne 1) { throw "expected 1 step, got $($status.entry_count)" }

  $zip = Join-Path $data "bundle.zip"
  $body = @{ title = "Smoke"; records = @{}; default = "full" } | ConvertTo-Json
  Invoke-WebRequest -Method Post "$base/api/export" -Headers $h -ContentType "application/json" -Body $body -OutFile $zip -UseBasicParsing
  $unpacked = Join-Path $data "bundle"
  Expand-Archive $zip $unpacked
  uv run python (Join-Path $unpacked "verify.py") $unpacked --offline  # needs cryptography + rfc3161-client
  if ($LASTEXITCODE -ne 0) { throw "verify.py rejected the bundle" }
  Write-Host "verify.py accepted the bundle"
} finally {
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

# The app's own window (D-058), as you would use it: the page is drawn in the window (WebView2),
# closing the window hides it while the app keeps running, a second start shows it again, Quit
# ends the app.
$wdata = Join-Path (Split-Path $data -Parent) "rprov-window"
Remove-Item -Recurse -Force $wdata -ErrorAction SilentlyContinue
$env:RPROV_HOME = $wdata
$wlog = Join-Path $wdata "logs\app.log"
$window = Start-Process $exe -ArgumentList "--check-window", "--port", "8798" -PassThru
$null = $window.Handle  # keeps the exit code readable after the process ends
if (-not $window.WaitForExit(180000)) {
  Stop-Process -Id $window.Id -Force -ErrorAction SilentlyContinue
  Get-Content $wlog -ErrorAction SilentlyContinue
  throw "window check did not finish"
}
if ($window.ExitCode -ne 0 -or -not (Select-String -Path $wlog -Pattern "window check passed" -Quiet)) {
  Get-Content $wlog -ErrorAction SilentlyContinue
  throw "window check failed (exit code $($window.ExitCode))"
}
Select-String -Path $wlog -Pattern "window check"
$env:RPROV_HOME = $data

Start-Sleep -Seconds 2
Start-Process (Join-Path $appDir "unins000.exe") -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
Start-Sleep -Seconds 2
if (Test-Path $exe) { throw "uninstall left the program behind" }
if (-not (Test-Path (Join-Path $data "rprov.sqlite3"))) { throw "uninstall touched the data folder" }
Write-Host "Smoke test passed: installed, ran, saved a step, exported, verified, opened the window, uninstalled; data kept."
