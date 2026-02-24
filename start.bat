@echo off
echo === كاشف الكلمات العربي - يوتيوب ===
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo خطأ: Python غير مثبت. قم بتثبيته من python.org
    pause
    exit /b 1
)

:: Create virtualenv
if not exist "venv" (
    echo جاري إنشاء البيئة الافتراضية...
    python -m venv venv
)

:: Activate
call venv\Scripts\activate.bat

:: Install
echo جاري تثبيت المكتبات...
pip install -r backend\requirements.txt -q

:: Data dir
if not exist "data" mkdir data

echo.
echo الخادم يعمل على: http://localhost:8000
echo افتح المتصفح على: http://localhost:8000
echo.

cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
