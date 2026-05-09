@echo off
chcp 65001 > nul
title MASE 记忆可靠性平台 / Memory Reliability Platform

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║   MASE  Memory Reliability Platform          ║
echo  ║   记忆可靠性平台  · 正在启动...              ║
echo  ╚══════════════════════════════════════════════╝
echo.
echo  [1] 默认端口 8765 启动 (Default: port 8765)
echo  [2] 自定义端口启动 (Custom port)
echo  [3] 只读审计模式 Read-only audit mode
echo.
set /p CHOICE="  请选择 / Select [1-3, default=1]: "

if "%CHOICE%"=="" set CHOICE=1
if "%CHOICE%"=="1" goto START_DEFAULT
if "%CHOICE%"=="2" goto START_CUSTOM
if "%CHOICE%"=="3" goto START_READONLY
goto START_DEFAULT

:START_DEFAULT
echo.
echo  启动中 / Starting at http://127.0.0.1:8765 ...
cd /d "%~dp0"
powershell -NoExit -ExecutionPolicy Bypass -File "scripts\start_platform.ps1"
goto END

:START_CUSTOM
set /p CUSTOM_PORT="  输入端口号 / Enter port number [8766]: "
if "%CUSTOM_PORT%"=="" set CUSTOM_PORT=8766
echo.
echo  启动中 / Starting at http://127.0.0.1:%CUSTOM_PORT% ...
cd /d "%~dp0"
powershell -NoExit -ExecutionPolicy Bypass -File "scripts\start_platform.ps1" -Port %CUSTOM_PORT%
goto END

:START_READONLY
echo.
echo  只读审计模式 / Starting Read-only audit mode at http://127.0.0.1:8765 ...
cd /d "%~dp0"
powershell -NoExit -ExecutionPolicy Bypass -File "scripts\start_platform.ps1" -ReadOnly
goto END

:END
