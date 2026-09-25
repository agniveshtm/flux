; Flux - Inno Setup script
;
; Packages the PyInstaller one-file build (dist\flux.exe) into the Windows
; setup executable that ships alongside it in every GitHub release:
;
;   ISCC /DMyAppVersion=<x.y.z> installer\flux.iss
;     -> dist\flux-setup-<x.y.z>.exe
;
; .github/workflows/release.yml passes the tag version. The fallback below
; only serves manual local builds - keep it in sync with pyproject.toml.
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "Flux"
#define MyAppPublisher "agniveshtm"
#define MyAppURL "https://github.com/agniveshtm/flux"
#define MyAppExeName "flux.exe"

[Setup]
; A stable AppId is what makes a new setup recognize and upgrade/replace the
; previous installation - never change this value once published.
AppId={{8E5F4B21-6C0A-4D7E-9B3F-2A1C5D8E7F60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={autopf}\Flux
DisableProgramGroupPage=yes
; Per-user install, no UAC: the in-app updater runs this setup with
; /SILENT immediately after closing the app, where an elevation prompt
; would strand the user halfway through an upgrade. With
; PrivilegesRequired=lowest, {autopf} resolves to {localappdata}\Programs.
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=flux-setup-{#MyAppVersion}
SetupIconFile=..\src\flux\assets\favicon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Interactive installs: a Finish-page launch checkbox (skipped in silent
; mode, where there is no Finish page to tick a box on).
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: postinstall nowait skipifsilent
; Silent runs - the in-app updater's upgrade - relaunch automatically so
; the user lands straight on the new version.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent