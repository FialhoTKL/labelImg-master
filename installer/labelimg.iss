; Instalador do LabelImg - Inno Setup 6
;
; Empacota a pasta gerada pelo PyInstaller (dist\LabelImg). A versão é passada
; na linha de comando pelo build (build_installer.ps1 / GitHub Actions):
;   ISCC.exe /DMyAppVersion=1.9.0 installer\labelimg.iss

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "LabelImg"
#define MyAppPublisher "ARX Tecnologia"
#define MyAppExeName "LabelImg.exe"
#define MyAppURL "https://github.com/FialhoTKL/labelImg-master"

[Setup]
; O AppId identifica o programa entre versões: NUNCA altere, senão uma versão
; nova é instalada ao lado da antiga em vez de substituí-la.
AppId={{E5A408C8-FB2F-4C06-B4FA-DE51B6681B5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
; Instala em C:\ARX\LabelImg ({sd} = disco do sistema): C:\ARX é a pasta da
; empresa e cada software fica na sua própria subpasta. Usuários comuns podem
; criar pastas na raiz do C:, então não é preciso administrador, o que permite
; ao app se atualizar sozinho em modo silencioso. Atualizações reutilizam a
; pasta da instalação anterior.
DefaultDirName={sd}\ARX\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=LabelImg_Setup_{#MyAppVersion}
SetupIconFile=..\resources\icons\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Fecha o programa se estiver aberto durante a instalação/atualização.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Remove os arquivos da versão anterior antes de copiar os novos, para não
; sobrar biblioteca antiga misturada com a nova.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\LabelImg\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Sem "skipifsilent": depois de uma atualização automática (modo silencioso)
; o programa é reaberto sozinho.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall
