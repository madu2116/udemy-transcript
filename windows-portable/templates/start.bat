@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Udemy Transcript  (CHE DO DEBUG)
echo ============================================
echo Cach chay thong thuong (khong hien cua so nay): double-click UdemyTranscript.vbs
echo Tat ung dung: bam nut "Tat ung dung" tren web, hoac dong cua so nay.
echo.

"runtime\python.exe" launcher.py

pause
