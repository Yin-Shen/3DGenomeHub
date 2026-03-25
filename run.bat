@echo off
title 3D Genome Literature Hub
echo ============================================================
echo   3D Genome ^& Deep Learning Literature Hub
echo   Starting...
echo ============================================================
python run.py
if errorlevel 1 (
    echo.
    echo Error: Python not found. Please install Python 3.9+ from python.org
    pause
)
