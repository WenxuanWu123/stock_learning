#!/usr/bin/env python3
"""个股库构建：data/stocks/daily/*.parquet + meta.csv -> stocks.db（独立 SQLite）。

用法: .venv/bin/python scripts/build_stocks_db.py

设计要点：
- 独立建库（stocks.db），不并入 stock_learning.db：个股数据基本静态，避免每次
  rebuild.sh 都重导数百万行。
- 幂等：每次全量重建到临时文件 stocks.db.tmp，完成后原子替换，可重复执行；
  抓取进程正在写入的 parquet 若读取失败会跳过并告警，下次重跑自动补齐。
- daily 表为 WITHOUT ROWID 表，主键 (code, date) 聚簇存储：按代码顺序扫全表
  即顺序读，选股 API 全池加载走这条路径。
"""
import os
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "stocks"
DAILY_DIR = DATA_DIR / "daily"
META_CSV = DATA_DIR / "meta.csv"
DB_PATH = BASE_DIR / "stocks.db"
TMP_PATH = BASE_DIR / "stocks.db.tmp"

SCHEMA = """
CREATE TABLE codes (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE daily (
    code   TEXT NOT NULL,
    date   TEXT NOT NULL,           -- YYYY-MM-DD
    open   REAL NOT NULL,
    close  REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    volume REAL NOT NULL,           -- 单位：股
    PRIMARY KEY (code, date)
) WITHOUT ROWID;

-- 全市场交易日历（去重后的全部交易日期，升序）
CREATE TABLE calendar (
    date TEXT PRIMARY KEY
) WITHOUT ROWID;
"""

PROGRESS_EVERY = 100  # 每处理多少个文件打印一次进度


def load_meta():
    """meta.csv -> {代码: 名称}（utf-8-sig 去 BOM）。"""
    if not META_CSV.exists():
        print(f"  警告: 缺少 {META_CSV}，名称列将退化为代码本身")
        return {}
    df = pd.read_csv(META_CSV, encoding="utf-8-sig", dtype=str)
    return {str(r[0]).strip(): str(r[1]).strip()
            for r in df.itertuples(index=False) if pd.notna(r[0])}


def read_daily(path):
    """读一个 parquet，返回 (rows, dates)：rows 为 (code,date,o,c,h,l,v) 元组列表。
    读取失败（如抓取进程正在写入）抛异常，由调用方跳过。"""
    df = pd.read_parquet(path)
    if df.empty:
        return [], []
    code = path.stem
    df = df[["date", "open", "close", "high", "low", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["close"]).drop_duplicates(subset="date", keep="last")
    df = df.sort_values("date")
    vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(float)
    rows = [(code, d, float(o), float(c), float(h), float(l), float(v))
            for d, o, c, h, l, v in zip(df["date"], df["open"], df["close"],
                                        df["high"], df["low"], vol)]
    return rows, df["date"].tolist()


def main() -> int:
    files = sorted(DAILY_DIR.glob("*.parquet"))
    if not files:
        print(f"错误: {DAILY_DIR} 下没有 parquet 文件", file=sys.stderr)
        return 1
    names = load_meta()
    print(f"股票池: meta.csv {len(names)} 只，parquet 文件 {len(files)} 个", flush=True)

    if TMP_PATH.exists():
        TMP_PATH.unlink()
    conn = sqlite3.connect(str(TMP_PATH))
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.executescript(SCHEMA)

    t0 = time.time()
    total_rows = 0
    done_files = 0
    skipped = []
    all_dates = set()
    codes_rows = []

    for i, path in enumerate(files, 1):
        try:
            rows, dates = read_daily(path)
        except Exception as e:  # noqa: BLE001
            skipped.append(f"{path.name}: {type(e).__name__} {e}")
            continue
        if not rows:
            skipped.append(f"{path.name}: 空文件")
            continue
        conn.executemany("INSERT INTO daily VALUES (?,?,?,?,?,?,?)", rows)
        total_rows += len(rows)
        done_files += 1
        all_dates.update(dates)
        code = path.stem
        codes_rows.append((code, names.get(code, code)))
        if i % PROGRESS_EVERY == 0:
            conn.commit()
            print(f"进度: {i}/{len(files)} 文件，累计 {total_rows} 行，"
                  f"耗时 {time.time() - t0:.1f}s", flush=True)

    conn.executemany("INSERT INTO codes VALUES (?,?)", codes_rows)
    conn.executemany("INSERT INTO calendar VALUES (?)",
                     [(d,) for d in sorted(all_dates)])
    conn.commit()

    # 校验：库内行数必须与读入行数一致
    db_rows = conn.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    db_codes = conn.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
    db_days = conn.execute("SELECT COUNT(*) FROM calendar").fetchone()[0]
    conn.close()

    if db_rows != total_rows or db_codes != done_files:
        print(f"错误: 校验失败（库内 {db_rows} 行/{db_codes} 只，"
              f"读入 {total_rows} 行/{done_files} 只），已保留原库", file=sys.stderr)
        TMP_PATH.unlink(missing_ok=True)
        return 1

    os.replace(TMP_PATH, DB_PATH)
    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    print(f"完成 -> {DB_PATH}（{size_mb:.1f} MB）", flush=True)
    print(f"  股票 {db_codes} 只，日线 {db_rows} 行，交易日历 {db_days} 天，"
          f"总耗时 {time.time() - t0:.1f}s", flush=True)
    if skipped:
        print(f"  跳过 {len(skipped)} 个文件（下次重跑自动补齐）:", flush=True)
        for s in skipped[:10]:
            print(f"    {s}", flush=True)
        if len(skipped) > 10:
            print(f"    … 其余 {len(skipped) - 10} 个从略", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
