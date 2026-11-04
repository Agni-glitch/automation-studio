; Inno Setup script for Automation Studio. Built by build/package.py, which passes
; /DAppVersion=... /DSourceDir=<PyInstaller output folder> /DOutputDir=...
; Per-user install (no admin prompt) into %LOCALAPPDATA%\Programs\AutomationStudio.
; User data (%LOCALAPPDATA%\AutomationEngine: workflows, credentials, history) is kept on uninstall.

#define AppName "Automation Studio"
#define AppURL "https://github.com/Agni-glitch/automation-studio"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "output\dist\AutomationStudio"
#endif
#ifndef OutputDir
  #define OutputDir "output"
#endif

[Setup]
AppId={{8F2C6B1E-3D4A-4E5B-9C7D-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Automation Studio contributors
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\AutomationStudio
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=AutomationStudio-Setup-{#AppVersion}
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\AutomationStudio.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
MinVersion=10.0.17763
#ifdef Sign
; package.py defines Sign and passes /Sstudio=<command running sign.ps1 $f>
SignTool=studio
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"
Name: "autostart"; Description: "Run in the background when I sign in (keeps active workflows listening)"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[InstallDelete]
; a previous version's files must not mix with the new ones
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\AutomationStudio.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\AutomationStudio.exe"; Tasks: desktopicon

[Registry]
; Same value the in-app "start at sign-in" switch manages (backend/autostart.py).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AutomationStudio"; ValueData: """{app}\AutomationStudio.exe"" serve --background"; Tasks: autostart
; Remove it on uninstall even if it was switched on later from inside the app.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "AutomationStudio"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\AutomationStudio.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
; In-app updates run the installer with /SILENT /relaunch=1: reopen the app afterwards.
Filename: "{app}\AutomationStudio.exe"; Flags: nowait; Check: ShouldRelaunch

[UninstallRun]
Filename: "{app}\studio.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopService"

[Code]
function ShouldRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;

// Stop the background service of an existing installation before replacing its files.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  if FileExists(ExpandConstant('{app}\studio.exe')) then
    Exec(ExpandConstant('{app}\studio.exe'), 'stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
