; ============================================================
;  EC-Tok — instalador de Windows (Inno Setup 6)
;  Lo compila windows\build.ps1. Instala por usuario (sin admin).
; ============================================================
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist\ectok"
#endif

[Setup]
AppId={{B3E1D0C4-7A2F-4E59-9C3B-EC70C0000001}
AppName=EC-Tok
AppVersion={#AppVersion}
AppVerName=EC-Tok {#AppVersion}
AppPublisher=Cesar Mugica
DefaultDirName={localappdata}\Programs\EC-Tok
DefaultGroupName=EC-Tok
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=EC-Tok-Setup-{#AppVersion}
SetupIconFile=..\src\web\img\ectok.ico
UninstallDisplayIcon={app}\ectok.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[CustomMessages]
es.TaskDesktop=Crear acceso directo «EC-Tok» en el escritorio
en.TaskDesktop=Create an "EC-Tok" desktop shortcut
pt.TaskDesktop=Criar atalho «EC-Tok» na área de trabalho
es.GroupShortcuts=Accesos directos:
en.GroupShortcuts=Shortcuts:
pt.GroupShortcuts=Atalhos:
es.IconComment=Alertas, sonidos y voz para tus lives de TikTok
en.IconComment=Alerts, sounds and TTS for your TikTok lives
pt.IconComment=Alertas, sons e voz para suas lives do TikTok
es.IconData=Carpeta de datos de EC-Tok
en.IconData=EC-Tok data folder
pt.IconData=Pasta de dados do EC-Tok
es.IconUninstall=Desinstalar EC-Tok
en.IconUninstall=Uninstall EC-Tok
pt.IconUninstall=Desinstalar o EC-Tok
es.RunApp=Abrir EC-Tok
en.RunApp=Open EC-Tok
pt.RunApp=Abrir o EC-Tok

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:GroupShortcuts}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\EC-Tok"; Filename: "{app}\ectok.exe"; Comment: "{cm:IconComment}"
Name: "{group}\{cm:IconData}"; Filename: "{localappdata}\EC-Tok"
Name: "{group}\{cm:IconUninstall}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\EC-Tok"; Filename: "{app}\ectok.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ectok.exe"; Description: "{cm:RunApp}"; Flags: nowait postinstall skipifsilent
; Actualización desde la app (instalador en silencio): volver a abrir EC-Tok al terminar.
Filename: "{app}\ectok.exe"; Parameters: "--after-update"; Flags: nowait; Check: WizardSilent

[InstallDelete]
; Los accesos del menú Inicio cambian de nombre según el idioma
Type: files; Name: "{group}\*.lnk"

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ectok.exe /F"; Flags: runhidden; RunOnceId: "StopEcTok"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var R: Integer;
begin
  if CurStep = ssInstall then
  begin
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM ectok.exe /F', '', SW_HIDE, ewWaitUntilTerminated, R);
  end;
  { El idioma del instalador es el idioma inicial de la app (luego se cambia en la app) }
  if CurStep = ssPostInstall then
  begin
    ForceDirectories(ExpandConstant('{localappdata}\EC-Tok'));
    SaveStringToFile(ExpandConstant('{localappdata}\EC-Tok\language.txt'), ActiveLanguage, False);
  end;
end;
