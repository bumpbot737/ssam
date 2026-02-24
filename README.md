# 🔍 كاشف الكلمات العربي — يوتيوب

أقوى أداة عربية لتحليل الكلمات المفتاحية على يوتيوب، مع بث مباشر وبيانات حقيقية.

---

## ⚡ تشغيل سريع (محلي)

### Linux / Mac
```bash
chmod +x start.sh
./start.sh
```

### Windows
```
start.bat
```

ثم افتح: **http://localhost:8000**

---

## 🐳 تشغيل عبر Docker

```bash
docker-compose up -d
```

---

## ☁️ النشر السحابي

### Railway (مجاني)
1. ارفع المشروع على GitHub
2. اذهب إلى [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. اختر المستودع
4. يتعرف Railway على Dockerfile تلقائياً
5. ✅ رابطك جاهز خلال دقيقتين

### Render (مجاني)
1. ارفع على GitHub
2. اذهب إلى [render.com](https://render.com) → New Web Service
3. اختر المستودع → Environment: Docker
4. ✅ جاهز

### Fly.io (مجاني)
```bash
curl -L https://fly.io/install.sh | sh
fly auth login
fly launch
fly deploy
```

### VPS (DigitalOcean / Hetzner)
```bash
git clone <your-repo>
cd yt-keyword-tool
docker-compose up -d
```

---

## 🛠️ الأدوات المستخدمة

| الأداة | الاستخدام |
|--------|-----------|
| YouTube Autocomplete Scraper | اقتراحات مباشرة من يوتيوب |
| Google Trends (PyTrends) | نقاط الترند ومقارنة الكلمات |
| FastAPI + Server-Sent Events | بث مباشر للنتائج |
| SQLite | كاش البيانات (أسبوع) |
| aiohttp | طلبات HTTP سريعة وغير متزامنة |
| allorigins.win | بروكسي CORS مجاني للواجهة الأمامية |

---

## 📁 هيكل المشروع
```
yt-keyword-tool/
├── backend/
│   ├── main.py          ← FastAPI + كل المنطق
│   └── requirements.txt
├── frontend/
│   └── index.html       ← الواجهة الكاملة
├── data/                ← SQLite DB (يُنشأ تلقائياً)
├── Dockerfile
├── docker-compose.yml
├── start.sh             ← تشغيل Linux/Mac
└── start.bat            ← تشغيل Windows
```

---

## 🔌 API Endpoints

```
GET  /api/top          → أفضل 100 كلمة مفتاحية
GET  /api/search?q=... → بحث عن كلمة مفتاحية
GET  /api/related?kw=  → الكلمات المشابهة
GET  /api/stream/search → بث مباشر SSE
POST /api/refresh       → تحديث البيانات
GET  /api/health        → فحص الخادم
```

---

## ✅ الميزات

- 🔴 **بث مباشر** عبر Server-Sent Events
- 📅 **فلترة زمنية**: يوم / أسبوع / شهر مع أرقام دقيقة
- 🌍 **دعم الدول**: السعودية، مصر، الإمارات، الكويت، قطر، المغرب، الجزائر
- 🔗 **كلمات مشابهة** مرتبة بنسبة التشابه
- 💾 **كاش ذكي** في SQLite لتسريع الاستجابة
- ⬇️ **تصدير CSV** للنتائج
- 🔄 **تحديث تلقائي** كل 30 دقيقة
