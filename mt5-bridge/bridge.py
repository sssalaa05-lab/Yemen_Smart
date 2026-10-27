# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║   NEXUS MT5 BRIDGE — الجسر بين MetaTrader 5 ونظام Nexus                  ║
║                                                                          ║
║   يعمل على جهاز ويندوز بجانب ترمينال MT5 ويقوم بثلاث مهام:               ║
║   1) يقرأ الأسعار اللحظية (Ticks) من MT5 ويرسلها لنظام Nexus             ║
║   2) يقرأ الشموع (OHLCV M5) ويرسلها بنفس مسار التغذية الداخلية           ║
║   3) (اختياري) يستقبل قرارات الوكلاء وينفذها في MT5 فعلياً               ║
║                                                                          ║
║   المتطلبات:  Python 3.10+  على ويندوز                                   ║
║               pip install MetaTrader5 requests                           ║
║               ترمينال MT5 مفتوح + زر Algo Trading مفعّل (للتنفيذ فقط)    ║
║                                                                          ║
║   ─────────────────────────────────────────────────────────────────────  ║
║   ⚙️  الإعدادات تُقرأ من متغيرات البيئة (أكثر أمانًا وأسهل تغييرًا):      ║
║                                                                          ║
║   NEXUS_URL          (إلزامي) رابط النظام كاملًا                         ║
║                                    مثال:                                ║
║   https://preview-chat-<chat_id>.space-z.ai                             ║
║   أو http://localhost:3000 (للاختبار المحلي)                             ║
║                                                                          ║
║   NEXUS_BRIDGE_TOKEN (إلزامي) توكن الجسر (من .env على الخادم)            ║
║                                    مثال: nxb-xxxxxxxxxxxxxxxx          ║
║                                                                          ║
║   ─────────────────────────────────────────────────────────────────────  ║
║   مثال CMD على ويندوز:                                                   ║
║   set NEXUS_URL=https://preview-chat-<chat_id>.space-z.ai               ║
║   set NEXUS_BRIDGE_TOKEN=nxb-xxxxxxxxxxxxxxxx                           ║
║   python bridge.py                                                       ║
║                                                                          ║
║   مثال PowerShell:                                                       ║
║   $env:NEXUS_URL="https://preview-chat-<chat_id>.space-z.ai"            ║
║   $env:NEXUS_BRIDGE_TOKEN="nxb-xxxxxxxxxxxxxxxx"                        ║
║   python bridge.py                                                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

try:
    import MetaTrader5 as mt5
except ImportError:
    print("❌ مكتبة MetaTrader5 غير مثبتة — شغّل:  pip install MetaTrader5")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════════════════
#  الإعدادات — تُقرأ من متغيرات البيئة (لا تُعدّل الكود يدويًا)
# ════════════════════════════════════════════════════════════════════════════

# عنوان نظام Nexus — يُقرأ من NEXUS_URL (إلزامي)
# مثال: "https://preview-chat-<chat_id>.space-z.ai" أو "http://localhost:3000"
NEXUS_URL = os.environ.get("NEXUS_URL", "").rstrip("/")

# مفتاح الجسر — يُقرأ من NEXUS_BRIDGE_TOKEN (إلزامي)
# ⚠️ لا تضع التوكن في الكود! استخدم متغير البيئة دائمًا
BRIDGE_TOKEN = os.environ.get("NEXUS_BRIDGE_TOKEN", "")

# التحقق من وجود الإعدادات الإلزامية عند بدء التشغيل
if not NEXUS_URL:
    print("❌ NEXUS_URL غير محدد!")
    print("   حدد رابط النظام قبل تشغيل الجسر:")
    print('   set NEXUS_URL=https://preview-chat-<chat_id>.space-z.ai')
    sys.exit(1)

if not BRIDGE_TOKEN:
    print("❌ NEXUS_BRIDGE_TOKEN غير محدد!")
    print("   حدد توكن الجسر قبل تشغيل الجسر:")
    print('   set NEXUS_BRIDGE_TOKEN=nxb-xxxxxxxxxxxxxxxx')
    sys.exit(1)

# طباعة الإعدادات الفعالة (للتأكد قبل التشغيل)
print("═" * 70)
print("  NEXUS MT5 BRIDGE — الإعدادات الفعالة")
print("═" * 70)
print(f"  NEXUS_URL          = {NEXUS_URL}")
print(f"  NEXUS_BRIDGE_TOKEN = {BRIDGE_TOKEN[:15]}{'*' * (len(BRIDGE_TOKEN) - 15)}")
print("═" * 70)
print()

# الرموز المنطقية في Nexus ← الاسم الفعلي في نافذة Market Watch بترمينالك
# (بعض الوسطاء يستخدمون GOLD أو XAUUSD.a أو XAUUSDm — اكتب اسمك الصحيح هنا)
SYMBOL_MAP: dict[str, str] = {
    "XAUUSD": "XAUUSD",
    # "BTCUSD": "BTCUSD",
    # "EURUSD": "EURUSD",
}

# فارق توقيت سيرفر الوسيط عن UTC بالساعات (وثيقة MQL5 Date&Time):
#   "auto" (موصى به) = يقيسه الجسر تلقائياً من أحدث tick أثناء نشاط السوق
#                      ويعيد الفحص كل 30 دقيقة → يلتقط التوقيت الصيفي وحده.
#   أو رقم ثابت مثل 2.0 / 3.0 إذا عرفت فارق سيرفرك وأردت تثبيته يدوياً.
SERVER_TZ_OFFSET_HOURS: Any = "auto"
DEFAULT_TZ_OFFSET_HOURS = 2.0      # يُستخدم مؤقتاً إذا تعذر القياس (السوق مغلق)
SERVER_TIME_FILE = "server_time.json"  # اختياري: ملف EA الرفيق (NexusTimeEA) — فارق دقيق 100%
TZ_RECHECK_SEC = 1800.0            # إعادة قياس الفارق كل 30 دقيقة في وضع auto

POLL_TICKS_SEC = 1.0      # كل ثانية: قراءة السعر اللحظي
POLL_BARS_SEC = 15.0      # كل 15 ثانية: فحص شموع M5 جديدة
HEARTBEAT_SEC = 30.0      # نبضة الحالة كل 30 ثانية
DECISION_POLL_SEC = 45.0  # فحص قرارات الوكلاء كل 45 ثانية
SEED_BARS = 1500          # عدد الشموع المرسلة عند أول اتصال (تاريخ) — يكفي لتدريب ML فورًا

# ملف تفريغ التقويم الاقتصادي (اختياري — من EA رفيق لاحقاً؛ اتركه كما هو
# إن لم يكن لديك: الجسر يتجاهله بهدوء حتى يظهر)
CALENDAR_FILE = "calendar_dump.json"
CALENDAR_POLL_SEC = 120.0

def _calendar_candidates() -> list[str]:
    """مسارات محتملة لملف التقويم: مجلد العمل + Common\\Files لميتاتريدر."""
    cands = [os.path.abspath(CALENDAR_FILE)]
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        cands.append(os.path.join(
            appdata, "MetaQuotes", "Terminal", "Common", "Files", "calendar_dump.json"))
    return cands

# ── التنفيذ (اتركه False في البداية!) ────────────────────────────────────────
EXECUTE = False           # True = ينفذ قرارات الوكلاء في MT5 فعلياً
MIN_CONVICTION = 65       # لا ينفذ إلا إذا كانت قناعة القرار >= هذا الرقم
LOT = 0.01                # حجم العقد
SL_POINTS = 300           # وقف الخسارة بالنقاط (0 = بدون) — للذهب 300 نقطة ≈ 3$
TP_POINTS = 600           # الهدف بالنقاط (0 = بدون)
ALLOW_REAL_ACCOUNT = False  # ⚠️ اجعلها True فقط إذا كنت تريد التنفيذ على حساب حقيقي
# ════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("nexus_bridge.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("bridge")

SESSION = requests.Session()
SESSION.headers.update({
    "x-bridge-token": BRIDGE_TOKEN,
    "Content-Type": "application/json",
})

_state: dict[str, Any] = {
    "tz_offset_hours": DEFAULT_TZ_OFFSET_HOURS,  # يُحدَّث بـ resolve_tz_offset()
    "last_bar_ts": {},     # symbol → آخر timestamp شمعة أُرسلت
    "seeded": set(),       # الرموز التي أرسلنا تاريخها
    "last_tick": {},       # symbol → آخر (time,bid,ask) لتفادي التكرار
    "last_decision_id": None,
    "last_tick_ts": None,
    "calendar_mtime": 0.0, # آخر تعديل لملف التقويم
}


# ─────────────────────────────── أدوات HTTP ────────────────────────────────
# إعادة المحاولة عند فشل الشبكة (502 Bad Gateway, timeout, إلخ)
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = [1, 3, 8]  # ثوانٍ بين المحاولات


def _post(path: str, payload: dict) -> dict | None:
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            r = SESSION.post(f"{NEXUS_URL}{path}", json=payload, timeout=15)
            if r.status_code == 401:
                log.error("❌ التوكن مرفوض من الخادم — تحقق من NEXUS_BRIDGE_TOKEN")
                return None
            if r.status_code == 502:
                log.warning("⚠️  502 Bad Gateway — الخادم لا يستجيب (محاولة %d/%d)",
                            attempt + 1, MAX_RETRIES)
                last_exc = f"502 Bad Gateway for {path}"
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF_SEC[attempt])
                    continue
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            last_exc = str(exc)
            log.warning("POST %s فشل (محاولة %d/%d): %s",
                        path, attempt + 1, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SEC[attempt])
    log.error("❌ POST %s فشل نهائيًا بعد %d محاولات: %s",
              path, MAX_RETRIES, last_exc)
    return None


def _get(path: str) -> dict | None:
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            r = SESSION.get(f"{NEXUS_URL}{path}", timeout=15)
            if r.status_code == 404:
                return None
            if r.status_code == 502:
                log.warning("⚠️  502 Bad Gateway على GET %s (محاولة %d/%d)",
                            path, attempt + 1, MAX_RETRIES)
                last_exc = f"502 Bad Gateway for {path}"
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF_SEC[attempt])
                    continue
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            last_exc = str(exc)
            log.warning("GET %s فشل (محاولة %d/%d): %s",
                        path, attempt + 1, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SEC[attempt])
    log.error("❌ GET %s فشل نهائيًا بعد %d محاولات: %s",
              path, MAX_RETRIES, last_exc)
    return None


def _server_to_utc(epoch_seconds: int) -> str:
    """تحويل توقيت سيرفر الوسيط إلى UTC ISO (TimeCurrent أساسه توقيت السيرفر)."""
    dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc) - timedelta(
        hours=_state.get("tz_offset_hours", DEFAULT_TZ_OFFSET_HOURS)
    )
    return dt.isoformat()


# ────────────── ضبط فارق التوقيت (استفادة من وثيقة Date&Time) ──────────────
def _read_ea_offset_hours() -> float | None:
    """الفارق الدقيق من EA رفيق يكتب TimeCurrent() - TimeGMT() في ملف JSON.
    (دالتا TimeCurrent/TimeGMT بلغة MQL5 داخل الترمينال فقط — حزمة بايثون
    لا تملكهما، لذا يمر الفارق الدقيق عبر ملف مثل التقويم)."""
    try:
        with open(os.path.abspath(SERVER_TIME_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
        off = (float(data["server_time"]) - float(data["gmt_time"])) / 3600.0
    except Exception:
        return None  # لا ملف / ملف تالف → تجاهل بهدوء
    if -13.0 <= off <= 13.0:
        return round(off * 4) / 4  # أقرب ربع ساعة
    return None


def _measure_tick_offset_hours(symbols: dict[str, str]) -> float | None:
    """قياس بلا EA: أحدث tick.time بتوقيت السيرفر − UTC الآن.
    يعمل فقط عند نشاط السوق (tick طازج خلال ~10 دقائق) وإلا يرجع None."""
    for _nexus_sym, mt5_sym in symbols.items():
        t = mt5.symbol_info_tick(mt5_sym)
        if not t or not t.time:
            continue
        est = float(t.time) - time.time()              # ثوانٍ
        snapped = round(est / 1800.0) * 1800.0         # أقرب 30 دقيقة
        if 0 <= est <= 13.5 * 3600 and abs(est - snapped) <= 600:
            return snapped / 3600.0
    return None


def resolve_tz_offset(symbols: dict[str, str], initial: bool = False) -> None:
    """الأولوية: رقم ثابت في الإعدادات > ملف EA الرفيق > قياس tick > افتراضي."""
    if isinstance(SERVER_TZ_OFFSET_HOURS, (int, float)):
        _state["tz_offset_hours"] = float(SERVER_TZ_OFFSET_HOURS)
        if initial:
            log.info("🕒 فارق التوقيت: ثابت %.1f ساعة (إعداد يدوي)", float(SERVER_TZ_OFFSET_HOURS))
        return
    ea = _read_ea_offset_hours()
    if ea is not None:
        changed = _state.get("tz_offset_hours") != ea
        _state["tz_offset_hours"] = ea
        if initial or changed:
            log.info("🕒 فارق التوقيت: %+.2f ساعة (من ملف EA الرفيق — دقيق ويشمل التوقيت الصيفي)", ea)
        return
    measured = _measure_tick_offset_hours(symbols)
    if measured is not None:
        changed = _state.get("tz_offset_hours") != measured
        _state["tz_offset_hours"] = measured
        if initial or changed:
            log.info("🕒 فارق التوقيت المقاس من أحدث tick: %+.1f ساعة%s",
                     measured, "" if initial else " (تحديث تلقائي — غالباً تبديل توقيت صيفي)")
        return
    if initial:
        log.warning("🕒 تعذر قياس الفارق (السوق مغلق على الأرجح) — استخدام %.1f ساعة مؤقتاً؛ "
                    "سيُعاد القياس تلقائياً عند أول نشاط", DEFAULT_TZ_OFFSET_HOURS)


# ─────────────────────────────── الاتصال بـ MT5 ─────────────────────────────
def connect_mt5() -> bool:
    info = mt5.initialize()
    if not info:
        log.error("❌ فشل الاتصال بالترمينال: %s — تأكد أن MT5 مفتوح", mt5.last_error())
        return False
    acc = mt5.account_info()
    if acc:
        mode = {0: "DEMO ✅", 1: "CONTEST", 2: "REAL ⚠️"}.get(
            acc.trade_mode, str(acc.trade_mode)
        )
        log.info("✅ متصل: حساب %s | %s | %s | رصيد %.2f %s",
                 acc.login, acc.server, mode, acc.balance, acc.currency)
        if acc.trade_mode == 2 and EXECUTE and not ALLOW_REAL_ACCOUNT:
            log.error("🛡️ حماية: حساب حقيقي + EXECUTE=True مرفوض. اجعل ALLOW_REAL_ACCOUNT=True عمداً أو استخدم حساب Demo.")
            sys.exit(1)
        _state["account"] = {
            "login": acc.login, "server": acc.server,
            "mode": mode, "balance": acc.balance,
        }
    ver = mt5.version()
    log.info("✅ إصدار الترمينال: %s", ver)
    return True


def resolve_symbols() -> dict[str, str]:
    """التحقق من وجود الرموز في Market Watch وإرجاع الموجود فقط."""
    ok: dict[str, str] = {}
    for nexus_sym, mt5_sym in SYMBOL_MAP.items():
        si = mt5.symbol_info(mt5_sym)
        if si is None:
            log.warning("⚠️ الرمز %s غير موجود في الترمينال — تجاهله (عدّل SYMBOL_MAP)", mt5_sym)
            continue
        if not si.visible:
            mt5.symbol_select(mt5_sym, True)
        ok[nexus_sym] = mt5_sym
        log.info("📌 %s → %s (digits=%d, point=%g)",
                 nexus_sym, mt5_sym, si.digits, si.point)
    return ok


# ─────────────────────────────── حلقة التيكات ───────────────────────────────
def tick_loop(symbols: dict[str, str]) -> None:
    ticks = []
    for nexus_sym, mt5_sym in symbols.items():
        t = mt5.symbol_info_tick(mt5_sym)
        if not t or not t.bid or not t.ask:
            continue
        key = (t.time, round(t.bid, 2), round(t.ask, 2))
        if _state["last_tick"].get(nexus_sym) == key:
            continue  # لا تغير → لا إرسال
        _state["last_tick"][nexus_sym] = key
        ticks.append({
            "symbol": nexus_sym,
            "bid": float(t.bid),
            "ask": float(t.ask),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        _state["last_tick_ts"] = datetime.now(timezone.utc).isoformat()
    if ticks:
        _post("/api/v2/bridge/ticks", {"ticks": ticks})


# ─────────────────────────────── حلقة الشموع ────────────────────────────────
def _field(row, name: str, default=0):
    """قراءة حقل من صف rates بأمان — صفوف copy_rates مصفوفة numpy.void:
    تدعم r[name] فقط ولا تملك .get()، وبعض نسخ MetaTrader5 القديمة
    بلا حقل real_volume أصلاً — فنرجع الافتراضي بدل الانهيار."""
    try:
        v = row[name]
    except Exception:  # ValueError/KeyError/IndexError حسب النوع
        return default
    return default if v is None else v


def bars_loop(symbols: dict[str, str]) -> None:
    for nexus_sym, mt5_sym in symbols.items():
        rates = mt5.copy_rates_from_pos(mt5_sym, mt5.TIMEFRAME_M5, 0, SEED_BARS)
        if rates is None or len(rates) == 0:
            log.warning("⚠️ لا شموع لـ %s", mt5_sym)
            continue
        last_sent = _state["last_bar_ts"].get(nexus_sym)
        bars = []
        for r in rates:
            ts_iso = _server_to_utc(int(r["time"]))
            if last_sent and ts_iso <= last_sent:
                continue
            # حجم حقيقي (بورصة/عقود) إن توفّر وإلا حجم التيك (فوركس)
            real_vol = int(_field(r, "real_volume", 0) or 0)
            vol = float(real_vol) if real_vol > 0 else float(r["tick_volume"])
            bars.append({
                "symbol": nexus_sym,
                "timeframe": "M5",
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": vol,
                "spread": int(_field(r, "spread", 0) or 0),
                "timestamp": ts_iso,
            })
        if not bars:
            continue
        seed = nexus_sym not in _state["seeded"]
        payload_bars = bars if seed else bars[-5:]
        res = _post("/api/v2/bridge/bars", {"bars": payload_bars})
        if res and res.get("accepted") is not None:
            _state["last_bar_ts"][nexus_sym] = bars[-1]["timestamp"]
            if seed:
                _state["seeded"].add(nexus_sym)
                log.info("🌱 بذر %d شمعة لـ %s (accepted=%s)",
                         len(payload_bars), nexus_sym, res.get("accepted"))
            else:
                log.info("📊 شمعة جديدة %s: close=%.2f vol=%d",
                         nexus_sym, bars[-1]["close"], bars[-1]["volume"])


# ─────────────────────────────── نبضة الحالة ────────────────────────────────
def heartbeat(symbols: dict[str, str]) -> None:
    """Market Information موسّعة: حالة الترمينال + الحساب + تفاصيل الرموز."""
    payload: dict[str, Any] = {
        "mode": "execute" if EXECUTE else "data-only",
        "symbols": list(symbols.keys()),
        "last_tick_ts": _state.get("last_tick_ts"),
        "tz_offset_hours": _state.get("tz_offset_hours"),
    }

    # TerminalInfo: هل زر Algo Trading مفعّل؟ هل الوسيط متصل؟
    ti = mt5.terminal_info()
    if ti:
        payload["terminal"] = {
            "name": ti.name,
            "build": ti.build,
            "company": ti.company,
            "trade_allowed": bool(ti.trade_allowed),   # زر Algo Trading
            "connected": bool(ti.connected),           # اتصال بسيرفر الوسيط
            "ping_last_ms": int(ti.ping_last),
        }
        if EXECUTE and not ti.trade_allowed:
            log.error("🚨 زر Algo Trading مفعّل؟ EXECUTE=True لكن trade_allowed=False — التنفيذ سيفشل!")
        if not ti.connected:
            log.warning("⚠️ الترمينال غير متصل بسيرفر الوسيط")

    # AccountInfo: رصيد/حقوق/هامش/رافعة
    acc = mt5.account_info()
    if acc:
        mode = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(acc.trade_mode, str(acc.trade_mode))
        payload["account"] = {
            "login": acc.login, "server": acc.server, "mode": mode,
            "balance": acc.balance, "equity": acc.equity,
            "margin": acc.margin, "free_margin": acc.margin_free,
            "margin_level": acc.margin_level, "leverage": acc.leverage,
            "currency": acc.currency,
        }

    # تفاصيل الرموز (SymbolInfo): السبريد الحالي والسواب وقيود اللوت
    details = {}
    for nexus_sym, mt5_sym in symbols.items():
        si = mt5.symbol_info(mt5_sym)
        tk = mt5.symbol_info_tick(mt5_sym)
        if not si:
            continue
        details[nexus_sym] = {
            "mt5_symbol": mt5_sym,
            "spread_points": int(tk.time and ((tk.ask - tk.bid) / si.point)) if (tk and si.point) else None,
            "point": si.point, "digits": si.digits,
            "volume_min": si.volume_min, "volume_max": si.volume_max,
            "volume_step": si.volume_step,
            "swap_long": si.swap_long, "swap_short": si.swap_short,
            "trade_mode": si.trade_mode,
        }
    payload["symbols_detail"] = details
    _post("/api/v2/bridge/heartbeat", payload)


# ─────────────────────── خطاف التقويم الاقتصادي ─────────────────────────────
def calendar_loop() -> None:
    """يقرأ ملف تفريغ التقويم (من EA رفيق NexusCalendarEA.mq5) وينشره للخادم.
    الوثائق: MQL5 Economic Calendar (CalendarValueHistory…) غير متاح في
    حزمة بايثون — لذلك يمر عبر EA يكتب ملف JSON في مجلد Common Files.
    بلا ملف = تجاهل صامت."""
    for path in _calendar_candidates():
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue  # لا ملف هنا — جرّب المسار التالي
        mtimes = _state.setdefault("calendar_mtimes", {})
        if mtime <= mtimes.get(path, 0.0):
            return  # لم يتغير منذ آخر نشر
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            events = data.get("events", data) if isinstance(data, dict) else data
            if isinstance(events, list) and events:
                res = _post("/api/v2/bridge/calendar", {"events": events[:200]})
                if res:
                    mtimes[path] = mtime
                    log.info("📅 تقويم اقتصادي منشور: %d حدثاً (%s)",
                             res.get("accepted", 0), path)
                    return
        except Exception as exc:
            log.warning("قراءة ملف التقويم فشلت (%s): %s", path, exc)


# ──────────────────────── التنفيذ: قراءة وترتيب أوامر ───────────────────────
def _normalize_volume(si, vol: float) -> float:
    step = si.volume_step or 0.01
    v = max(si.volume_min, min(si.volume_max, vol))
    return round(round(v / step) * step, 8)


def _order_send_safe(request: dict) -> Any:
    res = mt5.order_send(request)
    if res and res.retcode == 10030:  # filling mode غير مدعوم → جرّب FOK ثم RETURN
        for fill in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
            request["type_filling"] = fill
            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                break
    return res


def decision_loop(symbols: dict[str, str]) -> None:
    """يقرأ آخر قرار من الوكلاء وينفذه إذا كان BUY/SELL بقناعة كافية."""
    for nexus_sym, mt5_sym in symbols.items():
        data = _get(f"/api/agents/decision/{nexus_sym}")
        if not data:
            continue
        d = data.get("data", data) if isinstance(data, dict) else {}
        verdict = str(d.get("verdict") or d.get("decision") or "").upper()
        conviction = float(d.get("conviction") or d.get("confidence") or 0)
        cid = str(d.get("cycle_id") or d.get("ts") or "")
        if not cid or cid == _state["last_decision_id"]:
            continue
        _state["last_decision_id"] = cid
        log.info("🧠 قرار جديد [%s]: %s قناعة=%.0f", cid[:8], verdict, conviction)

        if not EXECUTE:
            log.info("   (وضع البيانات فقط — EXECUTE=False لن يُنفذ)")
            continue
        if verdict not in ("BUY", "SELL") or conviction < MIN_CONVICTION:
            continue

        # صفقة واحدة كحد أقصى لكل رمز
        if mt5.positions_get(symbol=mt5_sym):
            log.info("   يوجد مركز مفتوح على %s — تجاهل", mt5_sym)
            continue

        si = mt5.symbol_info(mt5_sym)
        tk = mt5.symbol_info_tick(mt5_sym)
        if not si or not tk:
            continue
        is_buy = verdict == "BUY"
        price = tk.ask if is_buy else tk.bid
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        point = si.point
        req: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": mt5_sym,
            "volume": _normalize_volume(si, LOT),
            "type": order_type,
            "price": price,
            "deviation": 30,
            "magic": 20261026,
            "comment": f"nexus {conviction:.0f}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if SL_POINTS > 0:
            req["sl"] = round(price - SL_POINTS * point * 10, si.digits) if is_buy \
                else round(price + SL_POINTS * point * 10, si.digits)
        if TP_POINTS > 0:
            req["tp"] = round(price + TP_POINTS * point * 10, si.digits) if is_buy \
                else round(price - TP_POINTS * point * 10, si.digits)

        res = _order_send_safe(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info("✅ نُفذت: %s #%d @ %.2f", verdict, res.order, res.price)
        else:
            log.error("❌ فشل التنفيذ: %s", getattr(res, "comment", mt5.last_error()))


# ─────────────────────────────────── الرئيسية ───────────────────────────────
def main() -> None:
    log.info("═══ NEXUS MT5 BRIDGE ═══")
    log.info("الخادم: %s", NEXUS_URL)
    log.info("الوضع: %s", "تنفيذ فعلي ⚡" if EXECUTE else "بيانات فقط 📡")

    if not connect_mt5():
        sys.exit(1)
    symbols = resolve_symbols()
    if not symbols:
        log.error("لا رموز صالحة — عدّل SYMBOL_MAP")
        sys.exit(1)
    resolve_tz_offset(symbols, initial=True)

    last_bars = last_hb = last_dec = last_cal = last_tz = 0.0
    try:
        while True:
            now = time.monotonic()
            try:
                if not mt5.terminal_info():
                    log.warning("الترمينال انفصل — إعادة الاتصال…")
                    time.sleep(3)
                    if not connect_mt5():
                        continue
                tick_loop(symbols)
                if now - last_bars >= POLL_BARS_SEC:
                    bars_loop(symbols)
                    last_bars = now
                if now - last_hb >= HEARTBEAT_SEC:
                    heartbeat(symbols)
                    last_hb = now
                if now - last_dec >= DECISION_POLL_SEC:
                    decision_loop(symbols)
                    last_dec = now
                if now - last_cal >= CALENDAR_POLL_SEC:
                    calendar_loop()
                    last_cal = now
                if now - last_tz >= TZ_RECHECK_SEC:
                    resolve_tz_offset(symbols)  # يلتقط تبديل التوقيت الصيفي تلقائياً
                    last_tz = now
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("خطأ في الحلقة — الاستمرار")
            time.sleep(POLL_TICKS_SEC)
    except KeyboardInterrupt:
        log.info("⏹️ إيقاف بواسطة المستخدم")
    finally:
        mt5.shutdown()
        log.info("تم الإغلاق")


if __name__ == "__main__":
    main()
