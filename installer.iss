; Inno Setup Script for English Coach
; Prerequisite: Run build_remote.bat first to generate dist\EnglishCoach\
;
; Usage:
;   1. Download Inno Setup: https://jrsoftware.org/isdl.php
;   2. Open this file with Inno Setup Compiler
;   3. Build > Compile (Ctrl+F9)
;   4. Output: installer_output\EnglishCoach_Setup.exe

#define MyAppName "English Coach"
#define MyAppVersion "2.1"
#define MyAppPublisher "EnglishCoach"
#define MyAppExeName "EnglishCoach.exe"

[Setup]
AppId={{A7E2C3D1-4F5B-4A8E-9D6C-1B2A3E4F5G6H}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=installer_output
OutputBaseFilename=EnglishCoach_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
; 覆盖安装：关闭旧版本后直接覆盖文件
CloseApplications=yes
; Icon requires .ico format; PNG not supported by Inno Setup
SetupIconFile=src\resources\images\mascot.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
; Name: "english"; MessagesFile: "compiler:Default.isl"
; 如需中文安装界面，下载 ChineseSimplified.isl 放到 Inno Setup 6\Languages\ 目录
; 然后取消下行注释：
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"
Name: "startmenuicon"; Description: "创建开始菜单快捷方式"; GroupDescription: "附加选项:"

[Files]
; Copy entire PyInstaller output directory
Source: "dist\EnglishCoach\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
