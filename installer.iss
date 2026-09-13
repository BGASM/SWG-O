; SWG-O installer script for Inno Setup 6.
; Build the app first (build.bat), then open this in the Inno Setup Compiler
; and hit Compile, or run:  iscc installer.iss
;
; Output: dist\SWG-O-Setup-1.0.0.exe

#define AppName        "SWG-O"
#define AppVersion     "1.0.0"
#define AppAuthor      "Beargasm"
#define AppExe         "SWG-O.exe"

[Setup]
AppId={{8D3F1C42-5B7A-4E96-9C21-6A0F7E4B21D3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppAuthor}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppAuthor}
VersionInfoDescription={#AppName} Setup

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}

OutputDir=dist
OutputBaseFilename=SWG-O-Setup-{#AppVersion}
SetupIconFile=swgo.ico

; Installs per-user under %LOCALAPPDATA%\Programs, so no UAC prompt and no
; Program Files permission problems. Change to "admin" for a machine-wide
; install if you ever want one.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startupicon"; Description: "Start {#AppName} when I sign in"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
; The whole PyInstaller onedir output, including the _internal folder.
Source: "dist\SWG-O\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Diagnostic helper, for users whose client uses a different window class.
Source: "tools\swgo_pids.py"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "README.md";           DestDir: "{app}";       Flags: ignoreversion
Source: "LICENSE";             DestDir: "{app}";       Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";            Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}";  Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";      Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}";      Filename: "{app}\{#AppExe}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Settings live in %APPDATA%\SWG-O. Left in place on uninstall so an upgrade
; keeps the user's tile layout. Uncomment to remove them instead.
; Type: filesandordirs; Name: "{userappdata}\SWG-O"
