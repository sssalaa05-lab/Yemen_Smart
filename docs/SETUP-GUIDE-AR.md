# دليل التشغيل والتركيب — نظام Nexus للتداول الآلي (Nexus Trading System MT5)

> هذه النسخة المختصرة القابلة للقراءة في الطرفية. الدليل المفصّل المُنسّق موجود في ملف
> `Nexus-Setup-Guide-AR.docx` بجذر الأرشيف — افتحه بأي إصدار من Word.
> تاريخ الأرشيف: 2026-10-27 — يشمل كل التعديلات حتى المهمة 22 (ميزات التقويم + ثبات Redis).

---

## 1) نظرة سريعة على النظام

```
جهازك (ويندوز)                          خادم Linux
┌────────────────────────┐              ┌──────────────────────────────────┐
│ MT5 Terminal           │              │ 9 خدمات Python (منافذ 9000-9008) │
│  ├ NexusCalendarEA v1.02│── HTTPS ───→│ + لوحة Next.js (منفذ 3000)       │
│  ├ NexusTimeEA (اختياري)│  توكن مشفر │ + Redis 6379 + DuckDB            │
│  └ bridge.py v3        │              │ + 13 وكيل ذكاء + LLM محلي        │
└────────────────────────┘              │ + نماذج ML (XGB/LGBM/RF/Anomaly) │
                                        └──────────────────────────────────┘
```

| الخدمة | المنفذ | وظيفتها |
|---|---|---|
| nexus-api | 9000 | بوابة REST/WebSocket الأمامية |
| nexus-data | 9001 | استقبال الشموع من الجسر + التخزين |
| nexus-features | 9002 | حساب المؤشرات (41 ميزة سوقية) |
| nexus-ml | 9003 | النماذج + التنبؤ + التدريب (47 ميزة بعد إضافة 6 ميزات تقويم cal_*) |
| nexus-agents | 9004 | الوكلاء الـ 13 وصناعة القرار |
| nexus-news | 9005 | التقويم الاقتصادي والأخبار |
| nexus-risk | 9006 | قواعد المخاطر ومقاييس المركز |
| nexus-executor | 9007 | توجيه الأوامر (عبر الجسر عند التفعيل) |
| nexus-monitor | 9008 | الأداء والمراقبة |
| dashboard | 3000 | اللوحة التفاعلية |
| redis | 6379 | كل الحالة الحية + تاريخ التدريب |

---

## 2) محتويات الأرشيف

| المسار | الوصف |
|---|---|
| `nexus-system/Nexus-Trading-System-MT5-main/` | المشروع كاملاً بكود الميزات التقويمية + `models_store/XAUUSD/` (47 ميزة) |
| `dump.rdb` | لقطة Redis لحظة النسخ — تاريخ التدريب كاملاً (1220+ سجلاً) |
| `SETUP-GUIDE-AR.md` + `Nexus-Setup-Guide-AR.docx` | هذا الدليل (نسختان) |
| `RESTORE.md` | ملخص خطوات الاستعادة |
| `scripts/` | سكربتات التشغيل والاختبار والصيانة |
| `download/` | EA v1.02 + bridge.py v3 + bridge-guide.md |
| `worklog.md` | سجل العمل التراكمي لكل المهام |
| `.env` | الإعدادات — **يحتوي NEXUS_BRIDGE_TOKEN: لا تشاركه** |

غير مضمن (يُعاد توليده): `node_modules` بأمر `npm install`، و`.venv` بأمر `pip install -r requirements.txt`، و`.next` بأمر `npm run build`.

---

## 3) المتطلبات

**خادم Linux:** Python 3.10+ (يفضل 3.12)، Redis 7، Node.js 18+، حوالي 4GB مساحة للاعتماديات، أداة `gcc` لبناء Redis من المصدر إن لزم.

**جهاز Windows:** منصة MT5 مسجّل الدخول، Python 3.x مع حزمتي `MetaTrader5` و`requests`.

---

## 4) التركيب على خادم Linux

```bash
# 1. استخراج الأرشيف
tar xzf nexus-backup-2026-10-27.tar.gz

# 2. Redis — شغّل الخادم مع ملف dump.rdb في مجلد العمل
redis-server --daemonize yes --dir <مجلد dump.rdb>
# ثم فعّل الثبات (حرج — بدونه انهيار واحد يمحو تاريخ التدريب):
redis-cli CONFIG SET appendonly yes
redis-cli CONFIG SET appendfsync everysec
redis-cli CONFIG SET save "300 100 60 10000"
redis-cli BGSAVE

# 3. بيئة بايثون (احذف سطر MetaTrader5 من requirements.txt على لينكس)
cd nexus-system/Nexus-Trading-System-MT5-main
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 4. الإعدادات
cp <مكان الأرشيف>/.env .

# 5. تشغيل الحزمة كاملة (الترتيب الداخلي تلقائي)
.venv/bin/python run.py --paper --no-frontend

# 6. لوحة التحكم
cd dashboard && npm install && npm run build
cp -r public .next/static .next/standalone/ 2>/dev/null
node .next/standalone/server.js &
```

**التحقق:** `curl localhost:9003/health` يجب أن يُظهر `xgboost: true` (وأخوته lgbm/anomaly/rf) — إن ظهرت false فالخدمة أقلعت قبل اكتمال تحميل النماذج؛ أعد تشغيلها (انظر القسم 7). اللوحة على المنفذ 3000.

---

## 5) التركيب على جهاز Windows

1. **Python:** ثبّته من python.org مع تفعيل Add to PATH، ثم: `pip install MetaTrader5 requests`
2. **MT5:** سجّل الدخول (حساب Demo أولاً)، وفعّل من Tools → Options → Expert Advisors خيار Allow algorithmic trading
3. **bridge.py:** عدّل أعلى الملف: `NEXUS_URL` و`BRIDGE_TOKEN` (مضبوطان)، `SYMBOL_MAP` لاسم الرمز عند وسيطك، اترك `SERVER_TZ_OFFSET_HOURS="auto"` و`EXECUTE=False`، ثم شغّل: `python bridge.py` — اتركه يعمل دائماً
4. **NexusCalendarEA v1.02:** انسخه إلى `MQL5\Experts` (من MT5: File → Open Data Folder)، افتحه في MetaEditor واضغط F7 للترجمة، ثم اسحبه من Navigator على شارت **XAUUSD إطار M1** — ينشر التقويم الاقتصادي كل 5 دقائق
5. **NexusTimeEA (اختياري):** لدقة توقيت 100% — اسحبه على أي شارت، يكتب ملفاً فقط ولا يتداول

⚠️ **بعد أي تعديل على أي EA:** أعد ترجمته (F7) ثم **اسحبه من جديد على الشارت** — الترمينال لا يعيد تحميله تلقائياً.

التفصيل الكامل للجسر في `download/bridge-guide.md`.

---

## 6) التشغيل اليومي (يحدث تلقائياً دون تدخلك)

- كل شمعة M5 جديدة تُخبز بـ **47 ميزة** (41 سوقية + 6 تقويمية لحظية بلا تسريب مستقبلي)
- الجسر يعيد نشر التقويم كل 5 دقائق، وكاش التقويم الداخلي بنفس الدورية
- المفاجآت الاقتصادية (actual vs forecast) تتراكم مع الإصدارات الفعلية وتدخل إعادة التدريب التالية
- إعادة تدريب تلقائية كل 24 ساعة (cooldown) — أو يدوياً: `curl -X POST localhost:9003/api/ml/train -d '{"symbols":["XAUUSD"]}'`
- الحفظ ثلاثي الطبقات: نماذج على القرص + AOF كل ثانية + RDB دوري — انهيار Redis لا يفقد شيئاً

**التزامك الوحيد:** إبقاء جهاز الويندوز (MT5 + bridge.py) يعمل — هو مصدر الشموع والتقويم.

---

## 7) استكشاف الأخطاء (حالات حقيقية)

| العَرَض | السبب | الحل |
|---|---|---|
| `/health` يظهر النماذج false | الخدمة أقلعت قبل اكتمال كتابة النماذج | `pkill -f nexus_ml` — run.py يعيد تشغيلها ويحمّل النماذج |
| تبحث عن اللوجات في المكان الخطأ | `/tmp/nexus_run.log` بقايا عملية قديمة | اللوج الحقيقي: `logs/nexus_run.log` |
| فقدان تاريخ التدريب بعد انهيار Redis | persistence معطّل | طبّق أوامر CONFIG في القسم 4 ثم BGSAVE |
| القرص ممتلئ (95%+) | كاشات ضخمة (venv مكرر/puppeteer/playwright) | `df -h` ثم احذف الكاشات؛ انتبه: حذف ملفات طبقة الصورة لا يحرر مساحة فعلياً |
| الجسر يرد 401 | توكن غير مطابق | طابق `BRIDGE_TOKEN` في bridge.py مع `NEXUS_BRIDGE_TOKEN` في .env |
| الشموع متقدمة/متأخرة ساعات | إزاحة توقيت سيرفر الوسيط | اترك `SERVER_TZ_OFFSET_HOURS="auto"` — يصحح نفسه عند أول tick |
| الشارت لا يتحرك | الخادم ليس في وضع الجسر | تأكد من وضع مصدر البيانات bridge في إعدادات التشغيل |
| تعديل EA لا يظهر | الترمينال لا يعيد التحميل | أعد الترجمة F7 + اسحب EA من جديد على الشارت |

---

## 8) النسخ الاحتياطي والاستعادة

**لعمل نسخة جديدة في أي وقت (من جذر المشروع):**

```bash
redis-cli BGSAVE   # انتظر ثانيتين حتى تكتمل
tar czf nexus-backup-$(date +%F).tar.gz \
  --exclude='node_modules' --exclude='.venv' --exclude='.next' --exclude='__pycache__' \
  nexus-system dump.rdb .env worklog.md scripts download logs/nexus_run.log \
  RESTORE.md SETUP-GUIDE-AR.md Nexus-Setup-Guide-AR.docx
```

**الاستعادة:** اتبع القسم 4 بالترتيب — الأرشيف ذاته كافٍ لإقامة النظام من الصفر على خادم نظيف. احتفظ بنسخة من هذا الأرشيف على جهازك الشخصي، ومعها ملفات الويندوز (EA + bridge.py) الموجودة لديك أصلاً.
