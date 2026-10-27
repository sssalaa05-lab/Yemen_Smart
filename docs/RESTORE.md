# Nexus Trading System — دليل الاستعادة (Restore Guide)

نسخة احتياطية بتاريخ 2026-10-27 — تحتوي كل التعديلات حتى المهمة 22.

> **ابدأ من هنا:** الدليل الكامل المفصّل هو `Nexus-Setup-Guide-AR.docx` (نسخة منسقة للقراءة في Word)
> أو `SETUP-GUIDE-AR.md` (نسخة مختصرة للطرفية) — كلاهما في جذر هذا الأرشيف.
> هذا الملف مجرد ملخص سريع؛ الدليل الشامل يغطي التركيب والتشغيل والفحص واستكشاف الأخطاء.

## محتويات الأرشيف

| المسار | الوصف |
|---|---|
| `nexus-system/Nexus-Trading-System-MT5-main/` | المشروع الكامل بكود الميزات التقويمية (47 ميزة) + النماذج المدرّبة `models_store/XAUUSD/` |
| `dump.rdb` | لقطة Redis لحظة النسخ — **تاريخ التدريب كامل** (1220+ سجلاً بميزات cal_*) |
| `scripts/` | سكربتات التشغيل والاختبار والصيانة |
| `download/` | EA v1.02 + bridge.py v3 + الأدلة + اللقطات |
| `worklog.md` | سجل العمل التراكمي لكل المهام |
| `.env` | الإعدادات (تحتوي bridge token — لا تشاركه) |

## غير المضمّن (قابل لإعادة التوليد)

- `node_modules/` → يُعاد بـ `npm install` داخل dashboard/
- `.venv/` → يُعاد بـ `pip install -r requirements.txt` (احذف سطر MetaTrader5 على لينكس)
- `.next/` → يُعاد بـ `npm run build` داخل dashboard/ ثم انسخ `public/` و`.next/static/` إلى `standalone/`

## خطوات الاستعادة (لينكس)

1. استخرج الأرشيف: `tar xzf nexus-backup-2026-10-27.tar.gz`
2. Redis: شغّل خادم Redis 7 مع وضع `dump.rdb` في مجلد العمل ثم `--daemonize yes`
   (أو جمّع المرفق: `gcc` على scripts/bin المصدر — انظر worklog)
3. البيئة: `cd nexus-system/Nexus-Trading-System-MT5-main && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
4. انسخ `.env` إلى جذر المشروع إن لم يكن موجوداً
5. شغّل الحزمة: `.venv/bin/python run.py --paper --no-frontend`
6. اللوحة: `cd dashboard && npm install && npm run build && cp -r public .next/static .next/standalone/ && node .next/standalone/server.js &`
7. تحقق: `curl localhost:9003/health` يجب أن يظهر `xgboost: true` — واللوحة على 3000

## على جهاز الويندوز (موجود لديك أصلاً — لا يتغير)

- MT5 + `NexusCalendarEA.mq5` v1.02 (SHA256: fe15990d…) على شارت XAUUSD M1
- `bridge.py` v3 يعمل ويجلب الشموع + التقويم كل 5 دقائق

## ملاحظات حرجة

- بعد أي تعديل مستقبلي على EA: أعد ترجمته ثم **اسحبه من جديد على الشارت** (الترمينال لا يعيد التحميل تلقائياً)
- إعادة التدريب التالية المتوقعة: بعد إصدارات 12:30Z/14:00Z — أو يدوياً `POST localhost:9003/api/ml/train -d '{"symbols":["XAUUSD"]}'`
- ميزات التقويم الست (`cal_*`) محقونة في 3 مسارات: التغذية الحية، endpoint التنبؤ، backfill التدريب — أي تدريب مستقبلي يشملها تلقائياً
