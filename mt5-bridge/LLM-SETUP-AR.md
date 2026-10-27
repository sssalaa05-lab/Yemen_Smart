# تفعيل وكلاء LangGraph الذكية في Yemen Smart

> **المزود:** Z.ai — نموذج GLM-4.5-Flash (مجاني، 128K context)  
> **الميزات:** Daily Brief، Bull/Bear Debate، Arbitrator، News Sentiment، Strategy Research

---

## الخطوة 1: احصل على مفتاح Z.ai API

1. اذهب إلى https://z.ai/ أو https://open.bigmodel.cn
2. سجّل حسابًا (مجاني تمامًا)
3. من Dashboard → API Keys → **Create new key**
4. انسخ المفتاح — سيكون بصيغة:
   ```
   apiKeyId.apiKeySecret
   ```
   مثال (صيغة فقط — استبدل بمفتاحك):
   ```
   abcdef1234567890abcdef1234567890.XyZExampleSecretKey1
   ```

---

## الخطوة 2: أضف المفتاح إلى `.env` على الخادم

> ⚠️ المفتاح يُحفظ في `.env` فقط (محليًا على الخادم) — لا يُرفع إلى GitHub.

في ملف `/home/z/my-project/yemen-smart/.env` على الخادم:

```env
# Z.ai (GLM-4.5-Flash)
NEXUS_LLM_PROVIDER=zai
NEXUS_LLM_API_KEY=YOUR_KEY_HERE
NEXUS_LLM_API_URL=https://api.z.ai/api/paas/v4

# تفعيل البحث الاستراتيجي
NEXUS_DISABLE_RESEARCH=0
NEXUS_DISABLE_RESEARCH_LLM=0
```

---

## الخطوة 3: أعد تشغيل nexus-agents

```bash
# على الخادم (داخل جلسة Z.ai)
pkill -f "uvicorn services.nexus_agents"
sleep 3

cd /home/z/my-project/yemen-smart
/home/z/.venv/bin/python /home/z/my-project/scripts/daemonize.py \
  /home/z/my-project/yemen-smart/logs/nexus-agents.log \
  /home/z/my-project/yemen-smart \
  /home/z/.venv/bin/python -m uvicorn services.nexus_agents.main:app \
    --host 0.0.0.0 --port 9004 --log-level info
```

---

## الخطوة 4: تحقق من التفعيل

```bash
# 1. حالة الخدمة
curl http://127.0.0.1:9004/health
# يجب أن يرى: status=healthy

# 2. اختبار مباشر لـ Z.ai API
curl -X POST "https://api.z.ai/api/paas/v4/chat/completions" \
  -H "Authorization: Bearer YOUR_KEY_HERE" \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-4.5-flash","messages":[{"role":"user","content":"Say OK"}],"max_tokens":10}'
# يجب أن يرى: {"choices":[{"message":{"content":"OK"}}]}

# 3. عبر الـ URL العام
curl https://preview-chat-<chat_id>.space-z.ai/api/agents/health
```

---

## ما الذي ستراه في اللوحة بعد التفعيل

| الميزة | قبل | بعد |
|---|---|---|
| **Daily Brief** (ملخص يومي) | ❌ 401 Authentication | ✅ ملخص يومي بالعربية (6 و 13 UTC) |
| **Bull/Bear Debate** | ❌ معطّلة | ✅ مناظرة LangGraph حقيقية قبل كل قرار |
| **Arbitrator** (الحَكَم) | ❌ rule-based فقط | ✅ استدلال LLM للحكم النهائي |
| **News Sentiment** | ❌ معطّل | ✅ تحليل سياقي للأخبار بالعربية |
| **Strategy Research** | ❌ معطّل | ✅ بحث استراتيجيات جديدة بالـ LLM |

---

## الأمان

- ✅ المفتاح يُحفظ في `.env` فقط (محليًا على الخادم)
- ✅ لا يتم تخزين بياناتك على Z.ai (نموذج stateless)
- ✅ المفتاح يُستخدم فقط للاستدعاءات من `nexus-agents` إلى Z.ai
- ⚠️ **إذا تسرّب المفتاح**: ألغِه فورًا من https://z.ai/dashboard/api-keys
- ⚠️ **لا ترفع `.env` إلى GitHub** (مستبعد بالفعل في `.gitignore`)

---

## استكشاف الأخطاء

| الخطأ | السبب | الحل |
|------|------|------|
| `401 Authentication parameter not received` | `NEXUS_LLM_API_KEY` فارغ | أضفه إلى `.env` |
| `401 invalid api key` | مفتاح خاطئ أو منتهي | تحقق من النسخ الصحيح أو أنشئ مفتاحًا جديدًا |
| `429 quota exceeded` | تجاوز الحصة المجانية | انتظر للتجديد الشهري أو ارتقِ للخطة المدفوعة |
| `timeout` | بطء الشبكة | زِد `NEXUS_LLM_TIMEOUT=120` |
| `Daily Brief generation failed` | المفتاح غير مفعّل | أعد تشغيل `nexus-agents` بعد تحديث `.env` |

---

## الحصة المجانية (Free Tier)

حسب آخر تحديث من Z.ai:

| المعيار | القيمة |
|---|---|
| النموذج | GLM-4.5-Flash |
| الحصة الشهرية | 100M tokens (مجاني) |
| Context window | 128K tokens |
| Function calling | ✅ مدعوم |
| JSON mode | ✅ مدعوم |
| اللغة العربية | ✅ مدعومة |

> 💡 100M tokens تكفي لـ ~10,000 مناظرة Bull/Bear يوميًا — كافية للاستخدام الشخصي.

---

## روابط مفيدة

- الحصول على مفتاح: https://z.ai/
- لوحة التحكم: https://z.ai/dashboard/api-keys
- وثائق API: https://docs.z.ai/
- تسعير GLM-4.5-Flash: https://z.ai/pricing
