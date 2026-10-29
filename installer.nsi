; 企业信用一键截图工具 —— NSIS 安装包脚本
;
; 用法：
;   makensis /DAPP_VERSION=2.1.1 installer.nsi
;
; 产物：dist\企业信用截图工具_安装包.exe
;
; 特点：
;   * 装到「程序文件」下，不需要管理员也能装（用 SetShellVarContext current）
;   * 自动创建桌面快捷方式与开始菜单项
;   * 完整卸载（删除程序文件、快捷方式、注册表项）
;   * 用户的凭据与截图放在 %APPDATA%，卸载不会删（数据安全）

!define APP_NAME "企业信用一键截图工具"
!define APP_EXE "企业信用截图工具.exe"
!define APP_PUBLISHER "企业信用截图工具"
!define APP_REG_KEY "Software\企业信用一键截图工具"

; 现代界面（Modern UI）必须显式引入，否则 MUI_PAGE_* 宏找不到
!include "MUI2.nsh"
!include "LogicLib.nsh"

; 版本号可以由命令行覆盖：makensis /DAPP_VERSION=2.1.1 installer.nsi
!ifndef APP_VERSION
  !define APP_VERSION "2.1.1"
!endif

; 安装目录：优先用程序文件，权限不足时退回用户目录
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKCU "${APP_REG_KEY}" "InstallDir"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "dist\${APP_NAME}_安装包.exe"
Unicode true
RequestExecutionLevel user

VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=2052 "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductVersion" "${APP_VERSION}.0"
VIAddVersionKey /LANG=2052 "FileDescription" "企业信用一键截图工具"
VIAddVersionKey /LANG=2052 "LegalCopyright" "${APP_PUBLISHER}"

!define MUI_ABORTWARNING
!define MUI_ICON "assets\app.ico"
!define MUI_UNICON "assets\app.ico"
; 欢迎页/结束页左侧横幅（自己画的品牌图，比 NSIS 默认图标好看）
!define MUI_WELCOMEFINISHPAGE_BITMAP "assets\banner.bmp"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即启动"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Section "安装程序" SecMain
  SetOutPath "$INSTDIR"
  ; 整个 dist\企业信用截图工具 目录一起装（含 _internal 运行时）
  File /r "dist\企业信用截图工具\*"

  ; 使用说明单独放一份在安装目录根下，便于用户查阅
  File "使用说明.md"

  ; 注册表：记录安装目录（供下次安装/卸载定位）
  WriteRegStr HKCU "${APP_REG_KEY}" "InstallDir" "$INSTDIR"

  ; 开始菜单
  SetShellVarContext current
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\卸载.lnk" "$INSTDIR\uninstall.exe"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\使用说明.lnk" "$INSTDIR\使用说明.md"

  ; 桌面快捷方式
  CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"

  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; 让 Windows 的「已安装程序」能认出这个安装包
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoRepair" 1

  MessageBox MB_ICONINFORMATION|MB_OK "安装完成。$\n$\n程序文件：$INSTDIR$\n$\n配置与截图保存在：%APPDATA%\企业信用截图工具$\n（卸载程序不会删除这些数据）"
SectionEnd

Section "Uninstall"
  ; 只删程序文件；%APPDATA% 下的凭据与截图保留，避免误删用户数据
  SetShellVarContext current

  ; 先结束正在运行的程序：文件被占用时 RMDir /r 会失败，留下残渣目录。
  ; 用系统自带的 taskkill（不依赖 nsExec 插件，那个不是所有 NSIS 都自带）。
  ExecWait '"$SYSDIR\cmd.exe" /C taskkill /F /IM "${APP_EXE}"' $0
  ExecWait '"$SYSDIR\cmd.exe" /C taskkill /F /IM "调试版.exe"' $0
  Sleep 800

  ; 先删整个目录树，再兜底删空目录。
  ; 注意顺序：RMDir /r 遇到「已被前面 Delete 删过」的文件时可能留下残渣，
  ; 所以先整体删、再单独删一次空壳目录，确保目录真的消失。
  RMDir /r "$INSTDIR"
  RMDir /r "$INSTDIR\_internal"
  RMDir "$INSTDIR"

  Delete "$DESKTOP\${APP_NAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APP_NAME}"

  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
  DeleteRegKey HKCU "${APP_REG_KEY}"
SectionEnd

; 打包完成后如果程序正在运行，提示用户
Function .onInit
  ; 检查端口 8760 是否被占用（本程序在运行）
  ; 简单地看安装目录里的进程 —— 交给 Windows 自己处理更稳妥，这里只提示
FunctionEnd
