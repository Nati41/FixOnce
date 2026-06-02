; FixOnce Installer Script for Inno Setup
; https://jrsoftware.org/isinfo.php
;
; Build instructions:
; 1. Install Inno Setup from https://jrsoftware.org/isdl.php
; 2. Open this file in Inno Setup Compiler
; 3. Click Build > Compile
; 4. Output: installer/Output/FixOnce_Setup.exe

#define MyAppName "FixOnce"
#define MyAppVersion "3.2"
#define MyAppPublisher "FixOnce"
#define MyAppURL "https://github.com/fixonce/fixonce"
#define MyAppExeName "FixOnce.exe"

[Setup]
; App identity
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Install location
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; Output settings
OutputDir=Output
OutputBaseFilename=FixOnce_Setup_{#MyAppVersion}
SetupIconFile=..\FixOnce.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Privileges (per-user install, no admin required)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Visual
WizardStyle=modern
WizardSizePercent=100

; Misc
AllowNoIcons=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Main application (from PyInstaller dist folder)
Source: "..\dist\FixOnce\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Icon file
Source: "..\FixOnce.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\FixOnce.ico"

; Desktop (optional)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\FixOnce.ico"; Tasks: desktopicon

[Registry]
; App registration for uninstall info
Root: HKCU; Subkey: "Software\FixOnce"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\FixOnce"; ValueType: string; ValueName: "DataPath"; ValueData: "{userappdata}\FixOnce"; Flags: uninsdeletekey

; Remove legacy HKCU Run autostart from older installers (do not recreate)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "FixOnce"; Flags: uninsdeletevalue dontcreatekey

[Dirs]
; Create AppData folder with proper permissions
Name: "{userappdata}\FixOnce"; Permissions: users-full
Name: "{userappdata}\FixOnce\projects_v2"; Permissions: users-full
Name: "{userappdata}\FixOnce\global"; Permissions: users-full
Name: "{userappdata}\FixOnce\extension"; Permissions: users-full

[Run]
; First-run setup: server, FixOnceServer scheduled task, health check, dashboard.
; Setup waits for bootstrap and fails if it returns a non-zero exit code.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--bootstrap"; StatusMsg: "Setting up FixOnce (server, autostart, dashboard)..."; Flags: waituntilterminated skipifdoesntexist

[UninstallRun]
; Stop FixOnce before uninstall
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "StopFixOnce"

[UninstallDelete]
; Clean up AppData on uninstall (optional - commented out to preserve user data)
; Type: filesandordirs; Name: "{userappdata}\FixOnce"

[Code]
// Pascal Script for custom logic

procedure RemoveLegacyRunKey();
begin
  RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FixOnce');
end;

function InitializeUninstall: Boolean;
var
  MsgResult: Integer;
begin
  Result := True;

  // Ask user if they want to keep their data
  MsgResult := MsgBox(
    'Do you want to keep your FixOnce data (decisions, insights, project memory)?' + #13#10 + #13#10 +
    'Click Yes to keep your data for future reinstalls.' + #13#10 +
    'Click No to delete everything.',
    mbConfirmation, MB_YESNOCANCEL);

  if MsgResult = IDCANCEL then
    Result := False
  else if MsgResult = IDNO then
  begin
    // User wants to delete data
    DelTree(ExpandConstant('{userappdata}\FixOnce'), True, True, True);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    RemoveLegacyRunKey();
  end;

  if CurStep = ssDone then
  begin
    MsgBox(
      'FixOnce is ready!' + #13#10 + #13#10 +
      'Background startup uses the FixOnceServer scheduled task.' + #13#10 + #13#10 +
      'To install the Chrome Extension:' + #13#10 +
      '1. Open Chrome and go to chrome://extensions' + #13#10 +
      '2. Enable "Developer mode"' + #13#10 +
      '3. Click "Load unpacked"' + #13#10 +
      '4. Select: ' + ExpandConstant('{app}\extension') + #13#10 + #13#10 +
      'Or click "Install Extension" in the FixOnce dashboard.',
      mbInformation, MB_OK);
  end;
end;

// Check if FixOnce is running and offer to close it
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';

  // Try to close running instance gracefully
  Exec('taskkill', '/F /IM FixOnce.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  // Small delay to ensure process is closed
  Sleep(500);
end;
