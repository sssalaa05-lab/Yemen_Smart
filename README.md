<div align="center">

# 🛰️ Yemen Smart — Nexus Trading System MT5

### نظام تداول آلي بالذكاء الاصطناعي لـ MetaTrader 5 (XAUUSD & BTCUSD)

**محرك من 9 خدمات مصغّرة يدمج بين: انسامبل تعلم آلي كمي، ومناظرة وكلاء ذكاء توليدي، وتعلم تعزيزي، ومدير مخاطر سلوكي حي — يتحلّى بالبنية الحقيقية للسوق وينفّذ على MT5.**

📄 عربي · ⚖️ AGPL-3.0 · 🐍 Python 3.11+ · ⚛️ Next.js 14

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-14-000000?logo=nextdotjs&logoColor=white)
![XGBoost](https://img.shields.io/badge/XGBoost-ensemble-EB5B25)
![PyTorch](https://img.shields.io/badge/PyTorch-LSTM-EE4C2C?logo=pytorch&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-multi--agent-1C3C3C)
![Redis](https://img.shields.io/badge/Redis-streams-DC382D?logo=redis&logoColor=white)
![License](https://img.shields.io/badge/Licence-AGPL--3.0-blue)

</div>

---

> ⚠️ **تنويه.** هذا مشروع بحثي ومحفظة شخصية. تداول الأدوات المرفوعة (الذهب، عقود فروقات العملات الرقمية) ينطوي على خطر كبير لخسارة رأس المال. المستودع **لا يتضمن أي بيانات اعتماد** ويتصل افتراضيًا بحساب **تجريبي (Demo)**. لا شيء هنا يُعدّ نصيحة مالية. الاستخدام على مسؤوليتك الخاصة.

---

## 📚 الوثائق

| الدليل | المحتوى |
|---|---|
| **[هذا الملف](README.md)** | نظرة عامة، البنية، كيفية التشغيل |
| **[SETUP-GUIDE-AR.md](docs/SETUP-GUIDE-AR.md)** | دليل التركيب الكامل بالعربية |
| **[RESTORE.md](docs/RESTORE.md)** | خطوات استعادة النسخة الاحتياطية |
| **[WORKLOG.md](WORKLOG.md)** | سجل تطوير المشروع التراكمي (23 مهمة) |
| **[README.original.en.md](docs/README.original.en.md)** | README الإنجليزي الأصلي |
| **[README.original.es.md](docs/README.original.es.md)** | README الإسباني الأصلي |
| **[.env.example](.env.example)** | كل إعدادات التكوين موثّقة |

---

## 🎯 ما هو Yemen Smart؟

Yemen Smart (المعروف أيضًا بـ Nexus Trader) هو **عقل تداول آلي بالكامل** مبني كـ **9 خدمات مصغّرة متعاونة**. لا يُشغّل استراتيجية مؤشرات واحدة — بل يُشغّل *خط معالجة من المتخصصين* الذين يتناقشون حتى يصلوا إلى قرار، تمامًا كطاولة تداول حقيقية:

1. **طاولة كمية (Quant Desk)** — انسامبل تعلم آلي (Gradient Boosting + نماذج تتابعية عميقة + كشف الشذوذ) يصوّت على الاتجاه ونظام التقلب وأهداف SL/TP.
2. **طاولة بحث (Research Desk)** — وكلاء ذكاء توليدي (ثور ودب) يتناقشان في الصفقة، وعميل **حَكَم** يُصدر الحكم بدرجة قناعة.
3. **طاولة مخاطر (Risk Desk)** — محرك قواعد حي + حارس سلوكي *anti-tilt* يُحدّد حجم المركز ويستطيع نقض أي قرار.
4. **طاولة تنفيذ (Execution Desk)** — موجّه ذكي يضع الأمر في MT5 مع تحكم بالـ slippage/spread وزر قتل عام.

كل شيء **مبني على الأحداث عبر Redis streams**، **مُهيّأ ديناميكيًا** (لا أرقام سحرية مكتوبة في الكود — الحدود تعيش في Redis وتُحرّر من اللوحة)، و**متعدد الأصول** (نماذج ML منفصلة لكل رمز: الذهب لا يتصرّف كالبيتكوين).

---

## 🧠 طبقتا الذكاء الاصطناعي

معظم "بوتات الذكاء" نموذج واحد. Yemen Smart يُكدّس عمدًا **نوعين متكاملين من الذكاء**، لأنهما يفشلان بطرق مختلفة:

```
┌────────────────────────────────────────┐   ┌────────────────────────────────────────┐
│  🔢 الذكاء الكمي                       │   │  💬 الذكاء التوليدي                     │
│  سريع، عددي، قابل للاختبار الرجعي      │   │  استدلال سياقي + سرد                    │
│                                        │   │                                        │
│  • XGBoost — الاتجاه                   │ ─→│  • باحث ثور (Bull)                     │
│  • LightGBM — النظام + SL/TP           │   │  • باحث دب (Bear)                      │
│  • LSTM — الذاكرة التتابعية            │   │  • حَكَم — الحكم النهائي                │
│  • Isolation Forest — الشذوذ           │   │  • مرصد الأخبار + FinBERT              │
│  • HMM — حالات النظام الخفية           │   │                                        │
└────────────────────────────────────────┘   └────────────────────────────────────────┘
            │ votes + confidence                       │ reasoned verdict
            └─────────────┬───────────────────────────┘
                          ↓
                ⚖️ مدير المخاطر (Veto نهائي)
                          ↓
                ⚡ المنفّذ → MT5
```

- **الذكاء الكمي** دقيق وقابل للاختبار الرجعي لكنه أعمى عن السياق (لا يقرأ عنوان بنك مركزي).
- **الذكاء التوليدي** يقرأ السياق، يزن الأدلة المتضاربة، و*يشرح نفسه* — لكنه يهلوس ولا يقيس الاحتمالات.
- **الحَكَم** يدمج الاثنين، و**مدير المخاطر** لديه الفيتو النهائي غير القابل للتجاوز.

---

## 🏗️ بنية النظام

```
                            ┌─────────────────────────────┐
                            │  🏦 MetaTrader 5            │
                            │  Gold · BTC                 │
                            └──────────────┬──────────────┘
                                           │ (bridge.py on Windows)
                                           ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Yemen Smart — 9 خدمات + لوحة                                           │
│                                                                         │
│  📥 nexus-data :9001        🧮 nexus-features :9002                      │
│  استقبال الشموع + التخزين    مؤشرات MTF + cross-asset                    │
│                                                                         │
│  🤖 nexus-ml :9003          🧠 nexus-agents :9004                       │
│  ensemble لكل رمز            مناظرة LangGraph + حَكَم                    │
│  walk-forward · auto-retrain وكلاء بحث + دورة RL                        │
│                                                                         │
│  📰 nexus-news :9005        ⚖️ nexus-risk :9006                         │
│  تقويم اقتصادي               circuit breakers · anti-tilt               │
│  تحليل مشاعر · blackouts     تحديد حجم المركز                            │
│                                                                         │
│  ⚡ nexus-executor :9007     ❤️ nexus-monitor :9008                      │
│  توجيه ذكي · kill-switch     صحة · تيليمتري                             │
│                                                                         │
│  🌐 nexus-api :9000          📊 Dashboard :3000                          │
│  بوابة / BFF · WebSockets    Next.js 14                                  │
└─────────────────────────────────────────────────────────────────────────┘
                           │
                           ↓
                  🔴 Redis (streams + cache)
                  🦆 DuckDB (analytical store)
```

---

## 📦 محتويات المستودع

| المسار | الوصف |
|---|---|
| `services/` | الخدمات الـ9 (nexus-api, nexus-data, nexus-features, nexus-ml, nexus-agents, nexus-news, nexus-risk, nexus-executor, nexus-monitor) |
| `dashboard/` | لوحة Next.js 14 (TypeScript + Tailwind) |
| `mt5-bridge/` | جسر MT5: `bridge.py` + Expert Advisors + دليل التشغيل |
| `shared/` | نماذج مشتركة وأدوات مساعدة |
| `config/` | ملفات الإعداد |
| `docs/` | الوثائق (دليل التركيب، الاستعادة، README الأصلي، لقطات) |
| `scripts/` | سكربتات التشغيل والصيانة والاختبار |
| `notebooks/` | دفاتر Jupyter للتحليل |
| `tests/` | اختبارات وحدوية لكل خدمة |
| `models_store/` | ملفات نماذج JSON/TXT (النماذج الثنائية `.pkl`/`.joblib` مستبعدة — تُعاد توليدها بالتدريب) |
| `WORKLOG.md` | سجل التطوير التراكمي |
| `.env.example` | قالب الإعدادات (النسخة الحقيقية `.env` مستبعدة لأمان) |
| `requirements.txt` | اعتماديات Python |
| `docker-compose.yml` | تعريف الحاويات |
| `run.py` | نقطة الدخول الرئيسية |
| `preflight.py` | فحص ما قبل التشغيل |

---

## ⚙️ التشغيل السريع

### المتطلبات

- **خادم Linux:** Python 3.11+، Redis 7، Node.js 18+، ~4GB مساحة
- **جهاز Windows:** MetaTrader 5 + Python 3.x (للجسر)

### خطوات التشغيل

```bash
# 1. استنساخ المستودع
git clone https://github.com/sssalaa05-lab/Yemen_Smart.git
cd Yemen_Smart

# 2. نسخ .env.example إلى .env وتعبئة الإعدادات
cp .env.example .env
# عدّل .env: ضع NEXUS_BRIDGE_TOKEN قويًا، MT5_* (للحساب التجريبي)، إلخ.

# 3. تثبيت اعتماديات Python
python3 -m venv .venv
source .venv/bin/activate
# على Linux: احذف سطر MetaTrader5 من requirements.txt
pip install -r requirements.txt

# 4. تشغيل Redis
redis-server --daemonize yes
redis-cli CONFIG SET appendonly yes
redis-cli CONFIG SET appendfsync everysec

# 5. بناء لوحة التحكم
cd dashboard
npm install
npm run build
cd ..

# 6. فحص ما قبل التشغيل
python preflight.py --quick

# 7. تشغيل النظام (الخدمات الـ9 + اللوحة)
python run.py
```

ثم افتح المتصفح على: `http://localhost:3000`

### تشغيل جسر MT5 (على جهاز Windows)

1. ثبّت Python على ويندوز + `pip install MetaTrader5 requests`
2. افتح MT5 وسجّل دخولك (حساب **Demo**)
3. فعّل `Tools → Options → Expert Advisors → Allow algorithmic trading`
4. انسخ `mt5-bridge/bridge.py` إلى جهازك
5. اضبط متغيرات البيئة:
   ```cmd
   set NEXUS_URL=https://your-nexus-domain.com
   set NEXUS_BRIDGE_TOKEN=your-token-here
   ```
6. شغّل: `python bridge.py`

📖 التفاصيل الكاملة في: [`docs/SETUP-GUIDE-AR.md`](docs/SETUP-GUIDE-AR.md)

---

## 🔐 الأمان

### ما هو مُستبعد من المستودع (لن يُرفع إلى GitHub)

| النوع | السبب |
|---|---|
| `.env` | يحتوي `NEXUS_BRIDGE_TOKEN` وأسرار أخرى |
| `dump.rdb` | لقطة Redis فيها تاريخ التدريب الكامل |
| `*.pkl`, `*.joblib`, `*.h5` | نماذج ML مدربة (تُعاد توليدها) |
| `node_modules/`, `.next/` | اعتمدات قابلة للتثبيت |
| `__pycache__/`, `*.pyc` | ملفات تجميع |
| `*.log` | سجلات قد تحتوي معلومات حساسة |
| `*.duckdb`, `*.sqlite*` | قواعد بيانات محلية |

### كيفية التعامل مع الأسرار

1. **لا تضع أي سر في الكود** — استخدم دائمًا متغيرات البيئة
2. **انسخ `.env.example` إلى `.env`** وعدّل القيم محليًا
3. **توكن الجسر**: استخدم `os.environ.get("NEXUS_BRIDGE_TOKEN")` وليس نصًا حرفيًا
4. **إذا تسرّب سر**: ألغِه فورًا من GitHub Settings → Secrets scanning

---

## 📊 حالة المشروع

| المعيار | الحالة |
|---|---|
| **آخر تحديث** | 2026-10-27 |
| **عدد المهام المكتملة** | 23 (راجع WORKLOG.md) |
| **التقنيات الرئيسية** | Python 3.11, FastAPI, Next.js 14, Redis, DuckDB, PyTorch, XGBoost, LangGraph |
| **الترخيص** | AGPL-3.0 |
| **وضع التشغيل الافتراضي** | Paper (محاكاة بدون أموال حقيقية) |
| **الأصول المدعومة** | XAUUSD (الذهب)، BTCUSD (قابل للتوسعة) |

---

## 🤝 المساهمة

هذا مشروع شخصي/بحثي. لطالما سُرّت المساهمة في:
- تحسين نماذج ML
- إضافة أصول جديدة
- تحسين وكلاء LangGraph
- كتابة اختبارات وحدوية إضافية
- تحسين الوثائق

---

## ⚖️ الترخيص

راجع ملف [`LICENSE`](LICENSE) — رخصة AGPL-3.0.

---

## 🙏 شكر وتقدير

- فريق [Nexus Trader](https://github.com/) الأصلي للمشروع المرجعي
- مجتمعات FastAPI, Next.js, PyTorch, LangGraph, XGBoost
- مطورو Redis وDuckDB

---

<div align="center">

**⚠️ تنبيه نهائي:** هذا النظام للأبحاث والتعلم. لا تستخدمه بأموال حقيقية دون فهم كامل للمخاطر.

**صُنع بعناية لخدمة المجتمع اليمني والعربي 🇾🇪**

</div>
