@echo off
REM ════════════════════════════════════════════════════════════════════════════
REM   NEXUS MT5 BRIDGE — ملف تشغيل ويندوز
REM   يقوم بقراءة الإعدادات من ملف .env في نفس المجلد ثم تشغيل bridge.py
REM ════════════════════════════════════════════════════════════════════════════

chcp 65001 >nul
cd /d "%~dp0"

echo ═══════════════════════════════════════════════════════════════════════════
echo   NEXUS MT5 BRIDGE — بدء التشغيل
echo ═══════════════════════════════════════════════════════════════════════════
echo.

REM محاولة قراءة ملف .env إن وُجد
if exist ".env" (
    echo 📄 قراءة الإعدادات من .env ...
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        REM تجاهل التعليقات والأسطر الفارغة
        echo %%a | findstr /r "^#" >nul
        if errorlevel 1 (
            if not "%%a"=="" (
                set "%%a=%%b"
            )
        )
    )
) else (
    echo ⚠️  لا يوجد ملف .env — استخدم متغيرات البيئة مباشرة
)

REM التحقق من الإعدادات الإلزامية
if "%NEXUS_URL%"=="" (
    echo ❌ NEXUS_URL غير محدد!
    echo    أنشئ ملف .env من نسخة .env.example أو حدد المتغير يدويًا:
    echo    set NEXUS_URL=https://preview-chat-^<chat_id^>.space-z.ai
    pause
    exit /b 1
)

if "%NEXUS_BRIDGE_TOKEN%"=="" (
    echo ❌ NEXUS_BRIDGE_TOKEN غير محدد!
    echo    أنشئ ملف .env من نسخة .env.example أو حدد المتغير يدويًا:
    echo    set NEXUS_BRIDGE_TOKEN=nxb-xxxxxxxxxxxxxxxx
    pause
    exit /b 1
)

echo ✅ NEXUS_URL          = %NEXUS_URL%
echo ✅ NEXUS_BRIDGE_TOKEN = %NEXUS_BRIDGE_TOKEN:~0,15%*****
echo.

REM التحقق من Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python غير مثبت أو ليس في PATH
    echo    ثبّت Python من https://python.org ثم أعد المحاولة
    pause
    exit /b 1
)

REM التحقق من مكتبة MetaTrader5
python -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
    echo ⚠️  مكتبة MetaTrader5 غير مثبتة — جاري التثبيت...
    pip install MetaTrader5 requests
)

echo ═══════════════════════════════════════════════════════════════════════════
echo   تشغيل bridge.py ... (اضغط Ctrl+C للإيقاف)
echo ═══════════════════════════════════════════════════════════════════════════
echo.

python bridge.py

pause
