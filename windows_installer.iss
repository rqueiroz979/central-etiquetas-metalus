#define AppName "Almoxarifado"
#define AppVersion "1.1.0"
#define AppPublisher "Metalus"
#define AppExeName "ALMOXARIFADO.exe"

[Setup]
AppId={{798E9506-91BD-477B-8D98-51A54A20B735}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Almoxarifado
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=ALMOXARIFADO_OFFLINE\static\almoxarifado.ico
OutputDir=dist\windows
OutputBaseFilename=Almoxarifado-Setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
Uninstallable=yes
CloseApplications=force
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "dist\windows\ALMOXARIFADO\ALMOXARIFADO.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\windows\ALMOXARIFADO\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Abrir {#AppName}"; Flags: postinstall nowait skipifsilent
