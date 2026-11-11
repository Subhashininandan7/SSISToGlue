@echo off
setlocal
cd /d "%~dp0"
where dotnet >nul 2>&1 || (echo ERROR: .NET 8 SDK required. & pause & exit /b 1)
if not defined PYTHON_COMMAND (
  where python >nul 2>&1 && set "PYTHON_COMMAND=python"
)
if not defined PYTHON_COMMAND (
  where py >nul 2>&1 && set "PYTHON_COMMAND=py"
)
if not defined PYTHON_COMMAND (
  echo ERROR: Python 3 not found. Set PYTHON_COMMAND to the full path to python.exe.
  pause
  exit /b 1
)
echo Python command: %PYTHON_COMMAND%
echo Open http://127.0.0.1:5297 after startup.
dotnet run --project DemoWeb\DemoWeb.csproj
pause
