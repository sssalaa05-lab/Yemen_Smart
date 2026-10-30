# دورة حياة نماذج التعلم الآلي

## المرشح مقابل النموذج النشط

مسارات التدريب اليدوي وإعادة التدريب المجدول تحفظ ملفاتها تحت `models_store/candidates/<candidate_id>/<symbol>/` وتكتب `candidate_receipt.json` مرتبطًا ببصمة `training_schema.json`. إنشاء candidate لا يغير ملفات النموذج النشط ولا يعيد تحميل candidate إلى التنبؤ الحي. يمكن مراجعة حالة مرشح عبر `GET /api/ml/candidates/{candidate_id}`.

تبقى ملفات `models_store/<SYMBOL>/` هي نسخة champion التي يقرأها النظام. الترقية عملية منفصلة عبر `POST /api/ml/models/promote`، ولا تعمل ما لم يُضبط `NEXUS_ML_PROMOTION_TOKEN`. يتطلب الطلب ترويسة `x-ml-promotion-token` وعبارة تأكيد حرفية `PROMOTE <SYMBOL> <CANDIDATE_ID>`. يتحقق المسار من هوية candidate، وبصمة schema، وسلامة receipt؛ يحفظ نسخة المرشح تحت `models_store/versions/<SYMBOL>/<CANDIDATE_ID>/` ويؤرشف champion السابق قبل استبداله، ثم يعيد تحميل النموذج المعتمد فقط.

لا توجد ترقية تلقائية. عدم تهيئة مفتاح الموافقة يعطل الترقية ويعيد 503. يجب حماية هذا المفتاح وتقييد endpoint على مستوى الشبكة/المصادقة قبل إتاحته خارج بيئة التطوير؛ آلية المفتاح هذه ليست بديلًا عن نظام صلاحيات API مركزي.

## مصدر التدريب وعزل التاريخ

التدريب الحالي يقرأ سجلات feature history من Redis الحي فقط، وينتج مرشحين منفصلين عنها. لا يوجد حتى الآن endpoint لتدريب CSV أو ملف تاريخي؛ لذلك لا تُمرر ملفات CSV إلى Redis ولا تُخلط بياناتها بتاريخ الميزات الحية. إضافة مصدر CSV يجب أن تستخدم مساحة staging/معرف dataset مستقلاً، مع receipt يثبت hash الملف ومصدره ومخططه ووقت الاستيراد، وتُنتج candidate في المسار نفسه دون الكتابة إلى Redis أو champion. لا يُشغّل التدريب تلقائيًا عند رفع/استيراد ملف.

## سجل التقويم وإتاحته الزمنية

نسخ التقويم الواردة تُحفظ append-only في جدول DuckDB `calendar_revisions` مع `event_time` و`available_at` و`revision_id` وpayload المصدر. ميزات التقويم لا تستخدم حدثًا أو revision إذا كان `available_at` أحدث من وقت القرار، وتختار أحدث revision متاح لكل event. إذا غابت `available_at`، تُهمل النسخة بدل افتراض توافرها عند وقت الحدث. هذه الآلية تمنع إعادة استخدام snapshot حديث في الماضي، لكنها لا تعوض مصدرًا لا يسجل فعلًا وقت النشر أو تاريخ revisions الأصلي.

## تحديث محلي — 30 أكتوبر 2026

أُضيف جدول DuckDB عام append-only للنسخ المؤرخة، وبدأت خدمات الأخبار/التقويم والأصول المرتبطة forward capture عند تهيئة `NEXUS_INTERNAL_SERVICE_TOKEN`. تشمل المراجعة هوية provider/record ID وأوقات `published_at`, `event_time`, `available_at` ووقت الاستلام المنفصل. هذا لا يغير قيد مصدر التدريب أعلاه: لا يوجد بعد loader تاريخي يقرأ هذه revisions إلى X حسب `decision_time`؛ لذلك يجب أن تظل الميزات الخارجية غير مؤهلة ما لم يحمل كل سجل training receipt صالحًا ومثبتًا بأن النسخة كانت متاحة عند القرار. لا تُستنتج الإتاحة من آخر قيمة Redis أو من event time.

أُضيف purge عام يستخدم `target_timestamp` الفعلي في طيات walk-forward، واختبارات causal للـprefix/suffix والعائلات الزمنية، واختبارات risk blackout وposition sizing. لا تزال مراجعة كل مسارات feature engineering، vintages التاريخية للمصادر، ومقارنة shadow/paper مطلوبة قبل أي ادعاء بالأداء أو أي ترقية إنتاجية. تشغيل مجموعة pytest الموجهة في 30 أكتوبر أعاد 91 نجاحًا و4 subtests؛ ثم نجحت suite كاملة: **273 passed و4 subtests passed مع تحذير dependency واحد**. لم يحدث اختبار MT5 حي/Demo أو ربط history loader بالتدريب. تفاصيل archive والتفعيل في `docs/PIT_SOURCE_REVISION_ARCHIVE_AR.md`.
