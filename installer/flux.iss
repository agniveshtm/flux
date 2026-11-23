; Flux - Inno Setup script
;
; Packages the PyInstaller one-file build (dist\flux.exe) together with the
; ffmpeg sidecar (dist\ffmpeg.exe) into the Windows setup executable that
; ships in every GitHub release:
;
;   Copy-Item vendor\ffmpeg.exe dist\ffmpeg.exe
;   ISCC /DMyAppVersion=<x.y.z> installer\flux.iss
;     -> dist\flux-setup-<x.y.z>.exe
;
; .github/workflows/release.yml passes the tag version and stages the sidecar.
; The fallback below only serves manual local builds - keep it in sync with
; pyproject.toml.
#ifndef MyAppVersion
  #define MyAppVersion "0.5.0"
#endif

#define MyAppName "Flux"
#define MyAppPublisher "agniveshtm"
#define MyAppURL "https://github.com/agniveshtm/flux"
#define MyAppExeName "flux.exe"
#define MyFfmpegExeName "ffmpeg.exe"
#define MyFfmpegLicense "LICENSE-ffmpeg.txt"

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
; The build is PyInstaller on x64 Python, so the artifact is x64 only. Without
; these two the setup happily installs on 32-bit Windows and then fails to
; launch; with them the user gets Setup's own "not a valid Win32 application"
; refusal instead of a broken install.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
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
; In a frozen build locate_ffmpeg() looks for ffmpeg.exe beside sys.executable,
; so the sidecar has to land in the same {app} folder as flux.exe. Without this
; row an installed copy silently runs image-only even though the release
; advertises video/audio conversion. release.yml stages the binary in dist\
; before ISCC runs; test.yml writes a placeholder for the compile check.
Source: "..\dist\{#MyFfmpegExeName}"; DestDir: "{app}"; Flags: ignoreversion
; The sidecar is GPLv3 (gyan.dev essentials enables libx264), so its licence
; text must accompany the binary - see vendor/README.md.
Source: "..\vendor\{#MyFfmpegLicense}"; DestDir: "{app}"; Flags: ignoreversion

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