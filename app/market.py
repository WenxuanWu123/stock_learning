# -*- coding: utf-8 -*-
"""行情数据访问层：从 SQLite 读取序列，按需计算指标并缓存。"""
from bisect import bisect_right

from . import indicators as ind

# symbol -> 中文名（供展示）
SYMBOL_NAMES = {
    "sh000001": "上证指数",
    "sh000300": "沪深300",
    "sh000905": "中证500",
}


class MarketSeries:
    """单标的完整日线序列 + 懒计算指标序列。"""

    def __init__(self, symbol, rows):
        self.symbol = symbol
        self.dates = [r["date"] for r in rows]
        self.open = [r["open"] for r in rows]
        self.high = [r["high"] for r in rows]
        self.low = [r["low"] for r in rows]
        self.close = [r["close"] for r in rows]
        self.volume = [r["volume"] for r in rows]
        self._cache = {}

    def idx_on_or_before(self, date):
        """date（含）之前最近一个交易日的下标；没有则抛错。"""
        i = bisect_right(self.dates, date) - 1
        if i < 0:
            raise ValueError(f"{self.symbol} 在 {date} 或之前没有行情数据")
        return i

    def trade_date(self, date):
        return self.dates[self.idx_on_or_before(date)]

    def series(self, key):
        """懒计算指标序列。key 例: ('ma',20) ('rsi',6) ('bias',20)"""
        if key in self._cache:
            return self._cache[key]
        kind = key[0]
        if kind == "ma":
            s = ind.ma(self.close, key[1])
        elif kind == "rsi":
            s = ind.rsi(self.close, key[1])
        elif kind == "bias":
            s = ind.bias(self.close, key[1])
        elif kind == "macd":
            s = ind.macd(self.close)  # (dif, dea, bar)
        elif kind == "kdj":
            s = ind.kdj(self.high, self.low, self.close)
        elif kind == "std":
            s = ind.rolling_std(self.close, key[1])
        elif kind == "hmax":
            s = ind.rolling_max(self.high, key[1])
        elif kind == "vmean":
            s = ind.rolling_mean(self.volume, key[1])
        elif kind == "vmin":
            s = ind.rolling_min(self.volume, key[1])
        elif kind == "lmin":
            s = ind.rolling_min(self.low, key[1])
        else:
            raise ValueError(f"未知指标序列: {key}")
        self._cache[key] = s
        return s

    def value(self, key, date):
        i = self.idx_on_or_before(date)
        v = self.series(key)[i]
        if v is None:
            raise ValueError(f"{self.symbol} 在 {self.dates[i]} 处 {key} 数据不足")
        return v


_cache = {}


def get_series(conn, symbol):
    if symbol not in _cache:
        rows = conn.execute(
            "SELECT * FROM market_data WHERE symbol=? ORDER BY date", (symbol,)
        ).fetchall()
        if not rows:
            raise ValueError(f"行情表中没有标的 {symbol}")
        _cache[symbol] = MarketSeries(symbol, rows)
    return _cache[symbol]


def clear_cache():
    _cache.clear()
