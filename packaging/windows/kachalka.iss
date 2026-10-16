; Установщик Качалки для Windows (Inno Setup 6).
; Ставится в профиль пользователя, права администратора не нужны.
;   iscc /DAppVersion=1.0.0 packaging\windows\kachalka.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B2E4D1A-8C3F-4E7B-9A51-2D7C0F4E8B19}
AppName=Качалка
AppVersion={#AppVersion}
AppVerName=Качалка {#AppVersion}
AppPublisher=vldvr
AppPublisherURL=https://github.com/vldvr/kachalka
AppSupportURL=https://github.com/vldvr/kachalka/issues
DefaultDirName={localappdata}\Programs\Kachalka
DefaultGroupName=Качалка
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=Kachalka-{#AppVersion}-Windows-Setup
SetupIconFile=..\icons\kachalka.ico
UninstallDisplayIcon={app}\Kachalka.exe
UninstallDisplayName=Качалка
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\Kachalka\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Качалка"; Filename: "{app}\Kachalka.exe"
Name: "{autodesktop}\Качалка"; Filename: "{app}\Kachalka.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Kachalka.exe"; Description: "{cm:LaunchProgram,Качалка}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Kachalka.exe /T /F"; Flags: runhidden; RunOnceId: "StopKachalka"
