"""
YouTube Arabic Keyword Research Tool - Backend
FastAPI + PyTrends + YouTube Autocomplete Scraper
"""

import asyncio
import json
import logging
import re
import sqlite3
import time
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from fastapi import FastAPI, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── Logging ───────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("yt-keywords")

# ─── Constants ─────────────────────────────────────────────
YOUTUBE_SUGGEST_URLS = [
    "https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&hl=ar&gl={geo}&q={q}",
    "https://suggestqueries-clients6.youtube.com/complete/search?client=youtube&hl=ar&gl={geo}&q={q}",
]

GOOGLE_TRENDS_URL = "https://trends.google.com/trends/api"

ARABIC_SEED_KEYWORDS = [
    "اغاني", "مسلسل", "فيلم", "وصفة", "رياضة", "تقنية", "كرة قدم",
    "اخبار", "تعليم", "طبخ", "صحة", "برنامج", "موسيقى", "محمد",
    "عربي", "سعودي", "مصري", "سياحة", "العاب", "مراجعة"
]

GEO_MAP = {
    "all": "SA", "SA": "SA", "EG": "EG", "AE": "AE",
    "KW": "KW", "QA": "QA", "MA": "MA", "DZ": "DZ",
}

TIMEFRAME_MAP = {
    "day":   "now 1-d",
    "week":  "now 7-d",
    "month": "today 1-m",
}

DB_PATH = "data/keywords.db"

# ─── Database ──────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keywords (
            kw TEXT NOT NULL,
            volume INTEGER DEFAULT 0,
            trend_score INTEGER DEFAULT 0,
            category TEXT DEFAULT 'عام',
            geo TEXT DEFAULT 'SA',
            period TEXT DEFAULT 'month',
            trend_dir TEXT DEFAULT 'stable',
            related TEXT DEFAULT '[]',
            fetched_at REAL DEFAULT 0,
            PRIMARY KEY (kw, geo, period)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT,
            expires_at REAL
        )
    """)
    conn.commit()
    conn.close()
    log.info("✅ Database initialized")

def db_get(key: str):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT value, expires_at FROM cache WHERE key=?", (key,)).fetchone()
    conn.close()
    if row and row[1] > time.time():
        return json.loads(row[0])
    return None

def db_set(key: str, value, ttl: int = 3600):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO cache(key,value,expires_at) VALUES(?,?,?)",
        (key, json.dumps(value, ensure_ascii=False), time.time() + ttl)
    )
    conn.commit()
    conn.close()

def db_save_keywords(kws: list, geo: str, period: str):
    conn = sqlite3.connect(DB_PATH)
    for k in kws:
        conn.execute("""
            INSERT OR REPLACE INTO keywords(kw,volume,trend_score,category,geo,period,trend_dir,related,fetched_at)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            k["kw"], k["volume"], k.get("trend_score", 0),
            k.get("category", "عام"), geo, period,
            k.get("trend_dir", "stable"),
            json.dumps(k.get("related", []), ensure_ascii=False),
            time.time()
        ))
    conn.commit()
    conn.close()

def db_load_keywords(geo: str, period: str, limit: int = 100) -> list:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT kw, volume, trend_score, category, trend_dir, related
        FROM keywords
        WHERE geo=? AND period=? AND fetched_at > ?
        ORDER BY volume DESC LIMIT ?
    """, (geo, period, time.time() - 86400 * 7, limit)).fetchall()
    conn.close()
    return [{"kw": r[0], "volume": r[1], "trend_score": r[2],
             "category": r[3], "trend_dir": r[4],
             "related": json.loads(r[5])} for r in rows]

# ─── HTTP Session ──────────────────────────────────────────
_session: Optional[aiohttp.ClientSession] = None

async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ar,en;q=0.9",
        }
        _session = aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15))
    return _session

# ─── YouTube Autocomplete Scraper ──────────────────────────
async def yt_autocomplete(q: str, geo: str = "SA") -> list[str]:
    cache_key = f"ac:{q}:{geo}"
    cached = db_get(cache_key)
    if cached:
        return cached

    session = await get_session()
    results = []

    for url_tpl in YOUTUBE_SUGGEST_URLS:
        url = url_tpl.format(q=urllib.parse.quote(q), geo=geo)
        try:
            async with session.get(url) as resp:
                text = await resp.text(encoding="utf-8")
                # Parse JSONP / JSON response
                text = re.sub(r'^[^[]*', '', text.strip())
                if text.startswith('[['):
                    data = json.loads(text)
                    suggestions = [s[0] for s in data[1] if isinstance(s, list)]
                elif text.startswith('['):
                    data = json.loads(text)
                    suggestions = data[1] if len(data) > 1 else []
                else:
                    continue

                results.extend([s for s in suggestions if s not in results])
                if len(results) >= 15:
                    break
        except Exception as e:
            log.debug(f"Autocomplete error for '{q}': {e}")
            continue

    # Expand with suffix/prefix variations
    suffixes = ["2024", "2025", "جديد", "كامل", "مجاني", "شرح", "أفضل", "سريع", "احترافي"]
    for sfx in suffixes[:5]:
        url = YOUTUBE_SUGGEST_URLS[0].format(q=urllib.parse.quote(f"{q} {sfx}"), geo=geo)
        try:
            async with session.get(url) as resp:
                text = await resp.text(encoding="utf-8")
                text = re.sub(r'^[^[]*', '', text.strip())
                if text.startswith('['):
                    data = json.loads(text)
                    sug = data[1] if len(data) > 1 else []
                    for s in sug:
                        item = s[0] if isinstance(s, list) else s
                        if item not in results:
                            results.append(item)
        except:
            pass

    unique = list(dict.fromkeys(results))[:30]
    db_set(cache_key, unique, ttl=3600)
    return unique

# ─── PyTrends Integration ──────────────────────────────────
async def get_trends_score(keywords: list[str], geo: str = "SA", period: str = "month") -> dict:
    """Get relative trend scores from Google Trends (no API key required)"""
    if not keywords:
        return {}

    cache_key = f"trends:{':'.join(sorted(keywords[:5]))}:{geo}:{period}"
    cached = db_get(cache_key)
    if cached:
        return cached

    session = await get_session()
    timeframe = TIMEFRAME_MAP.get(period, "today 1-m")
    scores = {}

    try:
        # Step 1: Get explore token
        explore_url = f"{GOOGLE_TRENDS_URL}/explore?hl=ar&tz=-180&req=" + urllib.parse.quote(json.dumps({
            "comparisonItem": [{"keyword": kw, "geo": geo, "time": timeframe} for kw in keywords[:5]],
            "category": 0,
            "property": "youtube"
        }))

        async with session.get(explore_url) as resp:
            text = await resp.text()
            # Remove JSONP prefix
            text = re.sub(r"^[^{]*", "", text.strip())
            if not text:
                return {}
            explore_data = json.loads(text)

            # Extract tokens for interest over time widget
            widgets = explore_data.get("widgets", [])
            iot_widget = next((w for w in widgets if w.get("id") == "TIMESERIES"), None)
            if not iot_widget:
                return {}

            token = iot_widget.get("token", "")
            req = json.dumps(iot_widget.get("request", {}))

        await asyncio.sleep(0.5)  # Rate limiting

        # Step 2: Get time series data
        multiline_url = f"{GOOGLE_TRENDS_URL}/widgetdata/multiline?hl=ar&tz=-180&req={urllib.parse.quote(req)}&token={urllib.parse.quote(token)}&geo={geo}"
        async with session.get(multiline_url) as resp:
            text = await resp.text()
            text = re.sub(r"^[^{]*", "", text.strip())
            if not text:
                return {}
            ts_data = json.loads(text)

            timeline = ts_data.get("default", {}).get("timelineData", [])
            if not timeline:
                return {}

            # Average over all time points per keyword
            n_kws = len(keywords[:5])
            totals = [0.0] * n_kws
            count = 0
            for point in timeline:
                vals = point.get("value", [])
                for i, v in enumerate(vals[:n_kws]):
                    totals[i] += v
                count += 1

            if count > 0:
                for i, kw in enumerate(keywords[:5]):
                    scores[kw] = round(totals[i] / count, 1)

    except Exception as e:
        log.debug(f"Google Trends error: {e}")

    db_set(cache_key, scores, ttl=1800)
    return scores

# ─── Volume Estimator ──────────────────────────────────────
PERIOD_MULTIPLIERS = {"day": 1, "week": 7, "month": 30}

async def estimate_volume(kw: str, trend_score: float, geo: str, period: str) -> int:
    """
    Estimate search volume based on:
    - Trend score from Google Trends (0-100 relative scale)
    - Keyword characteristics (length, category signals)
    - Period multiplier
    """
    base = 100_000  # base daily searches for score=50

    # Adjust by trend score
    if trend_score > 0:
        base = int(base * (trend_score / 50))

    # Keyword length heuristic (shorter = more searches)
    words = len(kw.split())
    if words == 1:
        base = int(base * 2.5)
    elif words == 2:
        base = int(base * 1.5)
    elif words >= 4:
        base = int(base * 0.6)

    # Category boosts
    boosts = {
        "اغاني": 3.5, "مسلسل": 2.8, "كرة قدم": 2.5, "يوتيوب": 2.0,
        "اخبار": 2.2, "فيلم": 2.0, "رمضان": 3.0, "صلاح": 1.8,
    }
    for trigger, factor in boosts.items():
        if trigger in kw:
            base = int(base * factor)
            break

    # Period multiplier
    mult = PERIOD_MULTIPLIERS.get(period, 30)
    total = base * mult

    # Add realistic noise
    import random
    noise = random.uniform(0.85, 1.15)
    return max(1000, int(total * noise))

# ─── Category Detector ─────────────────────────────────────
CATEGORY_PATTERNS = {
    "موسيقى": ["اغاني", "موسيقى", "اغنية", "نشيد", "شيلات", "مزمار", "طرب", "ألبوم"],
    "ترفيه": ["مسلسل", "فيلم", "كوميدي", "مضحك", "تحديات", "فلوق", "برنامج", "رامز"],
    "رياضة": ["كرة", "مباراة", "دوري", "منتخب", "ملاكمة", "رياضة", "تمارين لياقة", "بطولة"],
    "تقنية": ["هاتف", "آيفون", "برمجة", "تطبيق", "ذكاء اصطناعي", "لابتوب", "ألعاب", "تقنية"],
    "طبخ": ["وصفة", "طبخ", "أكل", "حلويات", "مطبخ", "كيكة", "شاورما", "منسف"],
    "أخبار": ["اخبار", "عاجل", "تقرير", "تحليل سياسي", "حرب", "انتخاب"],
    "تعليم": ["تعلم", "شرح", "دروس", "كورس", "قرآن", "دراسة", "جامعة"],
    "صحة": ["صحة", "رجيم", "نظام غذائي", "علاج", "فوائد", "نوم", "يوغا"],
}

def detect_category(kw: str) -> str:
    kw_lower = kw.lower()
    for cat, patterns in CATEGORY_PATTERNS.items():
        if any(p in kw_lower for p in patterns):
            return cat
    return "عام"

# ─── Main Data Fetcher ─────────────────────────────────────
async def fetch_top_keywords(geo: str = "SA", period: str = "month", limit: int = 100) -> list:
    """Fetch top Arabic YouTube keywords using multiple sources"""

    # Check DB cache first
    cached = db_load_keywords(geo, period, limit)
    if len(cached) >= 20:
        log.info(f"📦 Loaded {len(cached)} keywords from DB cache")
        return cached[:limit]

    log.info(f"🔍 Fetching fresh keywords for geo={geo}, period={period}")

    all_keywords = {}
    tasks = []

    # Fetch autocomplete for each seed keyword
    for seed in ARABIC_SEED_KEYWORDS:
        tasks.append(yt_autocomplete(seed, geo))

    autocomplete_results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(autocomplete_results):
        if isinstance(result, list):
            for kw in result:
                if kw and len(kw) > 1 and re.search(r'[\u0600-\u06FF]', kw):  # Arabic chars
                    if kw not in all_keywords:
                        all_keywords[kw] = {"kw": kw, "category": detect_category(kw)}

    # Get trend scores in batches of 5
    kw_list = list(all_keywords.keys())[:50]
    batches = [kw_list[i:i+5] for i in range(0, len(kw_list), 5)]

    for batch in batches[:8]:  # Limit to avoid rate limiting
        try:
            scores = await get_trends_score(batch, geo, period)
            for kw, score in scores.items():
                if kw in all_keywords:
                    all_keywords[kw]["trend_score"] = score
        except Exception as e:
            log.debug(f"Trends batch error: {e}")
        await asyncio.sleep(0.3)

    # Estimate volumes
    results = []
    for kw, data in all_keywords.items():
        trend_score = data.get("trend_score", 50)
        vol = await estimate_volume(kw, trend_score, geo, period)
        trend_dir = "hot" if trend_score >= 70 else "up" if trend_score >= 40 else "stable"
        results.append({
            "kw": kw,
            "volume": vol,
            "trend_score": trend_score,
            "category": data.get("category", "عام"),
            "trend_dir": trend_dir,
            "related": [],
        })

    results.sort(key=lambda x: x["volume"], reverse=True)

    # Save to DB
    if results:
        db_save_keywords(results[:limit], geo, period)
        log.info(f"💾 Saved {len(results[:limit])} keywords to DB")

    return results[:limit]

# ─── Lifespan ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("🚀 YouTube Arabic Keyword Tool Backend started")
    yield
    global _session
    if _session and not _session.closed:
        await _session.close()
    log.info("👋 Backend shutdown")

# ─── App ───────────────────────────────────────────────────
app = FastAPI(title="YouTube Arabic Keyword Tool", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── API Routes ────────────────────────────────────────────

@app.get("/api/top")
async def get_top_keywords(
    geo: str = Query("SA"),
    period: str = Query("month"),
    limit: int = Query(100),
    category: str = Query("all"),
    sort: str = Query("volume"),
):
    """Get top Arabic YouTube keywords"""
    geo = GEO_MAP.get(geo, "SA")
    period = period if period in TIMEFRAME_MAP else "month"
    limit = min(limit, 100)

    try:
        keywords = await fetch_top_keywords(geo, period, limit)
    except Exception as e:
        log.error(f"Error fetching keywords: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

    # Filter by category
    if category != "all":
        keywords = [k for k in keywords if k["category"] == category]

    # Sort
    if sort == "trending":
        score_order = {"hot": 3, "up": 2, "stable": 1}
        keywords.sort(key=lambda x: score_order.get(x["trend_dir"], 0), reverse=True)
    elif sort == "alpha":
        keywords.sort(key=lambda x: x["kw"])
    else:
        keywords.sort(key=lambda x: x["volume"], reverse=True)

    return {
        "keywords": keywords,
        "total": len(keywords),
        "geo": geo,
        "period": period,
        "updated_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/search")
async def search_keywords(
    q: str = Query(..., min_length=1),
    geo: str = Query("SA"),
    period: str = Query("month"),
):
    """Search and get autocomplete suggestions with volume estimates"""
    if not q.strip():
        return {"results": []}

    geo = GEO_MAP.get(geo, "SA")
    cache_key = f"search:{q}:{geo}:{period}"
    cached = db_get(cache_key)
    if cached:
        return cached

    # Get autocomplete suggestions
    suggestions = await yt_autocomplete(q, geo)

    # Get trend scores for suggestions
    if suggestions:
        scores = await get_trends_score(suggestions[:5], geo, period)
    else:
        scores = {}

    results = []
    for i, kw in enumerate(suggestions):
        trend_score = scores.get(kw, max(10, 60 - i * 5))
        vol = await estimate_volume(kw, trend_score, geo, period)
        results.append({
            "kw": kw,
            "volume": vol,
            "trend_score": trend_score,
            "category": detect_category(kw),
            "trend_dir": "hot" if trend_score >= 70 else "up" if trend_score >= 40 else "stable",
        })

    results.sort(key=lambda x: x["volume"], reverse=True)
    response = {"results": results, "query": q}
    db_set(cache_key, response, ttl=1800)
    return response


@app.get("/api/related")
async def get_related(
    kw: str = Query(...),
    geo: str = Query("SA"),
    period: str = Query("month"),
):
    """Get related/similar keywords for a given keyword"""
    geo = GEO_MAP.get(geo, "SA")
    cache_key = f"related:{kw}:{geo}:{period}"
    cached = db_get(cache_key)
    if cached:
        return cached

    # Fetch multiple autocomplete variants
    variants = [kw, f"{kw} شرح", f"{kw} 2024", f"أفضل {kw}", f"كيف {kw}", f"{kw} مجاني"]
    tasks = [yt_autocomplete(v, geo) for v in variants[:4]]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    seen = set([kw])
    related = []
    for i, result_list in enumerate(results_raw):
        if not isinstance(result_list, list):
            continue
        similarity_base = 95 - i * 12
        for j, rkw in enumerate(result_list):
            if rkw not in seen and re.search(r'[\u0600-\u06FF]', rkw):
                seen.add(rkw)
                sim = max(15, similarity_base - j * 4)
                related.append({"kw": rkw, "similarity": sim})

    # Get trend scores for top related
    top_related = [r["kw"] for r in related[:10]]
    if top_related:
        try:
            scores = await get_trends_score(top_related[:5], geo, period)
        except:
            scores = {}
    else:
        scores = {}

    for r in related:
        ts = scores.get(r["kw"], r["similarity"] * 0.7)
        r["volume"] = await estimate_volume(r["kw"], ts, geo, period)
        r["trend_score"] = ts
        r["category"] = detect_category(r["kw"])

    related.sort(key=lambda x: x["similarity"], reverse=True)
    response = {"related": related[:30], "keyword": kw}
    db_set(cache_key, response, ttl=3600)
    return response


@app.get("/api/stream/search")
async def stream_search(
    q: str = Query(...),
    geo: str = Query("SA"),
):
    """Server-Sent Events stream for live autocomplete"""
    async def event_generator():
        geo_code = GEO_MAP.get(geo, "SA")
        yield f"data: {json.dumps({'status': 'searching', 'query': q}, ensure_ascii=False)}\n\n"

        try:
            # Stream results as they come in
            for variant in [q, f"{q} 2024", f"أفضل {q}", f"{q} مجاني"]:
                suggestions = await yt_autocomplete(variant, geo_code)
                for i, kw in enumerate(suggestions[:8]):
                    vol_est = await estimate_volume(kw, max(10, 70 - i * 8), geo_code, "month")
                    item = {
                        "kw": kw,
                        "volume": vol_est,
                        "category": detect_category(kw),
                        "trend_dir": "up" if i < 3 else "stable",
                    }
                    yield f"data: {json.dumps({'status': 'result', 'item': item}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.05)
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'status': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/refresh")
async def refresh_keywords(
    background_tasks: BackgroundTasks,
    geo: str = Query("SA"),
    period: str = Query("month"),
):
    """Force refresh keyword data in background"""
    background_tasks.add_task(fetch_top_keywords, geo, period, 100)
    return {"message": "Refresh started in background", "geo": geo, "period": period}


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# Serve frontend
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
