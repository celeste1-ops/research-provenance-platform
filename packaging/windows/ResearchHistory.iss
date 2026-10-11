; Windows installer (Inno Setup 6.5 or later) — DECISIONS D-044, D-046.
; Installs for the current user only (no administrator rights), adds a Start menu entry
; and an uninstaller. Your data lives in %USERPROFILE%\.rprov and is never touched by
; installing, upgrading or uninstalling.
;   ISCC.exe /DMyAppVersion=0.1.0 packaging\windows\ResearchHistory.iss

#define MyAppName "Research History"
#define MyAppExe "Research History.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: it is how upgrades find the installed copy.
AppId={{305AAEC5-E80E-4F7C-B4D9-B7FF40C9D588}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Research History contributors
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\..\dist
OutputBaseFilename=ResearchHistory-{#MyAppVersion}-windows-x64-setup
SetupIconFile=..\..\build\icons\app.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
; Chinese on a Chinese Windows, English everywhere else (D-046); no language question.
ShowLanguageDialog=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
; The official Simplified Chinese messages (jrsoftware/issrc, Files/Languages), kept here byte for
; byte (UTF-8, no BOM) so the build does not depend on which languages the compiler shipped with.
Name: "zh"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An upgrade replaces the program files completely (never the data in %USERPROFILE%\.rprov).
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
