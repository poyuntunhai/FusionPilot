@echo off
rem Thin wrapper so the CLI can be invoked as `fpx` from a Windows shell.
rem Set FPX_PYTHON to pick a specific interpreter; otherwise `python` is used.
setlocal
set "PY=%FPX_PYTHON%"
if "%PY%"=="" set "PY=python"
"%PY%" "%~dp0fpx.py" %*
exit /b %ERRORLEVEL%
