@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install .
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pandao_repro demo
if errorlevel 1 goto failed
echo 已完成，请查看上方结果目录中的结论.md。
pause
exit /b 0
:failed
echo 未完成，请查看上方错误信息。
pause
exit /b 1
