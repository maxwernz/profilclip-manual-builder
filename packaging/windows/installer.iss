; Inno Setup script – built by tools/build_release.py on Windows:
;   ISCC.exe /DAppVersion=0.2.0 /DSourceDir=..\..\dist\Anleitungs-Baukasten /DOutputDir=..\..\release\0.2.0 installer.iss
; Installs per user (no administrator rights) to %LOCALAPPDATA%\Programs\Anleitungs-Baukasten,
; so the app can update itself silently later.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Anleitungs-Baukasten"
#define AppExe "Anleitungs-Baukasten.exe"

[Setup]
; never change the AppId – it identifies the installation for updates and uninstall
AppId={{6F3C2A9E-4B1D-4C7A-9E52-8D1F0A6B3C21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Profi L-Clip GmbH
AppPublisherURL=https://www.profil-clip.de
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Profi L-Clip GmbH
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile=..\icon\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; remove files of the previous version so nothing stale is left behind
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; also runs after a silent update -> the new version starts automatically
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall
