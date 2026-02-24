#!/bin/bash
# ═══════════════════════════════════════
#  كاشف الكلمات - سكريبت التشغيل
# ═══════════════════════════════════════
set -e

echo "🚀 جاري تشغيل كاشف الكلمات العربي..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 غير مثبت. قم بتثبيته أولاً."
    exit 1
fi

# Create virtualenv if not exists
if [ ! -d "venv" ]; then
    echo "📦 إنشاء البيئة الافتراضية..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null

# Install dependencies
echo "📦 تثبيت المكتبات..."
pip install -r backend/requirements.txt -q

# Create data dir
mkdir -p data

# Launch
echo "✅ تشغيل الخادم على http://localhost:8000"
echo "   افتح المتصفح على: http://localhost:8000"
echo "   اضغط Ctrl+C للإيقاف"
echo ""

cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload
