# 🔄 خطوات الاسترجاع غداً — تشغيل كل شيء من الصفر

## أ) استرجاع المشروع (داشبورد FinGPT Gold + لوحة يمن سمارت)

```bash
# 1. انسخ مجلد المشروع من النسخة الاحتياطية إلى مكان عمل جديد
cp -r backup-gold-2026-11-03/01-project  ~/my-project-restored
cd ~/my-project-restored

# 2. أعد بناء المكتبات من ملف القفل (نفس الإصدارات بالضبط)
bun install          # أو: npm install

# 3. جهّز قاعدة البيانات (Prisma + SQLite)
bun run db:push

# 4. شغّل بيئة التطوير
bun run dev          # ← يعمل على المنفذ 3000
```

**يفتح عندك فوراً:**
- `http://localhost:3000/` — داشبورد FinGPT Gold (شموع + أخبار + إشارات)
- زر **«🥇 يمن سمارت»** في الهيدر ← لوحة يمن سمارت الذهبية
- أو مباشرة: `http://localhost:3000/?smart=1`

## ب) استرجاع النموذج والمحوّلات

المحوّلات المدربة جاهزة في `03-model/fingpt_run/`:
- `adapter/` — المحوّل العام (75%)
- `adapter_gold/` — **محوّل الذهب (92.5%)**

خادم الاستدلال كان يعمل على `127.0.0.1:8766` (محوّلان). سكربتات التشغيل والتدريب كلها داخل `01-project/scripts/` ومستودع `03-model/FinGPT/`.

## ج) حزم التصميم (اختياري)

- `02-packages/design-theme-kit/` — ثيم الذهب الداكن لأي مشروع جديد (globals.css + خطوط + توكنات + برومبت).
- `02-packages/yemen-smart-gold/` — `gold-admin.css` لحقن الهوية الذهبية في يمن سمارت الأصلية + دليل GOLD_PROMPT.

## د) ملاحظات

1. **المكتبات ليست مضمنة** — تُعاد تلقائياً من `bun.lock` بالأمر في الخطوة 2 (هذا هو المعيار الصحيح للنسخ الاحتياطي).
2. ملفات البيانات الكبيرة (بيانات الشموع) داخل `01-project/public/gold/` — كاملة.
3. الهوية اليمنية داخل `01-project/public/yemen/` — مدمجة في الكود عبر `next/image`.
4. لو تريد النسخ على جهاز آخر: حمّل المجلد من GitHub (Code → Download ZIP) أو:
   ```bash
   git clone https://github.com/sssalaa05-lab/Yemen_Smart.git
   cp -r Yemen_Smart/backup-gold-2026-11-03/01-project ~/my-project-restored
   ```
