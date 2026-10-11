# Build the Windows installer (DECISIONS D-044). Run from the repository root in PowerShell 7:
#   pwsh packaging/build_windows.ps1
# Needs: uv, Node.js 22+, Inno Setup 6 (choco install innosetup).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (uv run python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])").Trim()
Write-Host "Building Research History $version for Windows x64"

uv sync --extra ots --extra desktop --group package --locked
if ($LASTEXITCODE) { throw "uv sync failed" }
Push-Location web
npm ci; if ($LASTEXITCODE) { throw "npm ci failed" }
npm run build; if ($LASTEXITCODE) { throw "web build failed" }
Pop-Location

uv run python packaging/prepare.py
if ($LASTEXITCODE) { throw "prepare failed" }
uv run pyinstaller --noconfirm --clean packaging/rprov.spec --distpath dist --workpath build/pyinstaller
if ($LASTEXITCODE) { throw "PyInstaller failed" }

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (choco install innosetup)" }
& $iscc "/DMyAppVersion=$version" packaging\windows\ResearchHistory.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }
Get-ChildItem dist\*.exe | ForEach-Object { Write-Host ("{0}  {1:N1} MB" -f $_.Name, ($_.Length / 1MB)) }
