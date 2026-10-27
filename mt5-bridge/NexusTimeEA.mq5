//+------------------------------------------------------------------+
//|                                                 NexusTimeEA.mq5 |
//|   EA رفيق لجسر Nexus — يقيس فارق توقيت سيرفر الوسيط عن GMT      |
//|                                                                  |
//|   المصدر: وثيقة MQL5 الرسمية Date and Time                       |
//|   https://www.mql5.com/en/docs/dateandtime                       |
//|                                                                  |
//|   الفكرة (من الوثيقة):                                          |
//|     TimeCurrent() = آخر توقيت سيرفر معروف — وهو نفس التوقيت      |
//|                     المكتوب داخل الشموع والتكس التي يقرأها الجسر |
//|     TimeGMT()     = توقيت GMT الحقيقي                            |
//|     الفارق بينهما = الإزاحة التي يحتاجها bridge.py لتحويل        |
//|                     الشموع إلى UTC بدقة (تشمل التوقيت الصيفي)    |
//|                                                                  |
//|   التثبيت:                                                       |
//|     1) في MT5: File → Open Data Folder → MQL5 → Experts          |
//|        وانسخ هذا الملف هناك، ثم أعد تشغيل MT5 (أو F5 في المحرر)  |
//|     2) اسحب NexusTimeEA من Navigator على أي شارت واتركه          |
//|     3) لا يتداول ولا يعدل شيئاً — يكتب ملفاً فقط،                |
//|        ويعمل حتى لو زر Algo Trading مطفأ                          |
//|                                                                  |
//|   الملف يُكتب في مجلد Common\Files الخاص بالترمينال:            |
//|     C:\Users\<اسمك>\AppData\Roaming\MetaQuotes\Terminal\         |
//|         Common\Files\server_time.json                            |
//|   انسخ هذا المسار إلى SERVER_TIME_FILE في bridge.py              |
//+------------------------------------------------------------------+
#property copyright "Nexus Trading System"
#property version   "1.00"

input int InpWriteSec = 10; // فترة الكتابة بالثواني

const string FILE_NAME = "server_time.json";

//+------------------------------------------------------------------+
int OnInit()
  {
   EventSetTimer(MathMax(1, InpWriteSec));
   WriteOffset();
   Print("NexusTimeEA: يعمل — يكتب Common\\Files\\", FILE_NAME);
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   WriteOffset();
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

//+------------------------------------------------------------------+
void WriteOffset()
  {
   datetime srv     = TimeCurrent();            // توقيت السيرفر (أساس الشموع)
   datetime gmt     = TimeGMT();                // GMT الحقيقي
   long     diffSec = (long)srv - (long)gmt;     // الإزاحة المطلوبة بالثواني

   string json = StringFormat(
      "{\"server_time\":%I64d,\"gmt_time\":%I64d,\"offset_seconds\":%d,\"offset_hours\":%.2f}",
      (long)srv, (long)gmt, (int)diffSec, (double)diffSec / 3600.0);

   // FILE_COMMON = مجلد مشترك يسهل الوصول إليه من خارج الترمينال
   int h = FileOpen(FILE_NAME, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(h == INVALID_HANDLE)
     {
      Print("NexusTimeEA: فشل كتابة الملف، خطأ ", GetLastError());
      return;
     }
   FileWriteString(h, json);
   FileClose(h);
  }
//+------------------------------------------------------------------+
