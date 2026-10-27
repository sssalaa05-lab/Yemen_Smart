//+------------------------------------------------------------------+
//|                                              ZYSBCalendarEA.mq5  |
//|   EA رفيق لجسر ZYSB (Yemen Smart Bridge)                         |
//|   يفرّغ التقويم الاقتصادي من ميتاتريدر 5 إلى ملف JSON يقرؤه      |
//|   bridge.py وينشره للخادم.                                       |
//|                                                                  |
//|   v1.10 — إعادة تسمية بـ ZYSB لتمييزها عن EAs أخرى               |
//|   v1.01 — إصلاح أخطاء التجميع:                                   |
//|    - إزالة CALENDAR_MULTIPLIER_PERCENT (غير موجود في MQL5)       |
//|    - إصلاح تحويل long→datetime بأمر صريح                        |
//|                                                                  |
//|   التثبيت:                                                        |
//|   1) MetaEditor (F4) → مجلد Experts → الملف هنا → Compile (F7)   |
//|   2) اسحبه على أي شارت في ترمينال MT5                            |
//|   3) اتركه يعمل — يكتب الملف كل 5 دقائق في مجلد Common\Files     |
//|                                                                  |
//|   ⚠️ الاسم يحوي ZYSB لتمييزه عن EAs أخرى قد تكون مثبتة في MT5    |
//+------------------------------------------------------------------+
#property copyright "Yemen Smart (ZYSB)"
#property version   "1.10"
#property description "ZYSB Calendar EA — يفرّغ التقويم الاقتصادي MT5 إلى zysb_calendar.json لجسر ZYSB"

#property strict

//─── الإعدادات ────────────────────────────────────────────────────────
input string InpCurrencies    = "USD,EUR,GBP,JPY,AUD,CAD,CHF,NZD,CNY"; // العملات (فارغ = الكل)
input int    InpMinImportance = 0;          // أهمية دنيا: 0=الكل 1=متوسط+ 2=عالي فقط
input int    InpDaysBack      = 2;          // أيام ماضية
input int    InpDaysAhead     = 14;         // أيام قادمة
input int    InpTimerSec      = 300;        // دورة التحديث (ثانية)
input string InpFileName      = "zysb_calendar.json"; // اسم الملف (في Common\Files)

string g_lastHash = "";   // منع إعادة الكتابة إن لم يتغير المحتوى
bool   g_calendarDisabled = false;

//+------------------------------------------------------------------+
//| أدوات مساعدة                                                     |
//+------------------------------------------------------------------+
string ImpToString(const ENUM_CALENDAR_EVENT_IMPORTANCE imp)
  {
   if(imp == CALENDAR_IMPORTANCE_HIGH)    return "high";
   if(imp == CALENDAR_IMPORTANCE_MODERATE) return "medium";
   if(imp == CALENDAR_IMPORTANCE_LOW)     return "low";
   return "low";
  }

string ImpactToString(const ENUM_CALENDAR_EVENT_IMPACT im)
  {
   if(im == CALENDAR_IMPACT_POSITIVE) return "positive";
   if(im == CALENDAR_IMPACT_NEGATIVE) return "negative";
   return "na";
  }

// تنظيف النص: إزالة أي رمز غير ASCII حفاظاً على ترميز الملف
string Sanitize(const string src)
  {
   string outp = "";
   int len = StringLen(src);
   for(int i = 0; i < len; i++)
     {
      ushort ch = StringGetCharacter(src, i);
      if(ch >= 32 && ch <= 126)
         outp += StringSubstr(src, i, 1);
      else
         outp += " ";
     }
   // تهريب علامات JSON
   StringReplace(outp, "\\", "\\\\");
   StringReplace(outp, "\"", "\\\"");
   return outp;
  }

//+------------------------------------------------------------------+
//| تنسيق القيمة الرقمية مع وحدة المضاعف                              |
//| ملاحظة: CALENDAR_MULTIPLIER_PERCENT غير موجود في MQL5 —          |
//|        النسبة المئوية تُضاف تلقائيًا عبر digits عند بعض الوسطاء   |
//+------------------------------------------------------------------+
string FormatValue(const MqlCalendarEvent &ev, const long raw)
  {
   double v = (double)raw / MathPow(10.0, (double)ev.digits);
   string s = DoubleToString(v, (int)ev.digits);

   switch(ev.multiplier)
     {
      case CALENDAR_MULTIPLIER_THOUSANDS: s += "K"; break;
      case CALENDAR_MULTIPLIER_MILLIONS:  s += "M"; break;
      case CALENDAR_MULTIPLIER_BILLIONS:  s += "B"; break;
      case CALENDAR_MULTIPLIER_TRILLIONS: s += "T"; break;
      default: break;  // NONE أو أي قيمة أخرى (النسبة المئوية لا تحتاج لاحقة)
     }
   return s;
  }

//+------------------------------------------------------------------+
//| تنسيق التوقيت بصيغة ISO UTC                                      |
//| ملاحظة: تحويل صريح من long إلى datetime لتفادي التحذير            |
//+------------------------------------------------------------------+
string IsoUtc(const datetime server_time, const long tz_offset_sec)
  {
   // تحويل صريح بأمر (datetime) لتفادي تحذير فقدان البيانات
   datetime utc = (datetime)((long)server_time - tz_offset_sec);
   MqlDateTime t;
   TimeToStruct(utc, t);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
                       t.year, t.mon, t.day, t.hour, t.min, t.sec);
  }

//+------------------------------------------------------------------+
//| التفريغ الفعلي                                                   |
//+------------------------------------------------------------------+
void DumpCalendar()
  {
   datetime server_now = TimeTradeServer();
   // تحويل صريح بأمر (long) لتفادي تحذير فقدان البيانات
   long tz_off = (long)((long)TimeTradeServer() - (long)TimeGMT());

   // تحويل صريح بأمر (datetime) بعد ضرب long (تفادي الفيض)
   datetime from = (datetime)((long)server_now - (long)InpDaysBack * 86400);
   datetime to   = (datetime)((long)server_now + (long)InpDaysAhead * 86400);

   MqlCalendarValue values[];
   ResetLastError();
   if(!CalendarValueHistory(values, from, to))
     {
      int err = GetLastError();
      if(err == 4014 || err == 4807) // تقويم معطّل لدى الوسيط
        {
         if(!g_calendarDisabled)
           {
            g_calendarDisabled = true;
            Print("⚠️ ZYSBCalendarEA: التقويم الاقتصادي غير متاح من الوسيط (خطأ ", err, ")");
           }
        }
      else
         Print("⚠️ ZYSBCalendarEA: CalendarValueHistory فشل، خطأ=", err);
      return;
     }

   int total = ArraySize(values);
   if(total <= 0)
     {
      Comment("ZYSBCalendarEA: لا أحداث في النطاق");
      return;
     }

   string json = "{\"bridge_name\":\"ZYSB\",\"generated_at\":\"" + IsoUtc(server_now, tz_off) +
                 "\",\"events\":[";
   int count = 0;

   for(int i = 0; i < total && count < 200; i++)
     {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev))
         continue;
      MqlCalendarCountry cn;
      if(!CalendarCountryById(ev.country_id, cn))
         continue;

      // فلترة الأهمية
      if(InpMinImportance == 1 && ev.importance == CALENDAR_IMPORTANCE_LOW)
         continue;
      if(InpMinImportance >= 2 && ev.importance != CALENDAR_IMPORTANCE_HIGH)
         continue;

      // فلترة العملات
      if(StringLen(InpCurrencies) > 0)
        {
         string curs = InpCurrencies;
         StringToUpper(curs);
         string cur = cn.currency;
         StringToUpper(cur);
         if(StringFind(curs, cur) < 0)
            continue;
        }

      bool past = (values[i].time <= server_now);
      string actual = "null", forecast = "null", previous = "null";

      if(values[i].actual_value != 0 || (past && values[i].actual_value == 0 && values[i].revision > 0))
         actual = "\"" + Sanitize(FormatValue(ev, values[i].actual_value)) + "\"";
      if(values[i].forecast_value != 0)
         forecast = "\"" + Sanitize(FormatValue(ev, values[i].forecast_value)) + "\"";
      if(values[i].prev_value != 0)
         previous = "\"" + Sanitize(FormatValue(ev, values[i].prev_value)) + "\"";

      if(count > 0)
         json += ",";

      json += "{\"event_id\":\"" + IntegerToString((long)values[i].event_id) + "\"" +
              ",\"name\":\"" + Sanitize(ev.name) + "\"" +
              ",\"country\":\"" + Sanitize(cn.code) + "\"" +
              ",\"currency\":\"" + Sanitize(cn.currency) + "\"" +
              ",\"importance\":\"" + ImpToString(ev.importance) + "\"" +
              ",\"time\":\"" + IsoUtc(values[i].time, tz_off) + "\"" +
              ",\"forecast\":" + forecast +
              ",\"previous\":" + previous +
              ",\"actual\":" + actual +
              ",\"impact\":\"" + ImpactToString(values[i].impact_type) + "\"}";
      count++;
     }

   json += "]}";

   if(count == 0)
     {
      Comment("ZYSBCalendarEA: لا أحداث بعد الفلترة (العملات/الأهمية)");
      return;
     }

   // لا تلمس القرص إن لم يتغير شيء
   string hash = IntegerToString(StringLen(json)) + "_" + IntegerToString(count) +
                 "_" + StringSubstr(json, 40, 32);
   if(hash == g_lastHash)
     {
      Comment("ZYSBCalendarEA: لا تغيير — ", count, " حدثاً (آخر تحديث ",
              TimeToString(TimeLocal(), TIME_MINUTES), ")");
      return;
     }
   g_lastHash = hash;

   // كتابة في المجلد المشترك بين كل الترمينالات:
   // %APPDATA%\MetaQuotes\Terminal\Common\Files\zysb_calendar.json
   int h = FileOpen(InpFileName, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
     {
      Print("⚠️ ZYSBCalendarEA: فشل فتح الملف للكتابة، خطأ=", GetLastError());
      return;
     }
   FileWriteString(h, json);
   FileClose(h);

   g_calendarDisabled = false;
   Comment("ZYSBCalendarEA: ✅ نُشر ", count, " حدثاً إلى ", InpFileName,
           " (Common\\Files) — ", TimeToString(TimeLocal(), TIME_DATE | TIME_MINUTES));
   Print("📅 ZYSBCalendarEA: نُشر ", count, " حدثاً اقتصادياً");
  }

//+------------------------------------------------------------------+
//| دورة الحياة                                                      |
//+------------------------------------------------------------------+
int OnInit()
  {
   EventSetTimer(MathMax(60, InpTimerSec));
   DumpCalendar();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
  }

void OnTimer()
  {
   DumpCalendar();
  }
//+------------------------------------------------------------------+
