#define MyAppName "AccessibleIPTVClient"
#define MyAppDisplayName "Accessible IPTV Client"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Serrebi"
#define MyAppExeName "IPTVClient.exe"
#ifndef SourceDir
  #define SourceDir "..\dist\iptvclient"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\release"
#endif

[Setup]
AppId={{9F1D07F7-A6F2-47E9-BDB8-C0895F3F6C6F}
AppName={#MyAppDisplayName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppDisplayName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppDisplayName}
DisableProgramGroupPage=yes
; Per-machine install into Windows' default Program Files folder. On x64 Windows,
; x64-compatible builds install under "Program Files" and 32-bit builds install
; under "Program Files (x86)". Runtime config, EPG data, schedules, logs, and
; caches are kept in %APPDATA%\AccessibleIPTVClient by options.py.
PrivilegesRequired=admin
OutputDir={#OutputDir}
OutputBaseFilename={#MyAppName}-Setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; Setup must not try to close applications itself (issue #31). The updater
; has already closed the app and stopped anything still running out of the
; install directory by the time Setup starts, and it drives Setup with
; /VERYSILENT /SUPPRESSMSGBOXES. With CloseApplications=yes, Restart Manager
; reported the update helper's own Windows PowerShell as "an application
; using one of our files", could not shut it down - it is the process running
; Setup - and the suppressed "some applications could not be shut down" box
; defaulted to Abort, so every update rolled back with exit code 5.
CloseApplications=no
RestartApplications=no
SetupLogging=yes
; Select the installer language from the current Windows UI language.
; English remains the fallback for unsupported UI languages.
LanguageDetectionMethod=uilanguage
ShowLanguageDialog=no
UsePreviousLanguage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hungarian"; MessagesFile: "compiler:Languages\Hungarian.isl"

[CustomMessages]
; Inno Setup's stock Hungarian LaunchProgram is "Indítás %1".
; This override keeps the same meaning but uses natural Hungarian word order.
hungarian.LaunchProgram=%1 indítása

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; The old _internal directory is not deleted with [InstallDelete]: Inno never
; undoes those deletions, so an update that failed part-way (a file in use)
; rolled back to an app with half its runtime missing, and it would not start
; at all. It is moved aside instead, and put back if the install does not
; finish (see [Code]).

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "iptvclient.conf,epg.db,epg.db-wal,epg.db-shm,epg.db-journal,scheduled_recordings.json,iptv_cache\*,cache\*,logs\*,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "windows-installed.marker"; DestDir: "{app}"; DestName: ".windows-installed"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppDisplayName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  InternalBackupDir: String;
  InstallFinished: Boolean;

function InternalDir(): String;
begin
  Result := ExpandConstant('{app}\_internal');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    if DirExists(InternalDir()) then
    begin
      InternalBackupDir := ExpandConstant('{app}\_internal.update-backup');
      if DirExists(InternalBackupDir) then
        DelTree(InternalBackupDir, True, True, True);
      if RenameFile(InternalDir(), InternalBackupDir) then
        Log('Moved the old runtime aside: ' + InternalBackupDir)
      else
      begin
        // Something still holds a file in it. Install over the top instead:
        // a file that cannot be replaced then fails the install, and Inno's
        // own rollback restores every file it had already replaced.
        Log('Could not move the old runtime aside; installing over it.');
        InternalBackupDir := '';
      end;
    end;
  end
  else if CurStep = ssPostInstall then
  begin
    InstallFinished := True;
    if (InternalBackupDir <> '') and DirExists(InternalBackupDir) then
      DelTree(InternalBackupDir, True, True, True);
  end;
end;

procedure DeinitializeSetup();
begin
  // Runs after Inno's rollback has removed the files this install created.
  if InstallFinished or (InternalBackupDir = '') or not DirExists(InternalBackupDir) then
    Exit;
  if DirExists(InternalDir()) then
    DelTree(InternalDir(), True, True, True);
  if RenameFile(InternalBackupDir, InternalDir()) then
    Log('Install did not finish; restored the old runtime.')
  else
    Log('Install did not finish, and the old runtime could not be restored from ' + InternalBackupDir);
end;
