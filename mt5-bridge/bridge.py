# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║   ZYSB — Yemen Smart Bridge v3.0                                        ║
║   جسر MetaTrader 5 ↔ نظام Yemen Smart                                  ║
║   (ZYSB = Yemen Smart Bridge — يُميّزه عن الجسور الأخرى)                ║
║                                                                          ║
║   التحسينات عن v2.0:                                                    ║
║   ✦ كل الإعدادات من .env (لا hardcoded)                                ║
║   ✦ قراءة .env تلقائيًا عبر python-dotenv                             ║
║   ✦ SYMBOL_MAP من .env (لا تعديل الكود)                                ║
║   ✦ التنفيذ عبر API (لا mt5.order_send مباشر)                          ║
║   ✦ إرسال حالة المراكز المفتوحة                                        ║
║   ✦ إعادة محاولة محدودة (2 retries) على timeouts العابرة              ║
║   ✦ إعادة اتصال تلقائية عند انقطاع MT5                                ║
║   ✦ logging مُحسّن مع تدوير الملفات                                    ║
║                                                                          ║
║   الإعدادات (كلها في .env — انسخ .env.example إلى .env):               ║
║   NEXUS_URL                   (إلزامي) رابط النظام                     ║
║   NEXUS_BRIDGE_TOKEN          (إلزامي) توكن الجسر                      ║
║   BRIDGE_SYMBOLS              (اختياري) XAUUSD,BTCUSD — افتراضي XAUUSD ║
║   BRIDGE_EXECUTE              (اختياري) false — true لتنفيذ القرارات   ║
║   BRIDGE_LOT                  (اختياري) 0.01                            ║
║   BRIDGE_SL_POINTS            (اختياري) 300                             ║
║   BRIDGE_TP_POINTS            (اختياري) 600                             ║
║   BRIDGE_ALLOW_REAL_ACCOUNT   (اختياري) false — true لحساب حقيقي       ║
║   BRIDGE_POLL_TICKS_SEC       (اختياري) 5.0                             ║
║   BRIDGE_POLL_BARS_SEC        (اختياري) 60.0                            ║
║   BRIDGE_HEARTBEAT_SEC        (اختياري) 60.0                            ║
║   BRIDGE_DECISION_POLL_SEC    (اختياري) 120.0                           ║
║   BRIDGE_CALENDAR_POLL_SEC    (اختياري) 300.0                           ║
║   BRIDGE_SEED_BARS            (اختياري) 1500                            ║
║   BRIDGE_SERVER_TZ_OFFSET     (اختياري) auto                            ║
║   BRIDGE_LOG_LEVEL            (اختياري) INFO                             ║
║                                                                          ║
║   مثال CMD على ويندوز:                                                   ║
║   copy .env.example .env                                                ║
║   (عدّل .env ثم)                                                         ║
║   python bridge.py                                                       ║
║                                                                          ║
║   أو متغيرات البيئة مباشرة:                                              ║
║   set NEXUS_URL=https://preview-chat-<chat_id>.space-z.ai               ║
║   set NEXUS_BRIDGE_TOKEN=nxb-xxxxxxxxxxxxxxxx                           ║
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
from logging.handlers import RotatingFileHandler
from typing import Any

import requests

# ─────────────────────────────────────────────────────────────────────────────
#  قراءة .env تلقائيًا (إن وُجد python-dotenv)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    # ابحث عن .env في المجلد الحالي ثم مجلد السكربت
    _env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(_env_path):
        _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False

# ─────────────────────────────────────────────────────────────────────────────
#  استيراد MetaTrader5 (إلزامي)
# ─────────────────────────────────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
except ImportError:
    print("❌ مكتبة MetaTrader5 غير مثبتة — شغّل:  pip install MetaTrader5 requests python-dotenv")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════════════════
#  الإعدادات — كلها من متغيرات البيئة (مع قيم افتراضية آمنة)
# ════════════════════════════════════════════════════════════════════════════

def _get_env(name: str, default: str = "") -> str:
    """قراءة متغير بيئة مع إزالة المسافات الزائدة."""
    return os.environ.get(name, default).strip()


def _get_env_bool(name: str, default: bool = False) -> bool:
    """قراءة متغير بيئة كقيمة منطقية."""
    v = _get_env(name, "").lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on", "y", "صحيح", "نعم")


def _get_env_float(name: str, default: float) -> float:
    """قراءة متغير بيئة كرقم عشري."""
    v = _get_env(name, "")
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        print(f"⚠️  قيمة غير صالحة لـ {name}={v!r} — سيُستخدم الافتراضي {default}")
        return default


def _get_env_int(name: str, default: int) -> int:
    """قراءة متغير بيئة كعدد صحيح."""
    v = _get_env(name, "")
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        print(f"⚠️  قيمة غير صالحة لـ {name}={v!r} — سيُستخدم الافتراضي {default}")
        return default


# ── اسم الجسر (للتمييز في السجلات والـ banner) ──
# ZYSB = Yemen Smart Bridge — يُميّز هذا الجسر عن أي جسور أخرى على نفس الجهاز
BRIDGE_NAME = _get_env("BRIDGE_NAME", "ZYSB")

# ── إعدادات إلزامية ──
NEXUS_URL = _get_env("NEXUS_URL", "").rstrip("/")
BRIDGE_TOKEN = _get_env("NEXUS_BRIDGE_TOKEN", "")

if not NEXUS_URL:
    print("❌ NEXUS_URL غير محدد!")
    print("   اضبطه في .env أو كمتغير بيئة:")
    print('   NEXUS_URL=https://preview-chat-<chat_id>.space-z.ai')
    sys.exit(1)

if not BRIDGE_TOKEN:
    print("❌ NEXUS_BRIDGE_TOKEN غير محدد!")
    print("   اضبطه في .env أو كمتغير بيئة:")
    print('   NEXUS_BRIDGE_TOKEN=nxb-xxxxxxxxxxxxxxxx')
    sys.exit(1)

# ── إعدادات اختيارية مع قيم افتراضية ──

# الرموز: صيغة "LOGICAL:broker,LOGICAL2:broker2" أو "XAUUSD,BTCUSD"
# إن لم يُذكر الوسيط يُفترض أنه نفس الاسم المنطقي
_symbols_raw = _get_env("BRIDGE_SYMBOLS", "XAUUSD")
SYMBOL_MAP: dict[str, str] = {}
for entry in _symbols_raw.split(","):
    entry = entry.strip()
    if not entry:
        continue
    if ":" in entry:
        logical, broker = entry.split(":", 1)
        SYMBOL_MAP[logical.strip().upper()] = broker.strip()
    else:
        SYMBOL_MAP[entry.upper()] = entry.upper()

# تردد الإرسال (منخفض — آمن لحاوية Z.ai)
POLL_TICKS_SEC = _get_env_float("BRIDGE_POLL_TICKS_SEC", 5.0)
POLL_BARS_SEC = _get_env_float("BRIDGE_POLL_BARS_SEC", 60.0)
HEARTBEAT_SEC = _get_env_float("BRIDGE_HEARTBEAT_SEC", 60.0)
DECISION_POLL_SEC = _get_env_float("BRIDGE_DECISION_POLL_SEC", 120.0)
CALENDAR_POLL_SEC = _get_env_float("BRIDGE_CALENDAR_POLL_SEC", 300.0)
SEED_BARS = _get_env_int("BRIDGE_SEED_BARS", 1500)
POSITIONS_POLL_SEC = _get_env_float("BRIDGE_POSITIONS_POLL_SEC", 30.0)

# التوقيت
SERVER_TZ_OFFSET: Any = _get_env("BRIDGE_SERVER_TZ_OFFSET", "auto")
DEFAULT_TZ_OFFSET_HOURS = 2.0
SERVER_TIME_FILE = _get_env("BRIDGE_SERVER_TIME_FILE", "server_time.json")
TZ_RECHECK_SEC = 1800.0

# التنفيذ
EXECUTE = _get_env_bool("BRIDGE_EXECUTE", False)
MIN_CONVICTION = _get_env_int("BRIDGE_MIN_CONVICTION", 65)
LOT = _get_env_float("BRIDGE_LOT", 0.01)
SL_POINTS = _get_env_int("BRIDGE_SL_POINTS", 300)
TP_POINTS = _get_env_int("BRIDGE_TP_POINTS", 600)
ALLOW_REAL_ACCOUNT = _get_env_bool("BRIDGE_ALLOW_REAL_ACCOUNT", False)
EXECUTE_VIA_API = _get_env_bool("BRIDGE_EXECUTE_VIA_API", True)  # true = عبر الخادم

# التقويم
CALENDAR_FILE = _get_env("BRIDGE_CALENDAR_FILE", "calendar_dump.json")

# إعادة المحاولة
MAX_RETRIES = _get_env_int("BRIDGE_MAX_RETRIES", 2)
RETRY_BACKOFF_SEC = _get_env_float("BRIDGE_RETRY_BACKOFF_SEC", 1.5)

# التسجيل
LOG_LEVEL = _get_env("BRIDGE_LOG_LEVEL", "INFO").upper()
LOG_FILE = _get_env("BRIDGE_LOG_FILE", f"{BRIDGE_NAME.lower()}.log")

# ════════════════════════════════════════════════════════════════════════════
#  التهيئة
# ════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=f"%(asctime)s | %(levelname)-7s | [{BRIDGE_NAME}] | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
    ],
)
log = logging.getLogger(BRIDGE_NAME.lower())

# طباعة لافتة البداية
print("═" * 72)
print(f"  {BRIDGE_NAME} — Yemen Smart Bridge v3.0")
print("═" * 72)
print(f"  NEXUS_URL          = {NEXUS_URL}")
print(f"  NEXUS_BRIDGE_TOKEN = {BRIDGE_TOKEN[:15]}{'*' * max(0, len(BRIDGE_TOKEN) - 15)}")
print(f"  SYMBOLS            = {list(SYMBOL_MAP.keys())}")
print(f"  EXECUTE            = {EXECUTE} (via_api={EXECUTE_VIA_API})")
print(f"  ALLOW_REAL_ACCOUNT = {ALLOW_REAL_ACCOUNT}")
if EXECUTE:
    print(f"  LOT={LOT}  SL={SL_POINTS}pts  TP={TP_POINTS}pts  MIN_CONVICTION={MIN_CONVICTION}")
print(f"  POLL: tick={POLL_TICKS_SEC}s  bar={POLL_BARS_SEC}s  hb={HEARTBEAT_SEC}s  "
      f"decision={DECISION_POLL_SEC}s  calendar={CALENDAR_POLL_SEC}s  positions={POSITIONS_POLL_SEC}s")
print(f"  TZ_OFFSET          = {SERVER_TZ_OFFSET}")
if not _HAS_DOTENV:
    print("  ⚠️  python-dotenv غير مثبت — استخدم 'pip install python-dotenv' لقراءة .env تلقائيًا")
print("═" * 72)
print()

SESSION = requests.Session()
SESSION.headers.update({
    "x-bridge-token": BRIDGE_TOKEN,
    "Content-Type": "application/json",
    "User-Agent": f"{BRIDGE_NAME}/3.0",
    "X-Bridge-Name": BRIDGE_NAME,
})

_state: dict[str, Any] = {
    "tz_offset_hours": DEFAULT_TZ_OFFSET_HOURS,
    "last_bar_ts": {},
    "seeded": set(),
    "last_tick": {},
    "last_decision_id": {},
    "calendar_mtime": 0.0,
    "mt5_ready": False,
    "consecutive_errors": 0,
}


# ════════════════════════════════════════════════════════════════════════════
#  أدوات HTTP — مع إعادة محاولة محدودة على timeouts العابرة
# ════════════════════════════════════════════════════════════════════════════

def _post(path: str, payload: dict, retries: int | None = None) -> dict | None:
    """POST مع إعادة محاولة محدودة (لا تتراكم الطلبات)."""
    attempts = retries if retries is not None else MAX_RETRIES
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            r = SESSION.post(f"{NEXUS_URL}{path}", json=payload, timeout=15)
            if r.status_code == 401:
                log.error("❌ التوكن مرفوض من الخادم — تحقق من NEXUS_BRIDGE_TOKEN")
                return None
            if r.status_code == 429:
                log.warning("⚠️  429 Too Many Requests — تخطى هذه الدورة")
                return None
            r.raise_for_status()
            _state["consecutive_errors"] = 0
            return r.json()
        except requests.Timeout as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(RETRY_BACKOFF_SEC * attempt)
                continue
            log.warning("POST %s timeout بعد %d محاولات: %s", path, attempts, exc)
            return None
        except requests.ConnectionError as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(RETRY_BACKOFF_SEC * attempt)
                continue
            log.warning("POST %s connection error: %s", path, exc)
            return None
        except requests.RequestException as exc:
            log.warning("POST %s فشل: %s", path, exc)
            return None
    return None


def _get(path: str, retries: int | None = None) -> dict | None:
    """GET مع إعادة محاولة محدودة."""
    attempts = retries if retries is not None else MAX_RETRIES
    for attempt in range(1, attempts + 1):
        try:
            r = SESSION.get(f"{NEXUS_URL}{path}", timeout=15)
            if r.status_code == 401:
                log.error("❌ التوكن مرفوض من الخادم")
                return None
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                log.warning("⚠️  429 Too Many Requests — تخطى")
                return None
            r.raise_for_status()
            _state["consecutive_errors"] = 0
            return r.json()
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt < attempts:
                time.sleep(RETRY_BACKOFF_SEC * attempt)
                continue
            log.warning("GET %s فشل بعد %d محاولات: %s", path, attempts, exc)
            return None
        except requests.RequestException as exc:
            log.warning("GET %s فشل: %s", path, exc)
            return None
    return None


# ════════════════════════════════════════════════════════════════════════════
#  أدوات التوقيت
# ════════════════════════════════════════════════════════════════════════════

def _server_to_utc(epoch_seconds: int) -> str:
    """تحويل توقيت سيرفر الوسيط إلى UTC ISO."""
    dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc) - timedelta(
        hours=_state.get("tz_offset_hours", DEFAULT_TZ_OFFSET_HOURS)
    )
    return dt.isoformat()


def _read_ea_offset_hours() -> float | None:
    """الفارق الدقيق من NexusTimeEA."""
    try:
        paths = [os.path.abspath(SERVER_TIME_FILE)]
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            paths.append(os.path.join(
                appdata, "MetaQuotes", "Terminal", "Common", "Files", SERVER_TIME_FILE))
        for p in paths:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return float(data.get("offset_hours", 0))
    except Exception:
        pass
    return None


def resolve_tz_offset() -> float:
    """قياس/قراءة فارق توقيت السيرفر عن UTC."""
    if os.path.exists(SERVER_TIME_FILE):
        ea_off = _read_ea_offset_hours()
        if ea_off is not None:
            _state["tz_offset_hours"] = ea_off
            return ea_off

    if SERVER_TZ_OFFSET != "auto":
        try:
            val = float(SERVER_TZ_OFFSET)
            _state["tz_offset_hours"] = val
            return val
        except ValueError:
            pass

    # قياس تلقائي من أحدث tick
    for logical, broker in SYMBOL_MAP.items():
        info = mt5.symbol_info_tick(broker)
        if info and info.time:
            server_time = datetime.fromtimestamp(info.time, tz=timezone.utc)
            utc_now = datetime.now(timezone.utc)
            offset = round((server_time - utc_now).total_seconds() / 3600)
            _state["tz_offset_hours"] = float(offset)
            log.info("🕒 فارق التوقيت المقاس من أحدث tick (%s): +%s ساعة", logical, offset)
            return float(offset)

    return DEFAULT_TZ_OFFSET_HOURS


# ════════════════════════════════════════════════════════════════════════════
#  أدوات MT5 — معالجة numpy.void من copy_rates_from_pos (numpy 2.x)
# ════════════════════════════════════════════════════════════════════════════
# ملاحظة: في numpy 2.x، صفوف copy_rates_from_pos من نوع numpy.void
# لا تدعم الوصول بالخاصية (b.time) بل فقط بالعنصر (b["time"]).
# لذا نستخدم الوصول بالعنصر في كل مكان لضمان التوافق مع numpy 1.x و 2.x.

def init_mt5() -> bool:
    """تهيئة الاتصال بـ MT5."""
    if not mt5.initialize():
        log.error("❌ فشل initialize() — تأكد أن MT5 مفتوح ومُسجَّل دخول")
        return False

    acc = mt5.account_info()
    if not acc:
        log.error("❌ لا يوجد حساب — سجّل دخولك في MT5")
        mt5.shutdown()
        return False

    is_demo = acc.trade_mode == 0  # 0 = demo
    if not is_demo and not ALLOW_REAL_ACCOUNT:
        log.error("❌ حساب حقيقي — فعّل BRIDGE_ALLOW_REAL_ACCOUNT=true للمتابعة")
        mt5.shutdown()
        return False

    log.info("✅ متصل: حساب %s | %s | %s | رصيد %.2f %s",
             acc.login, acc.server, "DEMO ✅" if is_demo else "REAL ⚠️",
             acc.balance, acc.currency)

    term = mt5.terminal_info()
    if term:
        log.info("✅ إصدار الترمينال: %s | trade_allowed=%s",
                 term.build, term.trade_allowed)

    for logical, broker in SYMBOL_MAP.items():
        info = mt5.symbol_info(broker)
        if not info:
            log.warning("⚠️  الرمز %s غير موجود في Market Watch — حاول تفعيله يدويًا", broker)
            continue
        if not info.visible:
            mt5.symbol_select(broker, True)
        log.info("📌 %s → %s (digits=%d, point=%s, spread=%d pts)",
                 logical, broker, info.digits, info.point, info.spread)

    _state["mt5_ready"] = True
    return True


def reinit_mt5_if_needed() -> bool:
    """إعادة تهيئة MT5 إذا انقطع الاتصال."""
    if _state.get("mt5_ready"):
        # تحقق سريع
        try:
            if mt5.account_info() is not None:
                return True
        except Exception:
            pass
        log.warning("⚠️  انقطع اتصال MT5 — محاولة إعادة التهيئة...")
        try:
            mt5.shutdown()
        except Exception:
            pass
        _state["mt5_ready"] = False

    return init_mt5()


def read_tick(logical: str, broker: str) -> dict | None:
    """قراءة tick من MT5."""
    info = mt5.symbol_info_tick(broker)
    if not info:
        return None

    last = _state["last_tick"].get(logical)
    if last and last[0] == info.time and last[1] == info.bid and last[2] == info.ask:
        return None

    _state["last_tick"][logical] = (info.time, info.bid, info.ask)
    return {
        "symbol": logical,
        "bid": float(info.bid),
        "ask": float(info.ask),
        "last": float(info.last) if info.last > 0 else float(info.bid),
        "volume": int(info.volume) if hasattr(info, "volume") else 0,
        "timestamp": _server_to_utc(info.time),
    }


def read_bar(logical: str, broker: str, timeframe=mt5.TIMEFRAME_M5) -> dict | None:
    """قراءة شمعة M5 — يستخدم b["time"] (متوافق مع numpy 2.x)."""
    bars = mt5.copy_rates_from_pos(broker, timeframe, 0, 2)
    if bars is None or len(bars) < 1:
        return None

    last = bars[-1]
    last_time = int(last["time"])
    if _state["last_bar_ts"].get(logical) == last_time:
        return None

    _state["last_bar_ts"][logical] = last_time
    return {
        "symbol": logical,
        "timeframe": "M5",
        "bars": [{
            "time": _server_to_utc(last_time),
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
            "volume": int(last["tick_volume"]),
            "real_volume": int(last.get("real_volume", 0)) if hasattr(last, "__getitem__") else 0,
        }],
    }


def seed_history(logical: str, broker: str) -> None:
    """بذر تاريخ الشموع عند أول اتصال."""
    if logical in _state["seeded"]:
        return
    bars = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_M5, 0, SEED_BARS)
    if bars is None or len(bars) == 0:
        return

    payload_bars = []
    for b in bars:
        payload_bars.append({
            "time": _server_to_utc(int(b["time"])),
            "open": float(b["open"]),
            "high": float(b["high"]),
            "low": float(b["low"]),
            "close": float(b["close"]),
            "volume": int(b["tick_volume"]),
            "real_volume": int(b["real_volume"]) if "real_volume" in b.dtype.names else 0,
        })

    resp = _post("/api/v2/bridge/bars", {
        "symbol": logical,
        "timeframe": "M5",
        "bars": payload_bars,
    })
    if resp:
        log.info("🌱 بذر %d شمعة لـ %s", len(payload_bars), logical)
        _state["seeded"].add(logical)
        _state["last_bar_ts"][logical] = int(bars[-1]["time"])


def read_positions() -> list[dict]:
    """قراءة المراكز المفتوحة من MT5."""
    positions = mt5.positions_get() or []
    out = []
    for p in positions:
        out.append({
            "ticket": int(p.ticket),
            "symbol": str(p.symbol),
            "type": "BUY" if p.type == 0 else "SELL",
            "volume": float(p.volume),
            "open_price": float(p.price_open),
            "current_price": float(p.price_current),
            "sl": float(p.sl) if p.sl else None,
            "tp": float(p.tp) if p.tp else None,
            "profit": float(p.profit),
            "swap": float(p.swap),
            "open_time": _server_to_utc(int(p.time)),
            "comment": str(p.comment) if p.comment else "",
            "magic": int(p.magic),
        })
    return out


# ════════════════════════════════════════════════════════════════════════════
#  أدوات الإرسال — كل دالة ترسل طلب HTTP واحد فقط
# ════════════════════════════════════════════════════════════════════════════

def send_heartbeat() -> bool:
    """إرسال نبضة الحالة إلى الخادم."""
    acc = mt5.account_info()
    if not acc:
        return False

    term = mt5.terminal_info()
    payload = {
        "bridge_name": BRIDGE_NAME,
        "account": {
            "login": acc.login,
            "server": acc.server,
            "mode": "DEMO" if acc.trade_mode == 0 else "REAL",
            "balance": float(acc.balance),
            "currency": acc.currency,
            "leverage": int(acc.leverage),
            "equity": float(acc.equity),
            "margin": float(acc.margin),
            "free_margin": float(acc.margin_free),
            "margin_level": float(acc.margin_level) if acc.margin_level else None,
        },
        "terminal": {
            "build": term.build if term else None,
            "trade_allowed": bool(term.trade_allowed) if term else False,
            "connected": bool(term.connected) if term else False,
            "ping_ms": int(term.ping) if term and hasattr(term, "ping") else None,
        },
        "symbols": list(SYMBOL_MAP.keys()),
        "mode": "data-only" if not EXECUTE else "execute",
        "tz_offset_hours": _state.get("tz_offset_hours"),
        "broker_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    resp = _post("/api/v2/bridge/heartbeat", payload)
    return bool(resp)


def send_tick(logical: str, broker: str) -> bool:
    """إرسال tick واحد إلى الخادم."""
    tick = read_tick(logical, broker)
    if not tick:
        return False
    resp = _post("/api/v2/bridge/ticks", {"ticks": [tick]})
    if resp:
        log.debug("📡 tick %s: bid=%.2f ask=%.2f", logical, tick["bid"], tick["ask"])
        return True
    return False


def send_bar_if_new(logical: str, broker: str) -> bool:
    """إرسال شمعة M5 جديدة (إن وُجدت)."""
    bar = read_bar(logical, broker)
    if not bar:
        return False
    resp = _post("/api/v2/bridge/bars", bar)
    if resp:
        log.info("📊 شمعة جديدة %s: close=%.2f vol=%d",
                 logical, bar["bars"][0]["close"], bar["bars"][0]["volume"])
        return True
    return False


def send_positions() -> bool:
    """إرسال المراكز المفتوحة إلى الخادم (لعرضها في اللوحة)."""
    positions = read_positions()
    # أرسل حتى لو كانت فارغة — الخادم يحتاج لمعرفة أن لا مراكز
    resp = _post("/api/v2/bridge/positions", {"positions": positions})
    if resp:
        if positions:
            log.debug("📍 %d مركز مفتوح", len(positions))
        return True
    return False


def poll_decision(logical: str) -> None:
    """فحص قرار الوكلاء وتنفيذه إن لزم."""
    resp = _get(f"/api/agents/decision/{logical}")
    if not resp:
        return

    cycle_id = resp.get("cycle_id") or resp.get("id")
    last_seen = _state["last_decision_id"].get(logical)
    if cycle_id and cycle_id != last_seen:
        _state["last_decision_id"][logical] = cycle_id
        verdict = resp.get("verdict", "?")
        conviction = int(resp.get("conviction", 0) or 0)
        log.info("🤖 قرار جديد [%s]: %s (قناعة=%s%%)", logical, verdict, conviction)

        if EXECUTE and verdict in ("BUY", "SELL"):
            if conviction >= MIN_CONVICTION:
                if EXECUTE_VIA_API:
                    execute_via_api(logical, verdict, conviction, resp)
                else:
                    execute_decision_local(logical, verdict, conviction)
            else:
                log.info("⏸️  قناعة %d%% < %d — لم يُنفذ", conviction, MIN_CONVICTION)


def execute_via_api(logical: str, verdict: str, conviction: int, decision: dict) -> None:
    """تنفيذ القرار عبر API الخادم (الخادم بدوره يطلب من الجسر التنفيذ المحلي)."""
    payload = {
        "symbol": logical,
        "verdict": verdict,
        "conviction": conviction,
        "lot": LOT,
        "sl_points": SL_POINTS,
        "tp_points": TP_POINTS,
        "decision_id": decision.get("cycle_id") or decision.get("id"),
        "source": "bridge_auto",
    }
    resp = _post("/api/v2/bridge/execute", payload)
    if resp:
        log.info("✅ طلب التنفيذ أُرسل للخادم: %s", resp)
    else:
        log.error("❌ فشل إرسال طلب التنفيذ للخادم")


def execute_decision_local(logical: str, verdict: str, conviction: int) -> None:
    """تنفيذ قرار تداول في MT5 محليًا (الوضع التقليدي)."""
    if not ALLOW_REAL_ACCOUNT:
        log.warning("⚠️  التنفيذ المحلي معطّل — BRIDGE_ALLOW_REAL_ACCOUNT=false")
        return
    broker = SYMBOL_MAP.get(logical)
    if not broker:
        return

    log.info("⚡ تنفيذ محلي %s %s lot=%s SL=%d TP=%d",
             verdict, logical, LOT, SL_POINTS, TP_POINTS)

    tick = mt5.symbol_info_tick(broker)
    if not tick:
        return
    price = tick.ask if verdict == "BUY" else tick.bid
    info = mt5.symbol_info(broker)
    if not info:
        return

    point = info.point
    sl = price - SL_POINTS * point if verdict == "BUY" else price + SL_POINTS * point
    tp = price + TP_POINTS * point if verdict == "BUY" else price - TP_POINTS * point

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": broker,
        "volume": float(LOT),
        "type": mt5.ORDER_TYPE_BUY if verdict == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 20241027,
        "comment": f"nexus-{conviction}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("✅ تم التنفيذ: ticket=%s", result.order)
    else:
        log.error("❌ فشل التنفيذ: %s", result.comment if result else "no result")


def send_calendar_if_changed() -> None:
    """إرسال التقويم الاقتصادي إن تغيّر ملفه."""
    paths = [os.path.abspath(CALENDAR_FILE)]
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        paths.append(os.path.join(
            appdata, "MetaQuotes", "Terminal", "Common", "Files", CALENDAR_FILE))

    calendar_path = None
    for p in paths:
        if os.path.exists(p):
            calendar_path = p
            break

    if not calendar_path:
        return

    mtime = os.path.getmtime(calendar_path)
    if mtime == _state["calendar_mtime"]:
        return

    try:
        with open(calendar_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        events = data.get("events", [])
        if not events:
            return

        payload = {"events": events}
        resp = _post("/api/v2/bridge/calendar", payload)
        if resp:
            _state["calendar_mtime"] = mtime
            log.info("📅 أرسل %d حدث تقويم", len(events))
    except Exception as exc:
        log.warning("⚠️  فشل قراءة التقويم: %s", exc)


# ════════════════════════════════════════════════════════════════════════════
#  الحلقة الرئيسية — Single-Threaded Sequential
# ════════════════════════════════════════════════════════════════════════════

def main_loop():
    """حلقة واحدة متسلسلة — طلب HTTP واحد فقط في كل لحظة."""
    log.info("═══ %s — Yemen Smart Bridge v3.0 ═══", BRIDGE_NAME)
    log.info("الخادم: %s", NEXUS_URL)
    log.info("الوضع: %s", "بيانات + تنفيذ ⚡" if EXECUTE else "بيانات فقط 📡")
    log.info("التردد: tick=%.0fs | bar=%.0fs | hb=%.0fs | decision=%.0fs | pos=%.0fs",
             POLL_TICKS_SEC, POLL_BARS_SEC, HEARTBEAT_SEC, DECISION_POLL_SEC, POSITIONS_POLL_SEC)

    if not init_mt5():
        sys.exit(1)

    resolve_tz_offset()

    # بذر التاريخ لكل رمز
    for logical, broker in SYMBOL_MAP.items():
        seed_history(logical, broker)

    # نبضة أولية
    send_heartbeat()
    send_positions()

    # مؤشرات الوقت الأخيرة لكل حدث
    last_heartbeat = time.time()
    last_bar_check = time.time()
    last_decision = 0.0
    last_calendar = 0.0
    last_positions = time.time()
    last_tz_recheck = time.time()

    log.info("🚀 بدء الحلقة الرئيسية (single-threaded)")

    try:
        while True:
            now = time.time()

            # تحقق من اتصال MT5 (سريع، كل دورة)
            if not reinit_mt5_if_needed():
                log.error("❌ تعذّر إعادة اتصال MT5 — انتظار 30 ثانية")
                time.sleep(30)
                continue

            # 1) tick — كل POLL_TICKS_SEC
            for logical, broker in SYMBOL_MAP.items():
                try:
                    send_tick(logical, broker)
                except Exception as exc:
                    log.warning("tick فشل: %s", exc)

            # 2) heartbeat — كل HEARTBEAT_SEC
            if now - last_heartbeat >= HEARTBEAT_SEC:
                try:
                    send_heartbeat()
                    last_heartbeat = now
                except Exception as exc:
                    log.warning("heartbeat فشل: %s", exc)

            # 3) bar check — كل POLL_BARS_SEC
            if now - last_bar_check >= POLL_BARS_SEC:
                try:
                    for logical, broker in SYMBOL_MAP.items():
                        send_bar_if_new(logical, broker)
                except Exception as exc:
                    log.warning("bar check فشل: %s", exc)
                last_bar_check = now

            # 4) positions — كل POSITIONS_POLL_SEC
            if now - last_positions >= POSITIONS_POLL_SEC:
                try:
                    send_positions()
                except Exception as exc:
                    log.warning("positions فشل: %s", exc)
                last_positions = now

            # 5) decision poll — كل DECISION_POLL_SEC
            if now - last_decision >= DECISION_POLL_SEC:
                try:
                    for logical in SYMBOL_MAP:
                        poll_decision(logical)
                except Exception as exc:
                    log.warning("decision poll فشل: %s", exc)
                last_decision = now

            # 6) calendar — كل CALENDAR_POLL_SEC
            if now - last_calendar >= CALENDAR_POLL_SEC:
                try:
                    send_calendar_if_changed()
                except Exception as exc:
                    log.warning("calendar فشل: %s", exc)
                last_calendar = now

            # 7) إعادة قياس فارق التوقيت كل TZ_RECHECK_SEC
            if now - last_tz_recheck >= TZ_RECHECK_SEC:
                try:
                    resolve_tz_offset()
                except Exception:
                    pass
                last_tz_recheck = now

            # انتظار قصير قبل الدورة التالية
            time.sleep(POLL_TICKS_SEC)

    except KeyboardInterrupt:
        log.info("⏹️  إيقاف الجسر...")
    finally:
        try:
            mt5.shutdown()
        except Exception:
            pass
        log.info("تم الإيقاف.")


if __name__ == "__main__":
    main_loop()
