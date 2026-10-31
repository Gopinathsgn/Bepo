; Script generated for Inno Setup (produces Bepo-Setup.exe)
; Installs into user's LocalAppData without requiring Administrator privileges

#define MyAppName "Bepo"
#ifndef MyAppVersion
  #define MyAppVersion "1.2.2"   ; overridden by CI: ISCC /DMyAppVersion=x.y.z
#endif
#define MyAppPublisher "Gopinath"
#define MyAppURL "https://github.com/Gopinathsgn"
#define MyAppExeName "Bepo.exe"

[Setup]
AppId={{E8B2456C-3B47-49F1-8B39-9571E86E3C0F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=Bepo-Setup-v{#MyAppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
LicenseFile=LICENSE
PrivilegesRequired=lowest
; Same name as core/bootstrap.py MUTEX_NAME: Setup/Uninstall notice a running Bepo (a tray app) and ask to close it
AppMutex=Bepo_AI_Voice_Typing_SingleInstance_Mutex

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\Bepo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; "Start Bepo when I sign in" (core/startup.py) writes this value; remove it when Bepo is uninstalled
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Bepo"; Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
