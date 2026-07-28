#!/usr/bin/env python3
"""全 A 股近 5 年日线抓取（一次性冻结脚本，产出静态 parquet 进 git）。

用法：
    python fetch_stocks.py            # 全量抓取（可断点续跑，已存在的跳过）
    python fetch_stocks.py --update   # 增量更新：已存在的文件补到最后交易日之后
    python fetch_stocks.py --limit 30 # 只抓前 30 只（小批验证用）

数据源：akshare，前复权（qfq）。首选东方财富 stock_zh_a_hist；启动时探测，
若东财接口不可用则整批改用腾讯 stock_zh_a_hist_tx（注意：腾讯不覆盖北交所，
北交所股票会进 failed.txt，待东财恢复后重跑本脚本即可增量补齐）。
成交量统一为「股」（东财原始单位是手，×100 换算）。
输出：
    data/stocks/daily/<代码>.parquet  每股一文件，六列：date/open/close/high/low/volume
    data/stocks/meta.csv              代码,名称
    data/stocks/failed.txt            抓取失败的代码（重试 3 次仍失败）
"""

import argparse
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "stocks"
DAILY_DIR = DATA_DIR / "daily"
META_CSV = DATA_DIR / "meta.csv"
FAILED_TXT = DATA_DIR / "failed.txt"

KEEP_COLS = {"日期": "date", "开盘": "open", "收盘": "close",
             "最高": "high", "最低": "low", "成交量": "volume"}

RETRY = 3
LOG_EVERY = 100


def fetch_em(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """东方财富。成交量原始单位为手，×100 统一为股。无数据时返回空 df。"""
    df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                            start_date=start_date, end_date=end_date,
                            adjust="qfq")
    if df is None or df.empty:
        return pd.DataFrame(columns=list(KEEP_COLS.values()))
    df = df[list(KEEP_COLS)].rename(columns=KEEP_COLS)
    df["volume"] = (pd.to_numeric(df["volume"], errors="coerce") * 100).astype("Int64")
    return df


def fetch_tx(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """腾讯。成交量单位本来就是股。无数据时返回空 df。"""
    df = ak.stock_zh_a_hist_tx(symbol=symbol,
                               start_date=start_date, end_date=end_date,
                               adjust="qfq")
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])
    df = df[["date", "open", "close", "high", "low", "volume"]]
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").round().astype("Int64")
    return df


def probe_source(start_date: str, end_date: str):
    """启动时探测：东财可用用东财，否则整批用腾讯。"""
    try:
        if fetch_em("000001", start_date, end_date).empty:
            raise ValueError("empty dataframe")
        print("数据源: 东方财富", flush=True)
        return fetch_em
    except Exception as e:  # noqa: BLE001
        print(f"东方财富不可用（{type(e).__name__}），改用腾讯", flush=True)
        return fetch_tx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 只（0=全量）")
    ap.add_argument("--update", action="store_true",
                    help="增量更新：已存在的文件从最后交易日次日补到今日")
    args = ap.parse_args()

    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    end = datetime.now().date()
    start = end - timedelta(days=int(365 * 5) + 2)  # 多留 2 天余量
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")
    print(f"日期范围: {start_date} ~ {end_date}", flush=True)

    fetch_one = probe_source(start_date, end_date)

    pool = ak.stock_info_a_code_name()
    pool = pool.rename(columns={"code": "代码", "name": "名称"})
    if args.limit:
        pool = pool.head(args.limit)
    total = len(pool)
    print(f"股票池: {total} 只", flush=True)

    # meta.csv 始终全量写一次（即便 --limit 也写全量列表，供站点使用）
    if not args.limit:
        full_pool = ak.stock_info_a_code_name().rename(
            columns={"code": "代码", "name": "名称"})
        full_pool.to_csv(META_CSV, index=False, encoding="utf-8-sig")
        print(f"meta.csv 已写入: {len(full_pool)} 行", flush=True)

    failed_prev = set()
    if FAILED_TXT.exists():
        failed_prev = set(FAILED_TXT.read_text().split())

    done = skipped = 0
    failed: list[str] = []
    t0 = time.time()

    for i, row in enumerate(pool.itertuples(index=False), 1):
        code = str(row.代码)
        out = DAILY_DIR / f"{code}.parquet"
        fetch_start = start_date
        existing = None
        if out.exists():
            if not args.update:
                skipped += 1
                continue
            existing = pd.read_parquet(out)
            last = pd.to_datetime(existing["date"]).max().date()
            fetch_start = (last + timedelta(days=1)).strftime("%Y%m%d")
            if fetch_start > end_date:
                skipped += 1
                continue
        ok = False
        for attempt in range(1, RETRY + 1):
            try:
                df = fetch_one(code, fetch_start, end_date)
                if df.empty:
                    if existing is None:
                        raise ValueError("empty dataframe")
                    ok = True  # 增量模式：无新数据（停牌等），视为成功
                    break
                df["date"] = pd.to_datetime(df["date"]).dt.date
                if existing is not None:
                    df = (pd.concat([existing, df])
                          .drop_duplicates(subset="date", keep="last")
                          .sort_values("date").reset_index(drop=True))
                df.to_parquet(out, index=False)
                ok = True
                break
            except Exception as e:  # noqa: BLE001
                print(f"[{i}/{total}] {code} 第 {attempt} 次失败: {e}", flush=True)
                time.sleep(2 * attempt)
        if ok:
            done += 1
            failed_prev.discard(code)
        else:
            failed.append(code)
            failed_prev.add(code)
        if (done + len(failed)) % LOG_EVERY == 0:
            elapsed = time.time() - t0
            print(f"进度: 已完成 {done} / 本次需抓 {total - skipped} "
                  f"(总池 {total}, 跳过已存在 {skipped}, 失败 {len(failed)}), "
                  f"耗时 {elapsed/60:.1f} 分钟", flush=True)
        time.sleep(random.uniform(0.3, 0.5))

    FAILED_TXT.write_text("\n".join(sorted(failed_prev)) + ("\n" if failed_prev else ""))
    print(f"结束: 新抓 {done}, 跳过 {skipped}, 失败 {len(failed)} "
          f"(累计未成功 {len(failed_prev)}, 见 {FAILED_TXT})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
