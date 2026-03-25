@echo off
chcp 65001 >nul
title 3D Genome Literature Hub - Build EXE

echo ============================================================
echo   Building 3D Genome Literature Hub .exe
echo   Please wait...
echo ============================================================
echo.

:: Try to find Python - check multiple locations
set PYTHON_CMD=

:: Method 1: Check if python is directly available
python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python
    goto :found_python
)

:: Method 2: Check if python3 is available
python3 --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python3
    goto :found_python
)

:: Method 3: Try Anaconda/Miniconda common locations
for %%P in (
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "%USERPROFILE%\Anaconda3\python.exe"
    "%USERPROFILE%\Miniconda3\python.exe"
    "%LOCALAPPDATA%\anaconda3\python.exe"
    "%LOCALAPPDATA%\miniconda3\python.exe"
    "%PROGRAMDATA%\anaconda3\python.exe"
    "%PROGRAMDATA%\miniconda3\python.exe"
    "C:\anaconda3\python.exe"
    "C:\miniconda3\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
    "C:\ProgramData\miniconda3\python.exe"
    "C:\Users\%USERNAME%\anaconda3\python.exe"
    "C:\Users\%USERNAME%\miniconda3\python.exe"
) do (
    if exist %%P (
        set PYTHON_CMD=%%P
        goto :found_python
    )
)

:: Method 4: Try conda activate then python
where conda >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Found conda, activating base environment...
    call conda activate base
    python --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_CMD=python
        goto :found_python
    )
)

:: Method 5: Search PATH for python
for /f "tokens=*" %%i in ('where python 2^>nul') do (
    set PYTHON_CMD=%%i
    goto :found_python
)

:: Nothing found
echo [ERROR] Python not found!
echo.
echo You have Anaconda installed, but Python is not in PATH.
echo.
echo Please try ONE of these solutions:
echo.
echo   Solution 1: Open "Anaconda Prompt" (search in Start Menu)
echo               Then drag this file into the Anaconda Prompt window
echo               and press Enter
echo.
echo   Solution 2: Open "Anaconda Navigator" then launch "CMD.exe Prompt"
echo               Then cd to this folder and run: build_exe.bat
echo.
echo   Solution 3: Add Anaconda to PATH:
echo               Open Anaconda Prompt, type: conda init cmd.exe
echo               Then close and reopen Command Prompt
echo.
pause
exit /b 1

:found_python
echo [OK] Found Python: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

:: Get pip command
set PIP_CMD=%PYTHON_CMD% -m pip

:: Install dependencies
echo [1/3] Installing dependencies...
%PIP_CMD% install -r requirements.txt
if errorlevel 1 (
    echo [WARNING] Some dependencies may have failed, continuing...
)
%PIP_CMD% install pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller!
    pause
    exit /b 1
)

:: Build exe
echo.
echo [2/3] Building executable (this may take a few minutes)...
%PYTHON_CMD% -m PyInstaller --noconfirm ^
    --onefile ^
    --name "3DGenomeHub" ^
    --add-data "src\genome_literature;genome_literature" ^
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

:: Copy supporting files to dist
echo.
echo [3/3] Copying supporting files...
if not exist "dist\papers" mkdir "dist\papers"
if not exist "dist\templates" mkdir "dist\templates"
copy templates\email_digest.html dist\templates\ >nul 2>&1
copy .env.example dist\ >nul 2>&1

echo.
echo ============================================================
echo   SUCCESS! Your exe file is ready:
echo.
echo       dist\3DGenomeHub.exe
echo.
echo   Double-click it to start the app!
echo   (Browser will open automatically)
echo ============================================================
echo.
pause
