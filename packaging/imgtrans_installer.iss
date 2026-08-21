; 优译图AI 图片翻译 — 安装包脚本
; 编译：ISCC.exe packaging/imgtrans_installer.iss
; 产物：dist/installer/ImgTrans-Setup-0.1.0.exe

#define MyAppName "优译图AI 图片翻译"
#define MyAppVersion "1.1.6"
#define MyAppPublisher "ImgTrans"
#define MyAppExeName "ImgTrans.exe"
#define SourceDir "..\dist\release-candidate\windows-x64\ImgTrans"

[Setup]
AppId={{5F2A7C3D-8B4E-4F6A-9D1C-2E5F8A3B6C7D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ImgTrans
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=ImgTrans-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 客户端数据写入用户 AppData，安装目录只读，卸载干净

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
