@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

REM Viewer deployment entrypoint. All paths are resolved from this file so the
REM project can be placed anywhere, including the historical C:\industry_demo.
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%" || goto :root_error

if exist "industry_demo\restart_viewer.bat" (
    echo [失败] 检测到嵌套安装: %PROJECT_ROOT%\industry_demo
    echo        当前广播包被解压进了旧项目目录，活动根目录仍可能是旧版本。
    echo        请在广播包解压目录运行 INSTALL_FULL_REPLACE.cmd，
    echo        或把压缩包解压到 C:\ 的上一级而不是 C:\industry_demo 内。
    goto :failed
)

if not defined VIEWER_HOST set "VIEWER_HOST=0.0.0.0"
if not defined VIEWER_PORT set "VIEWER_PORT=8080"
if not defined VIEWER_CONDA_ENV set "VIEWER_CONDA_ENV=industry"
if not defined VIEWER_PYTHON set "VIEWER_PYTHON=python"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "cache" mkdir "cache"
set "VIEWER_LOG=cache\viewer.log"
set "PREFLIGHT_LOG=cache\viewer_preflight.log"

echo ====================================
echo  Industry Viewer 重启脚本
echo  项目: %PROJECT_ROOT%
echo  地址: %VIEWER_HOST%:%VIEWER_PORT%
echo  时间: %date% %time%
echo ====================================
echo.

echo [1/6] 检查部署文件...
if not exist "tools\viewer\preflight.py" (
    echo   [失败] 缺少 tools\viewer\preflight.py
    echo   请重新同步最新 tools 目录和 restart_viewer.bat。
    goto :failed
)
if not exist "config\research_workflow.yaml" (
    echo   [失败] 缺少 config\research_workflow.yaml
    echo   2026-07 工作流重构后，config 已是 Viewer 启动依赖。
    echo   请把项目根目录的 config 文件夹同步到此目录后重试。
    goto :failed
)
echo   部署入口文件存在
echo.

echo [2/6] 激活 Python 环境...
if defined VIEWER_SKIP_CONDA goto :python_ready
where conda >nul 2>&1
if errorlevel 1 (
    echo   [失败] PATH 中找不到 conda。
    echo   可先运行 Conda 初始化脚本，或设置 VIEWER_SKIP_CONDA=1 和 VIEWER_PYTHON。
    goto :failed
)
call conda activate "%VIEWER_CONDA_ENV%"
if errorlevel 1 (
    echo   [失败] 无法激活 Conda 环境 "%VIEWER_CONDA_ENV%"。
    echo   如环境名称不同，请先执行: set VIEWER_CONDA_ENV=实际环境名
    goto :failed
)
:python_ready
"%VIEWER_PYTHON%" -c "import sys; print('  Python:', sys.executable)"
if errorlevel 1 (
    echo   [失败] Python 不可执行: %VIEWER_PYTHON%
    goto :failed
)
echo.

echo [3/6] 执行只读启动预检...
"%VIEWER_PYTHON%" "tools\viewer\preflight.py" --root "%PROJECT_ROOT%" > "%PREFLIGHT_LOG%" 2>&1
if errorlevel 1 (
    echo   [失败] 启动预检未通过:
    type "%PREFLIGHT_LOG%"
    goto :failed
)
type "%PREFLIGHT_LOG%"
echo.

echo [4/6] 关闭占用 %VIEWER_PORT% 端口的旧进程...
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":%VIEWER_PORT% .*LISTENING"') do (
    set "FOUND=1"
    echo   关闭旧进程 PID=%%a
    taskkill /F /PID %%a >nul 2>&1
)
if "!FOUND!"=="0" echo   端口当前空闲
timeout /t 2 /nobreak >nul

if exist "%VIEWER_LOG%" (
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "BAKTIME=%%i"
    move /Y "%VIEWER_LOG%" "%VIEWER_LOG%.!BAKTIME!.bak" >nul 2>&1
)
echo.

echo [5/6] 启动 Viewer...
start "" /B "%VIEWER_PYTHON%" -m flask --app tools.viewer.app:app run --host="%VIEWER_HOST%" --port="%VIEWER_PORT%" --no-debugger --no-reload > "%VIEWER_LOG%" 2>&1
echo   已发起启动，等待 HTTP 健康检查...
echo.

echo [6/6] 验证服务状态...
set "READY=0"
for /L %%i in (1,1,30) do (
    if "!READY!"=="0" (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%VIEWER_PORT%/api/health' -TimeoutSec 2; if ($r.StatusCode -eq 200 -and ($r.Content | ConvertFrom-Json).ok) { exit 0 } } catch {}; exit 1" >nul 2>&1
        if !errorlevel! equ 0 set "READY=1"
        if "!READY!"=="0" timeout /t 1 /nobreak >nul
    )
)

if "!READY!"=="0" (
    echo   [失败] 30 秒内未通过 /api/health。
    echo.
    echo === Viewer 日志 ===
    if exist "%VIEWER_LOG%" type "%VIEWER_LOG%"
    goto :failed
)

netstat -an | findstr /R /C:"%VIEWER_HOST%:%VIEWER_PORT% .*LISTENING" >nul
if errorlevel 1 (
    echo   [警告] HTTP 已可用，但未确认监听地址为 %VIEWER_HOST%:%VIEWER_PORT%。
    echo          请用 netstat -ano ^| findstr :%VIEWER_PORT% 复核内网监听。
) else (
    echo   [成功] HTTP 健康检查通过，监听地址为 %VIEWER_HOST%:%VIEWER_PORT%。
)
echo.
echo ====================================
echo  重启完成
echo ====================================
echo  本机: http://127.0.0.1:%VIEWER_PORT%/
echo  日志: %PROJECT_ROOT%\%VIEWER_LOG%
echo ====================================
echo.
if /I not "%VIEWER_NO_PAUSE%"=="1" pause
exit /b 0

:root_error
echo [失败] 无法进入脚本所在目录: %~dp0
goto :failed

:failed
echo.
echo Viewer 未启动。修复上方首个错误后重新运行。
if /I not "%VIEWER_NO_PAUSE%"=="1" pause
exit /b 1
