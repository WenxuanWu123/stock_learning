# -*- coding: utf-8 -*-
"""选股实验场：条件组合筛选 + 历史批量回测统计。

数据流：data/stocks/daily/*.parquet → scripts/build_stocks_db.py → stocks.db → 本模块。
指标口径与 app/indicators.py 一致：MA 为简单移动平均；RSI 直接调用
indicators.rsi（通达信 SMA 递推）。停牌/无成交日自然跳过（按个股自身日线逐日
精确匹配，当日无行者不命中）。

教学核心：history 模式把条件组合在基准日之前 N 个交易日的每一天各跑一遍，
汇总全部命中（按股·日计）的 forward 收益分布，并与同期全市场基准对比——
用数据打破"选股公式圣杯"幻觉。

性能：全池日线一次性载入内存（stocks.db mtime 变化时自动重载）；条件掩码全部
numpy 向量化；RSI 递推最贵，排在最后且只在便宜条件仍有候选时计算。
上限保护：forward_days ≤ 120、history_days ≤ 250、条件 ≤ 8 条、命中展示 ≤ 200 条。
"""
import os
import re
import sqlite3
from bisect import bisect_right

import numpy as np
import pandas as pd
from fastapi import HTTPException
from pydantic import BaseModel, Field

from . import indicators as ind
from .db import BASE_DIR

DB_PATH = BASE_DIR / "stocks.db"
HIT_LIMIT = 200          # 命中列表展示上限
MAX_CONDITIONS = 8
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ConditionIn(BaseModel):
    type: str
    params: dict = Field(default_factory=dict)


class ScreenerIn(BaseModel):
    as_of: str | None = None          # 筛选基准日，默认最新交易日
    conditions: list[ConditionIn]
    forward_days: int = 20            # 后续表现观察窗口（交易日）
    mode: str = "single"              # single=单次筛选 / history=历史批量统计
    history_days: int = 250           # history 模式回溯交易日数


# ── 数据池：stocks.db 全量载入内存，按 mtime 失效 ──

class StockPool:
    def __init__(self):
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            self.names = dict(conn.execute("SELECT code, name FROM codes"))
            cal = [r[0] for r in conn.execute("SELECT date FROM calendar ORDER BY date")]
            df = pd.read_sql_query(
                "SELECT code, date, close, high, low, volume FROM daily"
                " ORDER BY code, date", conn)
        finally:
            conn.close()
        self.calendar = np.array(cal)
        self.latest = cal[-1] if cal else None
        codes = df["code"].to_numpy()
        dates = df["date"].to_numpy()
        cols = {k: df[k].to_numpy(dtype=np.float64)
                for k in ("close", "high", "low", "volume")}
        starts = np.flatnonzero(np.concatenate(([True], codes[1:] != codes[:-1])))
        self.codes = []
        self.stocks = {}
        for k, s in enumerate(starts):
            e = starts[k + 1] if k + 1 < len(starts) else len(df)
            code = str(codes[s])
            self.codes.append(code)
            self.stocks[code] = {
                "dates": dates[s:e],
                **{k: v[s:e] for k, v in cols.items()},
            }


_cache = {"mtime": None, "pool": None}


def get_pool():
    if not DB_PATH.exists():
        raise HTTPException(
            503, "个股库未构建：请先运行 .venv/bin/python scripts/build_stocks_db.py")
    mt = os.path.getmtime(DB_PATH)
    if _cache["mtime"] != mt:
        _cache["pool"] = StockPool()
        _cache["mtime"] = mt
    return _cache["pool"]


# ── 向量化指标（口径同 app/indicators.py）──

def _rmean(x, n):
    """简单移动平均（同 indicators.ma），前 n-1 项为 NaN。"""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.cumsum(np.concatenate(([0.0], x)))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def _rmax(x, n):
    """滚动最高（同 indicators.rolling_max），前 n-1 项为 NaN。"""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = np.lib.stride_tricks.sliding_window_view(x, n).max(axis=1)
    return out


def _rsi(close, n):
    """通达信 RSI：直接调用 indicators.rsi，None 转 NaN。"""
    s = ind.rsi(list(close), n)
    return np.array([np.nan if v is None else v for v in s], dtype=np.float64)


# ── 条件校验：非法参数抛 400（中文原因）──

def _num(p, key, default, lo, hi, label, integer=False):
    raw = p.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise HTTPException(400, f"{label}：参数 {key}={raw!r} 必须是数字")
    v = float(raw)
    if integer:
        if v != int(v):
            raise HTTPException(400, f"{label}：参数 {key}={raw!r} 必须是整数")
        v = int(v)
    if not lo <= v <= hi:
        raise HTTPException(400, f"{label}：参数 {key}={raw:g} 超出范围 {lo}~{hi}")
    return v


def validate_condition(c):
    """校验并规范化一个条件，返回 {type, params, label}。"""
    t, p = c.type, c.params or {}
    if t == "ma_bull":
        label0 = "均线多头"
        periods = p.get("periods", [5, 20, 60])
        if (not isinstance(periods, list) or not 2 <= len(periods) <= 4
                or any(isinstance(x, bool) or not isinstance(x, int) for x in periods)):
            raise HTTPException(400, f"{label0}：periods 必须是 2~4 个整数，如 [5,20,60]")
        if any(not 2 <= x <= 250 for x in periods):
            raise HTTPException(400, f"{label0}：均线周期须在 2~250 之间")
        if list(periods) != sorted(set(periods)):
            raise HTTPException(400, f"{label0}：periods 必须严格递增，如 [5,20,60]")
        return {"type": t, "params": {"periods": list(periods)},
                "label": f"均线多头{'/'.join(map(str, periods))}"}
    if t == "rsi_max":
        label0 = "RSI 超卖"
        n = _num(p, "n", 6, 2, 120, label0, integer=True)
        mx = _num(p, "max", 20, 1, 100, label0)
        return {"type": t, "params": {"n": n, "max": mx}, "label": f"RSI{n}≤{mx:g}"}
    if t == "bias_max":
        label0 = "乖离率"
        n = _num(p, "n", 20, 2, 120, label0, integer=True)
        mx = _num(p, "max", -5, -100, 100, label0)
        return {"type": t, "params": {"n": n, "max": mx}, "label": f"BIAS{n}≤{mx:g}%"}
    if t == "drawdown_min":
        label0 = "高点回撤"
        n = _num(p, "n", 60, 2, 250, label0, integer=True)
        mn = _num(p, "min", 20, 0, 100, label0)
        return {"type": t, "params": {"n": n, "min": mn}, "label": f"{n}日回撤≥{mn:g}%"}
    if t == "vol_ratio":
        label0 = "量比"
        n = _num(p, "n", 5, 2, 120, label0, integer=True)
        mn = _num(p, "min", 2, 0.1, 100, label0)
        return {"type": t, "params": {"n": n, "min": mn}, "label": f"{n}日量比≥{mn:g}"}
    if t == "chg_range":
        label0 = "区间涨跌幅"
        n = _num(p, "n", 20, 1, 250, label0, integer=True)
        mn = _num(p, "min", -10, -100, 100, label0)
        mx = _num(p, "max", 5, -100, 100, label0)
        if mn >= mx:
            raise HTTPException(400, f"{label0}：min 必须小于 max")
        return {"type": t, "params": {"n": n, "min": mn, "max": mx},
                "label": f"{n}日涨幅{mn:g}~{mx:g}%"}
    raise HTTPException(400, f"未知条件类型 {t!r}（可选：ma_bull / rsi_max / bias_max /"
                             " drawdown_min / vol_ratio / chg_range）")


# ── 条件求值 ──

def eval_code(st, conds, fwd_days):
    """对一只股票计算条件命中掩码与各条件取值函数。

    返回 (mask, val_fns, fwd)：
    - mask：布尔数组（长度=该股日线数），True 表示该日命中全部条件
    - val_fns：[(label, f(i)->str)]，命中行展示"各条件实际值"用
    - fwd：forward 收益 % 数组（close[i+fwd_days]/close[i]-1，不足为 NaN）
    便宜条件先算并短路与；RSI 递推最贵，最后算且只在仍有候选时计算。
    """
    c, h, v = st["close"], st["high"], st["volume"]
    n_rows = len(c)
    mask = np.ones(n_rows, dtype=bool)
    val_fns = []
    rsi_conds = []
    for cond in conds:
        t, p = cond["type"], cond["params"]
        if t == "rsi_max":
            rsi_conds.append(cond)
            continue
        if t == "ma_bull":
            mas = [_rmean(c, per) for per in p["periods"]]
            prev = c
            for m in mas:
                mask &= ~np.isnan(m) & (prev > m)
                prev = m
            val_fns.append((cond["label"], lambda i, c=c, mas=mas:
                            " / ".join([f"{c[i]:.2f}"] + [f"{m[i]:.2f}" for m in mas])))
        elif t == "bias_max":
            m = _rmean(c, p["n"])
            b = (c - m) / m * 100
            mask &= ~np.isnan(b) & (b <= p["max"])
            val_fns.append((cond["label"], lambda i, b=b: f"{b[i]:.2f}"))
        elif t == "drawdown_min":
            dd = (c / _rmax(h, p["n"]) - 1) * 100
            mask &= ~np.isnan(dd) & (dd <= -p["min"])
            val_fns.append((cond["label"], lambda i, dd=dd: f"{dd[i]:.2f}"))
        elif t == "vol_ratio":
            vr = v / _rmean(v, p["n"])   # 量比：当日量 / n日均量（均量含当日，同通达信 V/MA(V,n)）
            mask &= np.isfinite(vr) & (vr >= p["min"])
            val_fns.append((cond["label"], lambda i, vr=vr: f"{vr[i]:.2f}"))
        elif t == "chg_range":
            n = p["n"]
            chg = np.full(n_rows, np.nan)
            if n_rows > n:
                chg[n:] = (c[n:] / c[:-n] - 1) * 100
            mask &= ~np.isnan(chg) & (chg >= p["min"]) & (chg <= p["max"])
            val_fns.append((cond["label"], lambda i, chg=chg: f"{chg[i]:.2f}"))
    for cond in rsi_conds:
        if not mask.any():
            break
        p = cond["params"]
        r = _rsi(c, p["n"])
        mask &= ~np.isnan(r) & (r <= p["max"])
        val_fns.append((cond["label"], lambda i, r=r: f"{r[i]:.1f}"))
    fwd = np.full(n_rows, np.nan)
    if n_rows > fwd_days:
        fwd[:-fwd_days] = (c[fwd_days:] / c[:-fwd_days] - 1) * 100
    return mask, val_fns, fwd


def _stats(rets):
    """forward 收益数组的聚合统计；空数组返回 count=0。"""
    rets = np.asarray(rets, dtype=np.float64)
    n = len(rets)
    if n == 0:
        return {"count": 0, "win_rate": None, "avg": None, "median": None,
                "best": None, "worst": None}
    return {"count": n,
            "win_rate": round(float((rets > 0).mean() * 100), 1),
            "avg": round(float(rets.mean()), 2),
            "median": round(float(np.median(rets)), 2),
            "best": round(float(rets.max()), 2),
            "worst": round(float(rets.min()), 2)}


def _hit_row(pool, st, code, i, date, val_fns, fwd, fwd_days):
    rv = fwd[i]
    ok = not np.isnan(rv)
    return {
        "code": code, "name": pool.names.get(code, code), "date": str(date),
        "close": round(float(st["close"][i]), 2),
        "values": {label: fn(i) for label, fn in val_fns},
        "forward_return": round(float(rv), 2) if ok else None,
        "forward_date": str(st["dates"][i + fwd_days]) if ok else None,
    }


# ── 主流程 ──

def run(body: ScreenerIn):
    mode = body.mode or "single"
    if mode not in ("single", "history"):
        raise HTTPException(400, f"mode 只能是 single / history，收到 {body.mode!r}")
    f = body.forward_days
    if isinstance(f, bool) or not isinstance(f, int) or not 1 <= f <= 120:
        raise HTTPException(400, f"forward_days={f!r} 必须是 1~120 的整数")
    hd = body.history_days
    if isinstance(hd, bool) or not isinstance(hd, int) or not 10 <= hd <= 250:
        raise HTTPException(400, f"history_days={hd!r} 必须是 10~250 的整数")
    if not 1 <= len(body.conditions) <= MAX_CONDITIONS:
        raise HTTPException(400, f"conditions 至少 1 条、至多 {MAX_CONDITIONS} 条")
    conds = [validate_condition(c) for c in body.conditions]

    pool = get_pool()
    cal = list(pool.calendar)
    if not cal:
        raise HTTPException(503, "个股库为空，请重跑 scripts/build_stocks_db.py")
    as_of = body.as_of or pool.latest
    if not DATE_RE.match(as_of):
        raise HTTPException(400, f"as_of 格式应为 YYYY-MM-DD，收到 {as_of!r}")
    i_end = bisect_right(cal, as_of) - 1   # 非交易日对齐到之前最近交易日
    if i_end < 0:
        raise HTTPException(400, f"基准日 {as_of} 早于数据起点 {cal[0]}")
    as_of = cal[i_end]

    conds_echo = [{"type": c["type"], "params": c["params"], "label": c["label"]}
                  for c in conds]
    base = {"mode": mode, "as_of": as_of, "forward_days": f,
            "pool_size": len(pool.codes), "conditions": conds_echo}

    if mode == "single":
        return _run_single(pool, conds, as_of, f, base)
    return _run_history(pool, conds, cal, i_end, hd, f, base)


def _run_single(pool, conds, as_of, f, base):
    """单次筛选：全池扫基准日当日。"""
    hits, hit_rets, base_rets = [], [], []
    pending = 0
    for code in pool.codes:
        st = pool.stocks[code]
        dates = st["dates"]
        i = int(np.searchsorted(dates, as_of))
        if i >= len(dates) or dates[i] != as_of:
            continue  # 当日停牌/无数据，跳过
        mask, val_fns, fwd = eval_code(st, conds, f)
        if not np.isnan(fwd[i]):
            base_rets.append(fwd[i])   # 基准：当日有交易的全池股票
        if not mask[i]:
            continue
        if np.isnan(fwd[i]):
            pending += 1               # 后续行情未冻结满 forward_days，暂无法统计
        else:
            hit_rets.append(fwd[i])
        if len(hits) < HIT_LIMIT:
            hits.append(_hit_row(pool, st, code, i, as_of, val_fns, fwd, f))
    return {**base,
            "hit_count": len(hit_rets) + pending, "shown": len(hits), "hits": hits,
            "stats": {**_stats(hit_rets), "pending": pending},
            "baseline": _stats(base_rets)}


def _run_history(pool, conds, cal, i_end, hd, f, base):
    """历史批量统计：条件在基准日之前 hd 个交易日的每一天各跑一遍。"""
    i_start = max(0, i_end - hd + 1)
    d0, d1 = cal[i_start], cal[i_end]
    total_hits = pending = 0
    hit_dates = set()
    all_rets, base_rets = [], []
    sample = []        # 最近 HIT_LIMIT 条命中样本
    threshold = ""     # sample 满员后只收更新的日期
    for code in pool.codes:
        st = pool.stocks[code]
        dates = st["dates"]
        lo = int(np.searchsorted(dates, d0))
        hi = int(np.searchsorted(dates, d1, side="right"))
        if lo >= hi:
            continue
        mask, val_fns, fwd = eval_code(st, conds, f)
        b = fwd[lo:hi]
        base_rets.append(b[~np.isnan(b)])   # 基准：窗口内全部股·日
        idxs = np.flatnonzero(mask[lo:hi]) + lo
        if len(idxs) == 0:
            continue
        total_hits += len(idxs)
        rets = fwd[idxs]
        ok = ~np.isnan(rets)
        all_rets.append(rets[ok])
        pending += int((~ok).sum())
        hit_dates.update(dates[idxs].tolist())
        for i in idxs:
            d = dates[i]
            if d < threshold:
                continue
            sample.append((str(d), _hit_row(pool, st, code, i, d, val_fns, fwd, f)))
            if len(sample) > HIT_LIMIT * 2:
                sample.sort(key=lambda t: t[0], reverse=True)
                del sample[HIT_LIMIT:]
                threshold = sample[-1][0]
    sample.sort(key=lambda t: t[0], reverse=True)
    hits = [row for _, row in sample[:HIT_LIMIT]]
    rets = np.concatenate(all_rets) if all_rets else np.empty(0)
    brets = np.concatenate(base_rets) if base_rets else np.empty(0)
    hist_counts, _ = np.histogram(
        rets, bins=[-np.inf, -10, -5, 0, 5, 10, np.inf])
    return {**base,
            "history": {
                "from": d0, "to": d1, "days": i_end - i_start + 1,
                "hit_count": total_hits, "hit_days": len(hit_dates),
                "pending": pending,
                "stats": _stats(rets),
                "baseline": _stats(brets),
                "histogram": {
                    "buckets": ["≤-10%", "-10~-5%", "-5~0%", "0~5%", "5~10%", ">10%"],
                    "counts": [int(x) for x in hist_counts],
                },
            },
            "shown": len(hits), "hits": hits}
