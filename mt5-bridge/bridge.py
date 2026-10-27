# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║   NEXUS MT5 BRIDGE v2.0 — Single-Threaded Sequential                    ║
║   حل جذري لمشكلة 429 Too Many Requests                                   ║
║                                                                          ║
║   التصميم الجديد:                                                        ║
║   - حلقة واحدة متسلسلة (لا تزامن)                                       ║
║   - طلب HTTP واحد فقط في كل لحظة                                        ║
║   - تردد منخفض (آمن لحاوية Z.ai)                                        ║
║   - لا إعادة محاولة (تتجنب تراكم الطلبات)                               ║
║   - معالجة numpy.void من copy_rates_from_pos (numpy 2.x)                ║
║                                                                          ║
║   الإعدادات تُقرأ من متغيرات البيئة:                                     ║
║   NEXUS_URL          (إلزامي) رابط النظام                               ║
║   NEXUS_BRIDGE_TOKEN (إلزامي) توكن الجسر                                ║
║                                                                          ║
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
#  الإعدادات — تُقرأ من متغيرات البيئة
# ════════════════════════════════════════════════════════════════════════════

NEXUS_URL = os.environ.get("NEXUS_URL", "").rstrip("/")
BRIDGE_TOKEN = os.environ.get("NEXUS_BRIDGE_TOKEN", "")

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

print("═" * 70)
print("  NEXUS MT5 BRIDGE v2.0 — Single-Threaded Sequential")
print("═" * 70)
print(f"  NEXUS_URL          = {NEXUS_URL}")
print(f"  NEXUS_BRIDGE_TOKEN = {BRIDGE_TOKEN[:15]}{'*' * max(0, len(BRIDGE_TOKEN) - 15)}")
print("═" * 70)
print()

# ── تردد الإرسال (منخفض — آمن لحاوية Z.ai) ──
POLL_TICKS_SEC = 5.0       # tick كل 5 ثوانٍ
POLL_BARS_SEC = 60.0       # فحص شمعة جديدة كل دقيقة
HEARTBEAT_SEC = 60.0       # نبضة كل دقيقة
DECISION_POLL_SEC = 120.0  # قرار كل دقيقتين
CALENDAR_POLL_SEC = 300.0  # تقويم كل 5 دقائق
SEED_BARS = 1500

# ── إعدادات إضافية ──
SYMBOL_MAP: dict[str, str] = {
    "XAUUSD": "XAUUSD",
    # "BTCUSD": "BTCUSD",
    # "EURUSD": "EURUSD",
}
SERVER_TZ_OFFSET_HOURS: Any = "auto"
DEFAULT_TZ_OFFSET_HOURS = 2.0
SERVER_TIME_FILE = "server_time.json"
TZ_RECHECK_SEC = 1800.0

EXECUTE = False           # True = ينفذ قرارات الوكلاء في MT5 فعلياً
MIN_CONVICTION = 65       # لا ينفذ إلا إذا كانت قناعة القرار >= هذا الرقم
LOT = 0.01                # حجم العقد
SL_POINTS = 300           # وقف الخسارة بالنقاط (0 = بدون) — للذهب 300 نقطة ≈ 3$
TP_POINTS = 600           # الهدف بالنقاط (0 = بدون)
ALLOW_REAL_ACCOUNT = False  # ⚠️ اجعلها True فقط إذا كنت تريد التنفيذ على حساب حقيقي

CALENDAR_FILE = "calendar_dump.json"

# ════════════════════════════════════════════════════════════════════════════
#  التهيئة
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
    "tz_offset_hours": DEFAULT_TZ_OFFSET_HOURS,
    "last_bar_ts": {},
    "seeded": set(),
    "last_tick": {},
    "last_decision_id": None,
    "last_tick_ts": None,
    "calendar_mtime": 0.0,
}


# ════════════════════════════════════════════════════════════════════════════
#  أدوات HTTP — لا إعادة محاولة (مفتاح حل 429)
# ════════════════════════════════════════════════════════════════════════════

def _post(path: str, payload: dict) -> dict | None:
    """POST طلب واحد — لا إعادة محاولة لتجنب تراكم الطلبات."""
    try:
        r = SESSION.post(f"{NEXUS_URL}{path}", json=payload, timeout=15)
        if r.status_code == 401:
            log.error("❌ التوكن مرفوض من الخادم — تحقق من NEXUS_BRIDGE_TOKEN")
            return None
        if r.status_code == 429:
            log.warning("⚠️  429 Too Many Requests — تخطى هذه الدورة")
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        log.warning("POST %s فشل: %s", path, exc)
        return None


def _get(path: str) -> dict | None:
    """GET طلب واحد — لا إعادة محاولة."""
    try:
        r = SESSION.get(f"{NEXUS_URL}{path}", timeout=15)
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            log.warning("⚠️  429 Too Many Requests — تخطى")
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        log.warning("GET %s فشل: %s", path, exc)
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

    if SERVER_TZ_OFFSET_HOURS != "auto":
        _state["tz_offset_hours"] = float(SERVER_TZ_OFFSET_HOURS)
        return float(SERVER_TZ_OFFSET_HOURS)

    info = mt5.symbol_info_tick("XAUUSD")
    if info and info.time:
        server_time = datetime.fromtimestamp(info.time, tz=timezone.utc)
        utc_now = datetime.now(timezone.utc)
        offset = round((server_time - utc_now).total_seconds() / 3600)
        _state["tz_offset_hours"] = float(offset)
        log.info("🕒 فارق التوقيت المقاس من أحدث tick: +%s ساعة", offset)
        return float(offset)

    return DEFAULT_TZ_OFFSET_HOURS


# ════════════════════════════════════════════════════════════════════════════
#  أدوات MT5 — معالجة numpy.void من copy_rates_from_pos (numpy 2.x)
# ════════════════════════════════════════════════════════════════════════════
# ملاحظة مهمة: في numpy 2.x، صفوف copy_rates_from_pos من نوع numpy.void
# لا تدعم الوصول بالخاصية (b.time) بل فقط بالعنصر (b["time"]).
# لذا نستخدم الوصول بالعنصر في كل مكان لضمان التوافق مع numpy 1.x و 2.x.

def init_mt5() -> bool:
    """تهيئة الاتصال بـ MT5."""
    if not mt5.initialize():
        log.error("❌ فشل initialize() — تأكد أن MT5 مفتوح")
        return False

    acc = mt5.account_info()
    if not acc:
        log.error("❌ لا يوجد حساب — سجّل دخولك في MT5")
        mt5.shutdown()
        return False

    is_demo = acc.trade_mode == 0  # 0 = demo
    if not is_demo and not ALLOW_REAL_ACCOUNT:
        log.error("❌ حساب حقيقي — فعّل ALLOW_REAL_ACCOUNT للمتابعة")
        mt5.shutdown()
        return False

    log.info("✅ متصل: حساب %s | %s | %s | رصيد %.2f %s",
             acc.login, acc.server, "DEMO ✅" if is_demo else "REAL ⚠️",
             acc.balance, acc.currency)

    term = mt5.terminal_info()
    if term:
        log.info("✅ إصدار الترمينال: %s", term.build)

    for logical, broker in SYMBOL_MAP.items():
        info = mt5.symbol_info(broker)
        if not info:
            log.warning("⚠️  الرمز %s غير موجود في Market Watch", broker)
            continue
        if not info.visible:
            mt5.symbol_select(broker, True)
        log.info("📌 %s → %s (digits=%d, point=%s)",
                 logical, broker, info.digits, info.point)

    return True


def read_tick(logical: str, broker: str) -> dict | None:
    """قراءة tick من MT5 — يستخدم info.time (TickInfo يدعم الخاصية)."""
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
        "timestamp": _server_to_utc(info.time),
    }


def read_bar(logical: str, broker: str, timeframe=mt5.TIMEFRAME_M5) -> dict | None:
    """قراءة شمعة M5 — يستخدم b["time"] (متوافق مع numpy 2.x)."""
    bars = mt5.copy_rates_from_pos(broker, timeframe, 0, 2)
    if bars is None or len(bars) < 1:
        return None

    last = bars[-1]
    # ⚠️ استخدام الوصول بالعنصر (وليس بالخاصية) لتوافق numpy 2.x
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
        # ⚠️ استخدام الوصول بالعنصر (وليس بالخاصية) لتوافق numpy 2.x
        payload_bars.append({
            "time": _server_to_utc(int(b["time"])),
            "open": float(b["open"]),
            "high": float(b["high"]),
            "low": float(b["low"]),
            "close": float(b["close"]),
            "volume": int(b["tick_volume"]),
        })

    resp = _post("/api/v2/bridge/bars", {
        "symbol": logical,
        "timeframe": "M5",
        "bars": payload_bars,
    })
    if resp:
        log.info("🌱 بذر %d شمعة لـ %s", len(payload_bars), logical)
        _state["seeded"].add(logical)
        # حفظ آخر شمعة لتفادي إعادة إرسالها
        _state["last_bar_ts"][logical] = int(bars[-1]["time"])


# ════════════════════════════════════════════════════════════════════════════
#  أدوات الإرسال — كل دالة ترسل طلب HTTP واحد فقط
# ════════════════════════════════════════════════════════════════════════════

def send_heartbeat() -> bool:
    """إرسال نبضة الحالة إلى الخادم."""
    acc = mt5.account_info()
    if not acc:
        return False

    payload = {
        "account": {
            "login": acc.login,
            "server": acc.server,
            "mode": "DEMO" if acc.trade_mode == 0 else "REAL",
            "balance": float(acc.balance),
            "currency": acc.currency,
            "leverage": int(acc.leverage),
            "equity": float(acc.equity),
        },
        "terminal": f"MT5 build {mt5.terminal_info().build if mt5.terminal_info() else '?'}",
        "symbols": list(SYMBOL_MAP.keys()),
        "mode": "data-only" if not EXECUTE else "execute",
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
    return bool(resp)


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


def poll_decision(logical: str) -> None:
    """فحص قرار الوكلاء وتنفيذه إن لزم."""
    resp = _get(f"/api/agents/decision/{logical}")
    if not resp:
        return

    cycle_id = resp.get("cycle_id")
    if cycle_id and cycle_id != _state.get("last_decision_id"):
        _state["last_decision_id"] = cycle_id
        verdict = resp.get("verdict", "?")
        conviction = resp.get("conviction", 0)
        log.info("🤖 قرار جديد [%s]: %s (قناعة=%s)",
                 logical, verdict, conviction)

        if EXECUTE and verdict in ("BUY", "SELL"):
            if conviction >= MIN_CONVICTION:
                execute_decision(logical, verdict, conviction)


def execute_decision(logical: str, verdict: str, conviction: int) -> None:
    """تنفيذ قرار تداول في MT5 (يدويًا حتى الآن)."""
    if not ALLOW_REAL_ACCOUNT:
        return
    broker = SYMBOL_MAP.get(logical)
    if not broker:
        return

    log.info("⚡ تنفيذ %s %s lot=%s SL=%d TP=%d",
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
#  الحلقة الرئيسية — Single-Threaded Sequential (مفتاح حل 429)
# ════════════════════════════════════════════════════════════════════════════

def main_loop():
    """حلقة واحدة متسلسلة — طلب HTTP واحد فقط في كل لحظة."""
    log.info("═══ NEXUS MT5 BRIDGE ═══")
    log.info("الخادم: %s", NEXUS_URL)
    log.info("الوضع: %s", "بيانات + تنفيذ ⚡" if EXECUTE else "بيانات فقط 📡")
    log.info("التردد: tick=%.0fs | bar=%.0fs | heartbeat=%.0fs | decision=%.0fs",
             POLL_TICKS_SEC, POLL_BARS_SEC, HEARTBEAT_SEC, DECISION_POLL_SEC)

    if not init_mt5():
        sys.exit(1)

    resolve_tz_offset()

    # بذر التاريخ لكل رمز
    for logical, broker in SYMBOL_MAP.items():
        seed_history(logical, broker)

    # نبضة أولية
    send_heartbeat()

    # مؤشرات الوقت الأخيرة لكل حدث
    last_heartbeat = time.time()
    last_bar_check = time.time()
    last_decision = 0
    last_calendar = 0
    last_tz_recheck = time.time()

    log.info("🚀 بدء الحلقة الرئيسية (single-threaded)")

    try:
        while True:
            now = time.time()

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

            # 4) decision poll — كل DECISION_POLL_SEC
            if now - last_decision >= DECISION_POLL_SEC:
                try:
                    for logical in SYMBOL_MAP:
                        poll_decision(logical)
                except Exception as exc:
                    log.warning("decision poll فشل: %s", exc)
                last_decision = now

            # 5) calendar — كل CALENDAR_POLL_SEC
            if now - last_calendar >= CALENDAR_POLL_SEC:
                try:
                    send_calendar_if_changed()
                except Exception as exc:
                    log.warning("calendar فشل: %s", exc)
                last_calendar = now

            # 6) إعادة قياس فارق التوقيت كل TZ_RECHECK_SEC
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
        mt5.shutdown()
        log.info("تم الإيقاف.")


if __name__ == "__main__":
    main_loop()
