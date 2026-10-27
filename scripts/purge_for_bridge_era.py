"""تنظيف شامل لعصر الجسر (bridge era):

السياق:
- أول بذر (400 شمعة) تم بفارق توقيت احتياطي +2.0 بينما القياس الحي أثبت +3.0
  (OneRoyal على توقيت DST الأمريكي حتى 1 نوفمبر) → كل الشموع القديمة منزاحة +1 ساعة
  (أشباح: كل شمعة حقيقية موجودة مرتين، مرة صحيحة ومرة بعد ساعة).
- مصدر Yahoo (GC=F) ما زال يعمل وكان سيمزج أسعار ~4030$ مع أسعار OneRoyal ~4017$.

الإجراء:
1) حذف كل صفوف ohlcv و ticks من DuckDB (كل الرموز — بداية نظرة 100% لبيانات الوسيط).
2) تصفير كاشات Redis المرتبطة (شموع/ميزات/إشارات/ML/GenAI) مع الحفاظ على
   runtime:settings و strategy و health و news و auth و bridge:status و trades.
3) طباعة إحصاءات قبل/بعد للتدقيق.
يُشغَّل والأسطول متوقف (قفل الكاتب حصري).
"""
import sys

DB = "/home/z/my-project/nexus-system/Nexus-Trading-System-MT5-main/data/nexus.duckdb"

# ── 1) DuckDB ────────────────────────────────────────────────────────────────
import duckdb

con = duckdb.connect(DB)

tables = [r[0] for r in con.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
).fetchall()]
print("tables:", tables)

for t in tables:
    try:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} rows (before)")
    except Exception as e:
        print(f"  {t}: skip ({e})")

# توزيع قبل الحذف (للتقرير)
try:
    dist = con.execute(
        "SELECT symbol, COUNT(*), MIN(timestamp), MAX(timestamp) "
        "FROM ohlcv GROUP BY symbol ORDER BY symbol"
    ).fetchall()
    for d in dist:
        print("  ohlcv:", d)
except Exception as e:
    print("  dist: ", e)

for t in ("ohlcv", "ticks"):
    if t in tables:
        con.execute(f"DELETE FROM {t}")
        print(f"DELETE FROM {t} -> remaining {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")

con.execute("CHECKPOINT")
con.close()
print("duckdb: purged + checkpointed")

# ── 2) Redis ────────────────────────────────────────────────────────────────
import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

purged = []
patterns = [
    "nexus:ohlcv:*", "nexus:features:*", "features:*", "stream:features",
    "stream:ticks*", "stream:ohlcv*", "nexus:signal*", "stream:signals*",
    "nexus:ml:*", "nexus:genai:*", "nexus:agent*", "nexus:calendar:*",
]
for p in patterns:
    keys = list(r.scan_iter(match=p, count=200))
    # لا نمس الإعدادات والاستراتيجيات والصحة والأخبار وauth وحالة الجسر والصفقات
    keys = [k for k in keys if not any(
        s in k for s in (
            "runtime:settings", "strategy", "health", "news",
            "auth", "bridge:status", "trade",
        )
    )]
    if keys:
        r.delete(*keys)
        purged += keys

print(f"redis purged {len(purged)} keys")
for k in purged[:15]:
    print("  -", k)
print("DONE")
