# دليل تشغيل جسر MT5 v3.0 — خطوة بخطوة

> **الاسم:** ZYSB (Yemen Smart Bridge) — v3.0  
> **الغرض من الاسم:** تمييز هذا الجسر عن أي جسور أخرى قد تكون مشغّلة على نفس جهاز Windows (مثلاً جسور مشاريع أخرى).  
> **التغييرات الرئيسية:** كل الإعدادات من `.env`، قراءة تلقائية لـ `.env`، تنفيذ عبر API، إرسال حالة المراكز، إعادة محاولة محدودة، إعادة اتصال تلقائية، اسم قابل للتخصيص `BRIDGE_NAME`.

## ما هذا؟

`bridge.py` برنامج صغير يعمل على جهازك (ويندوز) بجانب منصة MetaTrader 5،
ينقل **أسعار وسيطك الحقيقية اللحظية** إلى نظام Yemen Smart، ويمكنه (اختيارياً)
**تنفيذ قرارات الوكلاء** في MT5 تلقائياً. يُسمى الجسر **ZYSB** (Yemen Smart Bridge)
لتمييزه في السجلات وملفات الـ log عن أي جسور أخرى.

```
جهازك (ويندوز)                        الخادم (Z.ai)
┌──────────────────────┐              ┌─────────────────────────┐
│  MT5 Terminal        │              │  Yemen Smart            │
│     ↕ bridge.py  ────┼── HTTPS ─────┼→  /api/v2/bridge/*      │
│  (أسعار + تنفيذ)     │   توكن مشفر  │   → وكلاء → قرارات      │
└──────────────────────┘              └─────────────────────────┘
```

---

## الخطوة 1 — تجهيز جهازك (مرة واحدة)

1. ثبّت Python 3.10+ من python.org (خلال التثبيت علّم ✅ **Add Python to PATH**)
2. افتح CMD في مجلد `mt5-bridge/` واكتب:
   ```
   pip install -r requirements.txt
   ```
   هذا يثبّت: `MetaTrader5` + `requests` + `python-dotenv`
3. افتح منصة MT5 وسجّل دخولك (حساب **Demo** للبداية)
4. من القائمة: **Tools → Options → Expert Advisors →** فعّل ✅ **Allow algorithmic trading**

## الخطوة 2 — ضبط الإعدادات عبر `.env`

1. انسخ `.env.example` إلى `.env` في نفس مجلد `bridge.py`:
   ```cmd
   copy .env.example .env
   ```
2. افتح `.env` بـ Notepad وعدّل القيم الإلزامية:

| الإعداد | القيمة | ملاحظة |
|---------|--------|--------|
| `BRIDGE_NAME` | `ZYSB` (افتراضي) | اسم الجسر — يُميّزه في السجلات والـ banner. غيّره إن أردت اسمًا آخر |
| `NEXUS_URL` | `https://preview-chat-<chat_id>.space-z.ai` | رابط المعاينة للجلسة الحالية على Z.ai — يتغير مع كل جلسة |
| `NEXUS_BRIDGE_TOKEN` | `nxb-xxxxxxxxxxxxxxxx` | نفس `NEXUS_BRIDGE_TOKEN` في `.env` على الخادم |
| `BRIDGE_SYMBOLS` | `XAUUSD` أو `XAUUSD:GOLD,BTCUSD` | الرموز المتداولة. إن كان اسم الوسيط مختلفًا استخدم صيغة `LOGICAL:broker` |
| `BRIDGE_SERVER_TZ_OFFSET` | `auto` | يقيس فارق سيرفرك تلقائيًا — أو ضع رقمًا مثل `2.0` |
| `BRIDGE_EXECUTE` | `false` | **اتركها false أولًا** — الجسر يرسل البيانات فقط |

### صيغة `BRIDGE_SYMBOLS`

| القيمة | المعنى |
|---|---|
| `XAUUSD` | رمز واحد، الاسم المنطقي = اسم الوسيط |
| `XAUUSD,BTCUSD` | رمزان، كل اسم منطقي = اسم الوسيط |
| `XAUUSD:GOLD` | الاسم المنطقي `XAUUSD` لكن اسم الوسيط في MT5 هو `GOLD` |
| `XAUUSD:GOLD,BTCUSD:BTCUSDm` | خليط |

## الخطوة 3 — التشغيل

```
python bridge.py
```

ستشاهد:
```
══════════════════════════════════════════════════════════════════════════
  ZYSB — Yemen Smart Bridge v3.0
══════════════════════════════════════════════════════════════════════════
  NEXUS_URL          = https://preview-chat-abc-123.space-z.ai
  NEXUS_BRIDGE_TOKEN = nxb-X56n-2H8Tar...
  SYMBOLS            = ['XAUUSD']
  EXECUTE            = False (via_api=True)
  ALLOW_REAL_ACCOUNT = False
  POLL: tick=5s  bar=60s  hb=60s  decision=120s  calendar=300s  positions=30s
  TZ_OFFSET          = auto
══════════════════════════════════════════════════════════════════════════

20:30:01 | INFO    | [ZYSB] | ═══ ZYSB — Yemen Smart Bridge v3.0 ═══
20:30:01 | INFO    | [ZYSB] | ✅ متصل: حساب 12345 | broker-Demo | DEMO ✅ | رصيد 10000.00 USD
20:30:01 | INFO    | [ZYSB] | ✅ إصدار الترمينال: 4385 | trade_allowed=True
20:30:01 | INFO    | [ZYSB] | 📌 XAUUSD → XAUUSD (digits=2, point=0.01, spread=15 pts)
20:30:01 | INFO    | [ZYSB] | 🌱 بذر 1500 شمعة لـ XAUUSD
20:30:01 | INFO    | [ZYSB] | 📊 شمعة جديدة XAUUSD: close=2030.50 vol=135
20:30:01 | INFO    | 🚀 بدء الحلقة الرئيسية (single-threaded)
```

اتركه يعمل. لتوقفه: `Ctrl+C`.

## الخطوة 4 — التحقق من طرف الخادم

افتح لوحة Yemen Smart على نفس الـ URL:
- الشارت الحي سيبدأ بالتحرك مع **أسعار وسيطك** (أسرع وأدق من Yahoo)
- قسم **Positions** سيعرض المراكز المفتوحة في MT5 (إن وُجدت)
- قسم **Bridge Status** سيعرض: حالة الاتصال، آخر نبضة، حالة زر Algo Trading

---

## ما الذي يُرسله الجسر؟

| البيانات | التردد | الـ Endpoint |
|---|---|---|
| **Ticks** (bid/ask) | كل 5 ثوان | `POST /api/v2/bridge/ticks` |
| **Bars** M5 | كل دقيقة (فقط عند شمعة جديدة) | `POST /api/v2/bridge/bars` |
| **Heartbeat** (account + terminal) | كل 60 ثانية | `POST /api/v2/bridge/heartbeat` |
| **Positions** snapshot | كل 30 ثانية | `POST /api/v2/bridge/positions` |
| **Decision poll** | كل 120 ثانية | `GET /api/agents/decision/{symbol}` |
| **Calendar** (إن تغيّر الملف) | كل 5 دقائق | `POST /api/v2/bridge/calendar` |
| **Seed history** (1500 شمعة) | مرة واحدة عند البداية | `POST /api/v2/bridge/bars` |

## التوقيت — تلقائي بالكامل

كل الشموع والـ ticks من MT5 تحمل **توقيت سيرفر الوسيط**، ونظام Yemen Smart يحتاج UTC. الجسر يحل هذا وحده:

1. **وضع `"auto"` (الافتراضي):** عند أول نشاط سوق يقيس الجسر الفارق من أحدث tick، ويعيد الفحص كل 30 دقيقة.
2. **(اختياري) دقة 100% عبر EA رفيق `ZYSBTimeEA.mq5`** — يستخدم `TimeCurrent`/`TimeGMT` ويكتب الفارق في `zysb_server_time.json`.

ترتيب الأولوية: رقم ثابت في `BRIDGE_SERVER_TZ_OFFSET` > ملف EA الرفيق > قياس تلقائي > افتراضي 2.0.

## تفعيل التنفيذ الفعلي (لاحقًا — بعد الثقة)

1. جرّب وضع البيانات أولًا يومين على الأقل ولاحظ قرارات الوكلاء
2. عندما تقتنع: في `.env` ضع:
   ```
   BRIDGE_EXECUTE=true
   BRIDGE_EXECUTE_VIA_API=true   # موصى به — التنفيذ عبر API الخادم
   BRIDGE_LOT=0.01
   BRIDGE_SL_POINTS=300
   BRIDGE_TP_POINTS=600
   BRIDGE_MIN_CONVICTION=65
   ```
3. **حماية مدمجة**: لو كان حسابك REAL سيرفض الجسر التنفيذ ما لم تجعل `BRIDGE_ALLOW_REAL_ACCOUNT=true` عمدًا

### طريقتان للتنفيذ

| الطريقة | الإعداد | الوصف |
|---|---|---|
| عبر API (موصى به) | `BRIDGE_EXECUTE_VIA_API=true` | الجسر يرسل طلب تنفيذ للخادم عبر `/api/v2/bridge/execute`. الخادم يسجّله للأرشفة. التنفيذ الفعلي لا يزال على الجسر لكن الخادم يراقب كل تنفيذ. |
| مباشر (تقليدي) | `BRIDGE_EXECUTE_VIA_API=false` | الجسر يستدعي `mt5.order_send` مباشرة دون مرور الخادم. أسرع لكن بلا سجل مركزي. |

## أمان

- كل رسالة موقعة بـ `x-bridge-token` — الخادم يرفض أي طلب بدون التوكن (401)
- الجسر **يقرأ** الأسعار من MT5 ولا يعدل شيئًا في منصتك (إلا عند تفعيل `EXECUTE=true`)
- التنفيذ مقيّد: صفقة واحدة لكل رمز + حد أدنى للقناعة
- الـ token يُمرّر في header (وليس في URL) — لا يظهر في سجلات الخادم

## أعطال شائعة

| الرسالة | الحل |
|---------|------|
| `فشل initialize()` | افتح MT5 وسجّل الدخول أولًا |
| `الرمز XAUUSD غير موجود` | عدّل `BRIDGE_SYMBOLS` لاسم الوسيط الفعلي (مثل `XAUUSD:GOLD`) |
| `التوكن مرفوض (401)` | تأكد أن `NEXUS_BRIDGE_TOKEN` في `.env` يطابق الخادم |
| `POST فشل: Timeout` | تحقق من الإنترنت — الجسر يعيد المحاولة تلقائيًا (مرتان) |
| `429 Too Many Requests` | زِد قيم `BRIDGE_POLL_*_SEC` في `.env` |
| `trade_allowed=False` | فعّل زر Algo Trading في MT5 (Tools → Options → Expert Advisors) |
| `انقطع اتصال MT5` | الجسر يعيد التهيئة تلقائيًا. إن استمر، أعد تشغيل MT5 |
| الشموع متقدمة/متأخرة ساعات | اترك `BRIDGE_SERVER_TZ_OFFSET=auto` — سيقيس الفارق عند أول tick |

## تبديل الخادم إلى وضع الجسر

عندما يعمل الجسر عندك وتريد أن يكون **مصدر البيانات الوحيد** (بدل Yahoo):
على الخادم في `.env` غيّر `NEXUS_DATA_SYNTHETIC_FALLBACK=0` (لإيقاف البيانات الاصطناعية)، ثم أعِد تشغيل الأسطول.
(قبل التبديل يعمل المصدران معًا — لا مشكلة للتجربة)

## تشغيل عدة جسور على نفس الجهاز (متقدم)

لو أردت تشغيل جسر ZYSB بجانب جسر آخر لمشروع مختلف على نفس جهاز Windows:

1. انسخ مجلد `B_Yemen_Smart` إلى مجلد آخر (مثل `B_Other_Project`)
2. في كل مجلد، عدّل `.env`:

   ```
   # في B_Yemen_Smart\.env
   BRIDGE_NAME=ZYSB
   BRIDGE_LOG_FILE=zysb.log
   NEXUS_URL=https://preview-chat-<chat_id>.space-z.ai
   NEXUS_BRIDGE_TOKEN=nxb-zysb-token-here

   # في B_Other_Project\.env
   BRIDGE_NAME=OTHER
   BRIDGE_LOG_FILE=other.log
   NEXUS_URL=https://other-server.com
   NEXUS_BRIDGE_TOKEN=nxb-other-token-here
   ```

3. شغّل كل جسر في CMD منفصل
4. كل سطر سجل سيحوي `[ZYSB]` أو `[OTHER]` للتمييز
5. ملفات السجل منفصلة: `zysb.log` و `other.log`

هذا يفيد المطورين الذين يشغّلون عدة مشاريع تداول على نفس جهاز Windows.
