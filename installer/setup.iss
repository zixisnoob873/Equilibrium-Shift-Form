; Gaming Zone Shift Management - Inno Setup Script
; Generates a professional Windows Setup Installer (.exe)

#define MyAppName "Gaming Zone Shift Management"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Equilibrium Gaming"
#define MyAppURL "https://github.com/zixisnoob873/Equilibrium-Shift-Form"
#define MyAppExeName "Equilibrium-Shift-Form.exe"

[Setup]
AppId={{D37E84B1-29FA-4F62-8E37-B3C57F0C8E19}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\EquilibriumShiftForm
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=output
OutputBaseFilename=Equilibrium-Shift-Form-Installer
SetupIconFile=..\assets\installer_icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "formdesktopicon"; Description: "Create a desktop shortcut for Shift Form"; GroupDescription: "{cm:AdditionalIcons}"
Name: "desktopicon"; Description: "Create a desktop shortcut for Control Center"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Start application automatically when Windows starts"; GroupDescription: "Startup Options:"; Flags: unchecked

[Files]
; Compiled launcher executable and Qt runtimes
Source: "..\dist\Equilibrium-Shift-Form\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Python application scripts and assets
Source: "..\server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\launcher.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\settings.example.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\update.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\start.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\setup_sheets.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\guide.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

; Directories
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\core\*"; DestDir: "{app}\core"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\layout\*"; DestDir: "{app}\layout"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Ensure data directories exist and preserve them across uninstall
Name: "{app}\local_data"; Flags: uninsneveruninstall
Name: "{app}\local_data_dev"; Flags: uninsneveruninstall
Name: "{app}\uploads"; Flags: uninsneveruninstall
Name: "{app}\screenshots"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\Shift Form"; Filename: "http://localhost:5000"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; IconFilename: "{app}\assets\installer_icon.ico"
Name: "{autodesktop}\Shift Form"; Filename: "http://localhost:5000"; IconFilename: "{app}\assets\icon.ico"; Tasks: formdesktopicon
Name: "{autodesktop}\Gaming Zone Shift Management"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GamingZoneShiftManager"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
