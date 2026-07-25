# -*- coding: utf-8 -*-
"""技术指标计算（纯 Python，无第三方依赖）。

口径说明：
- RSI / KDJ 的平滑使用通达信 SMA(X,N,M) 递归：Y = (X*M + Y'*(N-M)) / N
- MACD 使用标准 EMA(12/26/9)，MACD 柱 = 2*(DIF-DEA)（通达信口径）
- 均线为简单移动平均
所有函数输入为按日期升序的 list[float]，输出为等长 list（前段不足期为 None）。
"""


def sma_tdx(x, n, m=1):
    """通达信 SMA(X,N,M) 递归平滑。"""
    out = []
    prev = None
    for v in x:
        if v is None:
            out.append(prev)
            continue
        prev = v if prev is None else (v * m + prev * (n - m)) / n
        out.append(prev)
    return out


def ema(x, n):
    """标准 EMA: alpha = 2/(n+1)，递推（adjust=False）。"""
    alpha = 2.0 / (n + 1)
    out = []
    prev = None
    for v in x:
        if v is None:
            out.append(prev)
            continue
        prev = v if prev is None else v * alpha + prev * (1 - alpha)
        out.append(prev)
    return out


def rolling_mean(x, n):
    out = []
    for i in range(len(x)):
        if i + 1 < n:
            out.append(None)
        else:
            out.append(sum(x[i + 1 - n:i + 1]) / n)
    return out


def rolling_std(x, n):
    """样本标准差（ddof=1，通达信 STD 口径）。"""
    out = []
    for i in range(len(x)):
        if i + 1 < n:
            out.append(None)
        else:
            w = x[i + 1 - n:i + 1]
            mu = sum(w) / n
            out.append((sum((v - mu) ** 2 for v in w) / (n - 1)) ** 0.5)
    return out


def rolling_max(x, n):
    return [None if i + 1 < n else max(x[i + 1 - n:i + 1]) for i in range(len(x))]


def rolling_min(x, n):
    return [None if i + 1 < n else min(x[i + 1 - n:i + 1]) for i in range(len(x))]


def rsi(closes, n):
    """通达信 RSI(N) = SMA(MAX(C-LC,0),N,1)/SMA(ABS(C-LC),N,1)*100。"""
    up, dn = [0.0], [0.0]
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        up.append(max(diff, 0.0))
        dn.append(abs(diff))
    a = sma_tdx(up, n, 1)
    b = sma_tdx(dn, n, 1)
    return [None if (bv is None or bv == 0) else av / bv * 100 for av, bv in zip(a, b)]


def ma(closes, n):
    return rolling_mean(closes, n)


def bias(closes, n):
    """乖离率 BIAS(N) = (C - MA(N)) / MA(N) * 100。"""
    m = rolling_mean(closes, n)
    return [None if mv is None else (c - mv) / mv * 100 for c, mv in zip(closes, m)]


def macd(closes, fast=12, slow=26, signal=9):
    """返回 (DIF, DEA, MACD柱) 三条序列，MACD柱 = 2*(DIF-DEA)。"""
    ef = ema(closes, fast)
    es = ema(closes, slow)
    dif = [a - b for a, b in zip(ef, es)]
    dea = ema(dif, signal)
    bar = [2 * (d - e) for d, e in zip(dif, dea)]
    return dif, dea, bar


def kdj(highs, lows, closes, n=9, k_n=3, d_n=3):
    """通达信 KDJ(9,3,3)，K/D 初值 50。返回 (K, D, J)。"""
    hh = rolling_max(highs, n)
    ll = rolling_min(lows, n)
    rsv = []
    for i in range(len(closes)):
        if hh[i] is None or hh[i] == ll[i]:
            rsv.append(50.0 if hh[i] is not None else None)
        else:
            rsv.append((closes[i] - ll[i]) / (hh[i] - ll[i]) * 100)
    # TDX KDJ 的 K、D 以 50 起步
    k_vals, d_vals, j_vals = [], [], []
    k = d = 50.0
    for r in rsv:
        if r is None:
            k_vals.append(None); d_vals.append(None); j_vals.append(None)
            continue
        k = (r + k * (k_n - 1)) / k_n
        d = (k + d * (d_n - 1)) / d_n
        k_vals.append(k); d_vals.append(d); j_vals.append(3 * k - 2 * d)
    return k_vals, d_vals, j_vals
