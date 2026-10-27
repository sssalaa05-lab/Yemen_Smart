"""فحص تاريخ OHLCV في DuckDB — كشف الشموع الاصطناعية المتبقية."""
import duckdb

DB = "/home/z/my-project/nexus-system/Nexus-Trading-System-MT5-main/data/nexus.duckdb"
con = duckdb.connect(DB, read_only=True)

tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
print("tables:", tables)

for t in tables:
    if "ohlcv" not in t.lower():
        continue
    try:
        rows = con.execute(f"""
            SELECT timeframe, COUNT(*) AS n,
                   MIN(timestamp) AS oldest, MAX(timestamp) AS newest,
                   MIN(close) AS min_close, MAX(close) AS max_close
            FROM {t} WHERE symbol='XAUUSD'
            GROUP BY timeframe ORDER BY timeframe
        """).fetchall()
        print(f"\n== {t} (XAUUSD) ==")
        for r in rows:
            print(f"  TF={r[0]:4} n={r[1]:5} {r[2]} -> {r[3]}  close {r[4]:.2f} .. {r[5]:.2f}")
        # كم شمعة اصطناعية (سعر < 3500) لكل فريم
        bad = con.execute(f"""
            SELECT timeframe, COUNT(*) FROM {t}
            WHERE symbol='XAUUSD' AND close < 3500
            GROUP BY timeframe
        """).fetchall()
        if bad:
            print("  SYNTHETIC leftovers (close<3500):", bad)
    except Exception as e:
        print(f"  {t}: {e}")

con.close()
