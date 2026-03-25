@echo off
chcp 65001 >nul
title 3D Genome Literature Hub - Build EXE

echo ============================================================
echo   Building 3D Genome Literature Hub .exe
echo   Please wait...
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.9+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation!
    pause
    exit /b 1
)

:: Install dependencies
echo [1/3] Installing dependencies...
pip install -r requirements.txt >nul 2>&1
pip install pyinstaller >nul 2>&1

:: Build exe
echo [2/3] Building executable...
pyinstaller --noconfirm ^
    --onefile ^
    --name "3DGenomeHub" ^
    --icon NONE ^
    --add-data "src/genome_literature;genome_literature" ^
    --add-data "templates;templates" ^
    --add-data "papers;papers" ^
    --add-data "requirements.txt;." ^
    --hidden-import genome_literature ^
    --hidden-import genome_literature.cli ^
    --hidden-import genome_literature.web_app ^
    --hidden-import genome_literature.fetcher ^
    --hidden-import genome_literature.categorizer ^
    --hidden-import genome_literature.summarizer ^
    --hidden-import genome_literature.readme_generator ^
    --hidden-import genome_literature.email_notifier ^
    --hidden-import genome_literature.storage ^
    --hidden-import genome_literature.pipeline ^
    --hidden-import genome_literature.config ^
    run_exe.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed! Check the error messages above.
    pause
    exit /b 1
)

:: Done
echo [3/3] Done!
echo.
echo ============================================================
echo   SUCCESS! Your exe file is at:
echo   dist\3DGenomeHub.exe
echo.
echo   Double-click it to start the app!
echo ============================================================
echo.

:: Copy supporting files
if not exist "dist\papers" mkdir "dist\papers"
if not exist "dist\templates" mkdir "dist\templates"
copy templates\email_digest.html dist\templates\ >nul 2>&1
copy .env.example dist\ >nul 2>&1

echo   All files copied to dist\ folder.
echo   You can move the entire dist\ folder anywhere you like.
echo.
pause
