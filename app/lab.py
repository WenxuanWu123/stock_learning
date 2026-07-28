# -*- coding: utf-8 -*-
"""指标实验场：按用户参数取最近 N 日蜡烛并计算指标序列。

口径说明：所有指标都在完整历史序列上计算后再截取末尾 N 日（EMA/SMA 递归类
指标需要足够长的预热期），保证返回值与全历史口径一致；输出序列与蜡烛按日期
一一对齐（前段不足期为 None）。
"""
from fastapi import HTTPException

from . import indicators as ind
from .market import get_series, SYMBOL_NAMES

DAYS_LO, DAYS_HI = 30, 500
INDICATORS = ("macd", "kdj", "rsi", "bias")


def _parse_int(params, name, default, lo, hi, allow_zero=False):
    """解析整型查询参数：缺失用默认值，越界/非整数抛 400。allow_zero 时 0 表示关闭。"""
    raw = params.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(400, f"参数 {name}={raw!r} 不是整数")
    if v == 0 and allow_zero:
        return v
    if not lo <= v <= hi:
        raise HTTPException(400, f"参数 {name}={v} 超出范围 {lo}~{hi}")
    return v


def lab_data(conn, params):
    symbol = params.get("symbol") or "sh000001"
    if symbol not in SYMBOL_NAMES:
        raise HTTPException(
            400, f"未知标的 {symbol}（可选：{'/'.join(SYMBOL_NAMES)}）")
    days = _parse_int(params, "days", 250, DAYS_LO, DAYS_HI)
    ma1 = _parse_int(params, "ma1", 5, 2, 250)
    ma2 = _parse_int(params, "ma2", 20, 2, 250)
    kind = params.get("indicator") or "macd"
    if kind not in INDICATORS:
        raise HTTPException(
            400, f"未知副图指标 {kind}（可选：{'/'.join(INDICATORS)}）")

    s = get_series(conn, symbol)
    n = min(days, len(s.dates))
    candles = [
        {"date": s.dates[i], "open": s.open[i], "high": s.high[i],
         "low": s.low[i], "close": s.close[i], "volume": s.volume[i]}
        for i in range(len(s.dates) - n, len(s.dates))
    ]

    ma = {
        "ma1": {"n": ma1, "values": ind.ma(s.close, ma1)[-n:]},
        "ma2": {"n": ma2, "values": ind.ma(s.close, ma2)[-n:]},
    }

    if kind == "macd":
        fast = _parse_int(params, "fast", 12, 2, 60)
        slow = _parse_int(params, "slow", 26, 3, 120)
        signal = _parse_int(params, "signal", 9, 2, 60)
        if fast >= slow:
            raise HTTPException(400, "MACD 快线 fast 必须小于慢线 slow")
        dif, dea, bar = ind.macd(s.close, fast, slow, signal)
        indicator = {
            "kind": kind,
            "params": {"fast": fast, "slow": slow, "signal": signal},
            "series": {"dif": dif[-n:], "dea": dea[-n:], "bar": bar[-n:]},
        }
    elif kind == "kdj":
        kn = _parse_int(params, "n", 9, 2, 60)
        m1 = _parse_int(params, "m1", 3, 2, 30)
        m2 = _parse_int(params, "m2", 3, 2, 30)
        k, d, j = ind.kdj(s.high, s.low, s.close, kn, m1, m2)
        indicator = {
            "kind": kind,
            "params": {"n": kn, "m1": m1, "m2": m2},
            "series": {"k": k[-n:], "d": d[-n:], "j": j[-n:]},
        }
    elif kind == "rsi":
        r1 = _parse_int(params, "rsi1", 6, 2, 120)
        r2 = _parse_int(params, "rsi2", 12, 2, 120)
        r3 = _parse_int(params, "rsi3", 24, 2, 120, allow_zero=True)
        series = {"rsi1": ind.rsi(s.close, r1)[-n:],
                  "rsi2": ind.rsi(s.close, r2)[-n:]}
        if r3:
            series["rsi3"] = ind.rsi(s.close, r3)[-n:]
        indicator = {
            "kind": kind,
            "params": {"rsi1": r1, "rsi2": r2, "rsi3": r3},
            "series": series,
        }
    else:  # bias
        bn = _parse_int(params, "bias_n", 20, 2, 120)
        indicator = {
            "kind": kind,
            "params": {"n": bn},
            "series": {"bias": ind.bias(s.close, bn)[-n:]},
        }

    return {
        "symbol": symbol, "symbol_name": SYMBOL_NAMES[symbol], "days": n,
        "candles": candles, "ma": ma, "indicator": indicator,
    }
