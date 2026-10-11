@echo off
setlocal
rem ------------------------------------------------------------------
rem Double-click entry: pull the server's nightly DB backups onto this
rem PC, so a copy exists off the server. Pairs with pull-backups.sh.
rem The real host lives in deploy\.deploy.env (gitignored), so this
rem file carries no real address and is safe to commit.
rem ------------------------------------------------------------------

set "ENVFILE=%~dp0..\.deploy.env"
if not exist "%ENVFILE%" (
    echo [ERROR] deploy\.deploy.env not found next to this script.
    pause
    exit /b 1
)

set "DEPLOY_HOST="
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b "DEPLOY_HOST=" "%ENVFILE%"`) do set "DEPLOY_HOST=%%b"
if "%DEPLOY_HOST%"=="" (
    echo [ERROR] DEPLOY_HOST is missing in deploy\.deploy.env
    pause
    exit /b 1
)

set "KEY=%USERPROFILE%\.ssh\id_ed25519"
if not exist "%KEY%" (
    echo [ERROR] SSH key not found: %KEY%
    pause
    exit /b 1
)

set "DEST=%USERPROFILE%\FusionPilot-backups"
if not exist "%DEST%" mkdir "%DEST%"

echo Pulling backups from the server ...
scp -i "%KEY%" -o StrictHostKeyChecking=accept-new "%DEPLOY_HOST%:/var/backups/fusionpilot/*.sql.gz" "%DEST%\"
if errorlevel 1 (
    echo [ERROR] copy failed - check network or SSH key.
    pause
    exit /b 1
)

rem Verify each archive decompresses to a *completed* dump; delete any bad copy
rem so the next run re-pulls it. NOTE: the file is gzipped SQL text, NOT a tar
rem archive — tar -tzf would reject every good file. Windows ships no gzip.exe,
rem so decompress via PowerShell and look for mysqldump's closing marker.
for %%f in ("%DEST%\*.sql.gz") do (
    powershell -NoProfile -Command "Add-Type -AssemblyName System.IO.Compression; $fs=[IO.File]::OpenRead('%%f'); $gz=New-Object IO.Compression.GzipStream($fs,[IO.Compression.CompressionMode]::Decompress); $buf=New-Object byte[] 65536; $tail=''; while(($n=$gz.Read($buf,0,$buf.Length)) -gt 0){$tail=[Text.Encoding]::ASCII.GetString($buf,0,$n)}; $gz.Close(); if($tail -match 'Dump completed'){exit 0}else{exit 1}" >nul 2>&1 || (
        echo [WARN] corrupt or incomplete copy removed: %%~nxf
        del "%%f"
    )
)

echo.
echo Done. Local backup folder: %DEST%
echo.
dir /b /o-d "%DEST%\*.sql.gz" 2>nul
echo.
echo Keep this folder somewhere safe. Restoring a backup:
echo   mysql fusionpilot ^< fusionpilot-YYYY-MM-DD.sql.gz
pause
