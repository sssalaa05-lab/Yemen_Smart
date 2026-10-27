"""بذر تاريخي لسجل الميزات (nexus:features:history:XAUUSD) من شموع OneRoyal المبذورة.

المشكلة: خدمة الميزات تحسب لكل حدث بث حي فقط، والبذر الكبير (1500 شمعة) ينشر
حدثًا واحدًا لآخر شمعة → السجل التاريخي يبقى فارغًا والتدريب ينتظر ~42 ساعة.

الحل: إعادة حساب الميزات لكل شمعة تاريخية بنفس دوال nexus_features نفسها
(استيراد مباشر — صفر إعادة تنفيذ للمنطق) بنافذة 300 شمعة منزلقة (نفس
OHLCV_BAR_COUNT في nexus_data) ثم كتابة السجلات بنفس مخطط nexus_ml بالضبط:
{"features": numeric-only, "label": close>prev_close, "ohlcv": {...}, "timestamp": bar_ts}

ملاحظات التوافق:
- indicators ش causal → قيمتها عند الصف الأخير لا تتأثر بطول النافذة ≥ lookback.
- features["session"] تأتي من وقت المعالجة (كما في الحي تمامًا) → ثابتة في البذر
  ولا تضر (نماذج ML تتجاهل الميزة الثابتة)، وتتنوع لاحقًا مع الشموع الحية.
- cross_asset م skipped (كاشها فارغ حاليًا — نفس سلوك المسار الحي الآن).
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone

NEXUS_ROOT = "/home/z/my-project/nexus-system/Nexus-Trading-System-MT5-main"
sys.path.insert(0, NEXUS_ROOT)

import redis  # noqa: E402

from services.nexus_features.main import (  # noqa: E402
    _compute_tick_imbalance,
    _extract_features,
    _safe_float,
)
from services.nexus_features.indicators import calculate_all  # noqa: E402
from services.nexus_features.session_tagger import get_current_session, tag_dataframe  # noqa: E402
from services.nexus_features.trend_analyzer import calculate_trend_score, detect_trend  # noqa: E402
from services.nexus_features.volatility import (  # noqa: E402
    calculate_atr_normalized,
    detect_regime,
)

import pandas as pd  # noqa: E402

WINDOW = 300          # OHLCV_BAR_COUNT في nexus_data
MIN_BARS = 50         # حد الخدمة الحي
HISTORY_KEY = "nexus:features:history:XAUUSD"

# ── 1) جلب الشموع (تصاعديًا) ────────────────────────────────────────────────
url = "http://localhost:9001/api/data/ohlcv/XAUUSD/M5?limit=3000"
with urllib.request.urlopen(url, timeout=30) as resp:
    bars = json.loads(resp.read().decode())
bars.sort(key=lambda b: b["timestamp"])
print(f"bars fetched: {len(bars)}  ({bars[0]['timestamp']} → {bars[-1]['timestamp']})")

# ── 2) تنظيف السجلات الحية (أختام وقت-معالجة دقيقة عشرية لا تقارن بأختام الشموع) ─
# نسخها المبذورة أدناه تغطي نفس الشموع بأختام بار-زمن صحيحة (للمشي الأمامي حسب الشهر).
r = redis.Redis(host="localhost", port=6379, decode_responses=True)
all_rec = r.lrange(HISTORY_KEY, 0, -1)
live_idx = [i for i, raw in enumerate(all_rec)
            if "." in (json.loads(raw).get("timestamp") or "")]
if live_idx:
    keep = [raw for i, raw in enumerate(all_rec) if i not in set(live_idx)]
    r.delete(HISTORY_KEY)
    if keep:
        r.rpush(HISTORY_KEY, *keep)
    print(f"removed {len(live_idx)} live records (processing-time stamps), kept {len(keep)}")

# ── 3) الحساب التاريخي ──────────────────────────────────────────────────────
records = []
for i in range(WINDOW, len(bars)):
    bar_ts = bars[i]["timestamp"]
    window = bars[i - WINDOW + 1 : i + 1]
    df = pd.DataFrame(window)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    if len(df) < MIN_BARS:
        continue

    df = calculate_all(df)
    df = tag_dataframe(df)
    features = _extract_features(df)

    trend = detect_trend(df)
    features["trend_direction"] = trend.direction.value
    features["trend_strength"] = trend.strength
    features["trend_score"] = calculate_trend_score(df)

    atr_n = calculate_atr_normalized(df)
    regime = detect_regime(df)
    features["atr_normalized"] = _safe_float(atr_n.iloc[-1])
    features["vol_regime"] = str(regime.iloc[-1])

    session_info = get_current_session()
    features["session"] = session_info.name
    features["session_overlap"] = session_info.is_overlap

    features["close"] = _safe_float(df["close"].iloc[-1])
    features["atr_14"] = _safe_float(df["atr"].iloc[-1]) if "atr" in df.columns else 0.0
    features["tick_imbalance_20"] = _compute_tick_imbalance(df, window=20)
    features["tick_imbalance_5"] = _compute_tick_imbalance(df, window=5)

    numeric = {k: v for k, v in features.items() if isinstance(v, (int, float))}
    close_i = float(bars[i]["close"])
    close_prev = float(bars[i - 1]["close"])
    label = 1 if close_i > close_prev else 0

    records.append(json.dumps({
        "features": numeric,
        "label": label,
        "ohlcv": {
            "open": float(bars[i]["open"]),
            "high": float(bars[i]["high"]),
            "low": float(bars[i]["low"]),
            "close": close_i,
            "volume": float(bars[i].get("volume", 0)),
        },
        "timestamp": bar_ts,
    }))

print(f"records built: {len(records)}")
if records:
    first = json.loads(records[0])
    last = json.loads(records[-1])
    print("first:", first["timestamp"], "label", first["label"], "| n_feats", len(first["features"]))
    print("last :", last["timestamp"], "label", last["label"])

    # ── 4) الكتابة على دفعات ────────────────────────────────────────────────
    pipe = r.pipeline()
    for j, rec in enumerate(records):
        pipe.rpush(HISTORY_KEY, rec)
        if (j + 1) % 300 == 0:
            pipe.execute()
            print(f"  pushed {j + 1}/{len(records)}")
    pipe.execute()

print("history length now:", r.llen(HISTORY_KEY))
print("DONE")
