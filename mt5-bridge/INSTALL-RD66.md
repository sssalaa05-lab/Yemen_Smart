# ════════════════════════════════════════════════════════════════════════════
#   دليل تثبيت ZYSB على جهازك — مسار MT5 محدد
# ════════════════════════════════════════════════════════════════════════════

## مسار MT5 على جهازك

```
C:\Users\rd66\AppData\Roaming\MetaQuotes\Terminal\22D22E9B393E16F638B440240FDD255D\MQL5\Experts
```

### تحليل المسار

| الجزء | المعنى |
|---|---|
| `C:\Users\rd66\` | مجلد المستخدم الخاص بك |
| `AppData\Roaming\` | بيانات تطبيقات Windows |
| `MetaQuotes\Terminal\` | جذر بيانات MetaTrader |
| `22D22E9B...255D\` | **معرّف فريد** لنسخة MT5 لديك (كل تثبيت له hash مختلف) |
| `MQL5\Experts\` | مجلد Expert Advisors |

### المجلدات المهمة تحت `MQL5\`

```
C:\Users\rd66\AppData\Roaming\MetaQuotes\Terminal\22D22E9B393E16F638B440240FDD255D\MQL5\
├── Experts\         ← ضع هنا: ZYSBTimeEA.mq5, ZYSBCalendarEA.mq5
├── Scripts\
├── Indicators\
├── Include\
├── Libraries\
└── Files\           ← sandbox للملفات (لكل EA منفصل)
```

### المجلد المشترك (Common) — الأهم

```
C:\Users\rd66\AppData\Roaming\MetaQuotes\Terminal\Common\Files\
├── zysb_server_time.json     ← يُكتب تلقائيًا بواسطة ZYSBTimeEA
└── zysb_calendar.json   ← يُكتب تلقائيًا بواسطة ZYSBCalendarEA
```

> 💡 `bridge.py` يبحث تلقائيًا في هذا المسار المشترك عبر متغير البيئة `APPDATA`،
> لذا **لا تحتاج لتحديد المسار يدويًا** — الكود يجده تلقائيًا.

---

## الخطوة 1: تثبيت EA الرفيقة (اختياري — للحصول على دقة توقيت 100%)

### 1.1 فتح مجلد MT5

من داخل MT5:
- اضغط **Ctrl+N** لفتح Navigator، أو
- من القائمة: **File → Open Data Folder**

سيفتح مجلد `MQL5\` تلقائيًا.

### 1.2 نسخ ملفات EA

افتح مجلد `Experts\` وانسخ إليه:

```
من:  C:\B_Yemen_Smart\ZYSBTimeEA.mq5
إلى: C:\Users\rd66\AppData\Roaming\MetaQuotes\Terminal\22D22E9B393E16F638B440240FDD255D\MQL5\Experts\ZYSBTimeEA.mq5

من:  C:\B_Yemen_Smart\ZYSBCalendarEA.mq5
إلى: C:\Users\rd66\AppData\Roaming\MetaQuotes\Terminal\22D22E9B393E16F638B440240FDD255D\MQL5\Experts\ZYSBCalendarEA.mq5
```

### 1.3 إعادة تحميل EAs في MT5

في MT5:
- اضغط **F5** في محرر MetaEditor، أو
- أعد تشغيل MT5

سترى في Navigator → Expert Advisors:
- `ZYSBTimeEA`
- `ZYSBCalendarEA`

### 1.4 تثبيت ZYSBTimeEA على شارت

1. اسحب `ZYSBTimeEA` من Navigator إلى أي شارت (مثل XAUUSD M5)
2. في نافذة الخصائص:
   - **Common**: فعّل ✅ "Allow Algorithmic Trading" (اختياري — الـ EA يعمل بدونه أيضًا)
   - **Inputs**: اترك `InpWriteSec = 10` (يكتب كل 10 ثوانٍ)
3. اضغط **OK**

ستشاهد في تبويب **Experts**:
```
ZYSBTimeEA: يعمل — يكتب Common\Files\zysb_server_time.json
```

### 1.5 (اختياري) تثبيت ZYSBCalendarEA

نفس الطريقة، لكن هذا الـ EA يكتب التقويم الاقتصادي كل 5 دقائق.

---

## الخطوة 2: التحقق من كتابة الملف

بعد تثبيت `ZYSBTimeEA` لمدة 30 ثانية، تحقق من وجود الملف:

```cmd
dir "C:\Users\rd66\AppData\Roaming\MetaQuotes\Terminal\Common\Files\zysb_server_time.json"
```

يجب أن ترى:
```
 Volume in drive C has no label.
 Directory of C:\Users\rd66\AppData\Roaming\MetaQuotes\Terminal\Common\Files

27/10/2026  08:30 PM                85 zysb_server_time.json
```

افتحه بـ Notepad:
```json
{"server_time":1729967400,"gmt_time":1729960200,"offset_seconds":7200,"offset_hours":2.00}
```

> 💡 `offset_hours: 2.00` يعني أن سيرفر الوسيط متقدم عن GMT بـ ساعتين (توقيت أوروبا الشرقي).

---

## الخطوة 3: تشغيل ZYSB

```cmd
cd /d C:\B_Yemen_Smart
python bridge.py
```

سترى في السجل:
```
20:30:01 | INFO    | [ZYSB] | ═══ ZYSB — Yemen Smart Bridge v3.0 ═══
20:30:01 | INFO    | [ZYSB] | ✅ متصل: حساب 12345 | broker-Demo | DEMO ✅
20:30:01 | INFO    | [ZYSB] | 🕒 فارق التوقيت المقاس من أحدث tick: +2 ساعة
20:30:01 | INFO    | [ZYSB] | 📌 XAUUSD → XAUUSD (digits=2, point=0.01)
20:30:01 | INFO    | [ZYSB] | 🌱 بذر 1500 شمعة لـ XAUUSD
20:30:01 | INFO    | [ZYSB] | 🚀 بدء الحلقة الرئيسية
```

> 💡 لو ثبّت `ZYSBTimeEA`، سيستخدم ZYSB قياسه الدقيق بدلًا من القياس التقريبي من tick.

---

## اختياري: تخصيص المسار في `.env`

لو أردت تحديد مسار مختلف لملف `zysb_server_time.json` (مثلاً لو لديك تثبيت MT5 آخر):

```env
# في C:\B_Yemen_Smart\.env
BRIDGE_SERVER_TIME_FILE=C:\Users\rd66\AppData\Roaming\MetaQuotes\Terminal\Common\Files\zysb_server_time.json
BRIDGE_CALENDAR_FILE=C:\Users\rd66\AppData\Roaming\MetaQuotes\Terminal\Common\Files\zysb_calendar.json
```

افتراضيًا، ZYSB يبحث تلقائيًا في:
1. المجلد الحالي (`C:\B_Yemen_Smart\`)
2. `%APPDATA%\MetaQuotes\Terminal\Common\Files\`

لذا **لا تحتاج لتعديل شيء** في الإعداد الافتراضي.

---

## حل المشاكل

### المشكلة: الـ EA لا يكتب الملف

**الأعراض:** `dir` يُظهر أن `zysb_server_time.json` غير موجود

**الحلول:**
1. تأكد أنك نسخت الـ EA إلى `MQL5\Experts\` وليس مجلد آخر
2. في MT5: **Tools → Options → Expert Advisors** → فعّل ✅ "Allow Algorithmic Trading"
3. تأكد أن الـ EA مُثبّت على شارت مفتوح (تراه في تبويب **Experts** بأيقونة وجه مبتسم 😊)
4. راجع تبويب **Experts** لأي أخطاء

### المشكلة: ZYSB لا يجد الملف

**الأعراض:** `bridge.py` يطبع `🕒 فارق التوقيت المقاس من أحدث tick` بدلًا من القراءة من الملف

**السبب:** الـ EA لم يكتب الملف بعد، أو المسار غير صحيح

**الحل:**
1. شغّل `ZYSBTimeEA` لمدة 30 ثانية على الأقل
2. تحقق من المسار يدويًا:
   ```cmd
   dir "%APPDATA%\MetaQuotes\Terminal\Common\Files\zysb_server_time.json"
   ```
3. لو الملف في مسار مختلف، حدده في `.env`:
   ```env
   BRIDGE_SERVER_TIME_FILE=C:\path\to\zysb_server_time.json
   ```

### المشكلة: رسالة "الرمز XAUUSD غير موجود"

**السبب:** الرمز ليس في Market Watch

**الحل:**
1. في MT5: اضغط **Ctrl+M** لفتح Market Watch
2. ابحث عن `XAUUSD` أو `GOLD`
3. إن لم تجده: راجع وسيطك — بعض الوسطاء يستخدمون أسماء مثل `XAUUSDm` أو `XAUUSD.r`
4. حدّث `.env` بالاسم الفعلي:
   ```env
   BRIDGE_SYMBOLS=XAUUSD:XAUUSDm
   ```

---

## ملخص سريع

| المهمة | المسار على جهازك |
|---|---|
| ZYSB (الجسر) | `C:\B_Yemen_Smart\bridge.py` |
| إعدادات ZYSB | `C:\B_Yemen_Smart\.env` |
| EAs (تُنسخ إلى MT5) | `C:\B_Yemen_Smart\ZYSBTimeEA.mq5` → `MQL5\Experts\` |
| ملف zysb_server_time.json | `%APPDATA%\MetaQuotes\Terminal\Common\Files\` (يُكتب تلقائيًا) |
| ملف zysb_calendar.json | `%APPDATA%\MetaQuotes\Terminal\Common\Files\` (يُكتب تلقائيًا) |
| سجل ZYSB | `C:\B_Yemen_Smart\zysb.log` |
| MT5 instance | `22D22E9B393E16F638B440240FDD255D` (معرّف فريد لتثبيتك) |
