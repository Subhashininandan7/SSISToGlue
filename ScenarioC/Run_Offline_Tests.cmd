@echo off
cd /d "%~dp0"
py -3 -m pytest tests -q
pause
