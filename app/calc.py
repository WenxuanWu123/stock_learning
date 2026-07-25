# -*- coding: utf-8 -*-
"""calc 占位符注入引擎。

课文 / 题目 / 关卡 JSON 中的 `{{calc:函数(参数...)|精度}}` 在 seed 时
由本模块从行情表计算并替换为真实数字。语法详见 项目.md「calc 占位符语法」。
"""
import re

from .market import get_series, SYMBOL_NAMES

PLACEHOLDER_RE = re.compile(r"\{\{calc:([^}|]+)(?:\|(\d+))?\}\}")


def _s(conn, args, i=0):
    return get_series(conn, args[i].strip())


def _f2(v, digits):
    return f"{v:.{digits}f}"


# ── 各函数实现：参数为去掉括号后的逗号分隔列表 ──

def fn_close(conn, args, d):
    s = _s(conn, args)
    return _f2(s.close[s.idx_on_or_before(args[1].strip())], d)


def fn_open(conn, args, d):
    s = _s(conn, args)
    return _f2(s.open[s.idx_on_or_before(args[1].strip())], d)


def fn_high(conn, args, d):
    s = _s(conn, args)
    return _f2(s.high[s.idx_on_or_before(args[1].strip())], d)


def fn_low(conn, args, d):
    s = _s(conn, args)
    return _f2(s.low[s.idx_on_or_before(args[1].strip())], d)


def fn_volume(conn, args, d):
    s = _s(conn, args)
    return str(int(s.volume[s.idx_on_or_before(args[1].strip())]))


def fn_trade_date(conn, args, d):
    """对齐交易日：返回 date（含）之前最近一个交易日。"""
    return _s(conn, args).trade_date(args[1].strip())


def fn_chg_pct(conn, args, d):
    """区间涨跌幅 %：chg_pct(symbol, start, end)，两端各取最近交易日收盘。"""
    s = _s(conn, args)
    c0 = s.close[s.idx_on_or_before(args[1].strip())]
    c1 = s.close[s.idx_on_or_before(args[2].strip())]
    return _f2((c1 / c0 - 1) * 100, d)


def fn_ma(conn, args, d):
    """N 日均线：ma(symbol, N, date)"""
    return _f2(_s(conn, args).value(("ma", int(args[1])), args[2].strip()), d)


def fn_rsi(conn, args, d):
    """N 日 RSI（通达信口径）：rsi(symbol, N, date)"""
    return _f2(_s(conn, args).value(("rsi", int(args[1])), args[2].strip()), d)


def fn_bias(conn, args, d):
    """N 日乖离率 %：bias(symbol, N, date)"""
    return _f2(_s(conn, args).value(("bias", int(args[1])), args[2].strip()), d)


def fn_macd(conn, args, d):
    """MACD(12,26,9)：macd(symbol, date) -> "DIF=.., DEA=.., MACD=..""" 
    s = _s(conn, args)
    dif, dea, bar = s.series(("macd",))
    i = s.idx_on_or_before(args[1].strip())
    return f"DIF={_f2(dif[i], d)}，DEA={_f2(dea[i], d)}，MACD={_f2(bar[i], d)}"


def fn_kdj(conn, args, d):
    """KDJ(9,3,3)：kdj(symbol, date) -> "K=.., D=.., J=.."""
    s = _s(conn, args)
    kk, dd, jj = s.series(("kdj",))
    i = s.idx_on_or_before(args[1].strip())
    if kk[i] is None:
        raise ValueError(f"{s.symbol} 在 {s.dates[i]} 处 KDJ 数据不足")
    return f"K={_f2(kk[i], d)}，D={_f2(dd[i], d)}，J={_f2(jj[i], d)}"


def fn_max_high(conn, args, d):
    """区间最高价：max_high(symbol, start, end)"""
    s = _s(conn, args)
    i0, i1 = s.idx_on_or_before(args[1].strip()), s.idx_on_or_before(args[2].strip())
    return _f2(max(s.high[i0:i1 + 1]), d)


def fn_min_low(conn, args, d):
    """区间最低价：min_low(symbol, start, end)"""
    s = _s(conn, args)
    i0, i1 = s.idx_on_or_before(args[1].strip()), s.idx_on_or_before(args[2].strip())
    return _f2(min(s.low[i0:i1 + 1]), d)


def fn_symbol_name(conn, args, d):
    return SYMBOL_NAMES.get(args[0].strip(), args[0].strip())


FUNCS = {
    "close": fn_close, "open": fn_open, "high": fn_high, "low": fn_low,
    "volume": fn_volume, "trade_date": fn_trade_date, "chg_pct": fn_chg_pct,
    "ma": fn_ma, "rsi": fn_rsi, "bias": fn_bias, "macd": fn_macd,
    "kdj": fn_kdj, "max_high": fn_max_high, "min_low": fn_min_low,
    "symbol_name": fn_symbol_name,
}

CALL_RE = re.compile(r"^(\w+)\((.*)\)$")


def eval_placeholder(conn, expr, digits=2):
    m = CALL_RE.match(expr.strip())
    if not m:
        raise ValueError(f"calc 占位符语法错误: {expr!r}（应为 函数(参数...)）")
    name, argstr = m.group(1), m.group(2)
    if name not in FUNCS:
        raise ValueError(f"未知 calc 函数: {name}（可用: {', '.join(sorted(FUNCS))}）")
    args = [a.strip() for a in argstr.split(",") if a.strip()]
    return FUNCS[name](conn, args, digits)


def inject(conn, text):
    """替换 text 中全部 calc 占位符，返回 (新文本, 替换日志行列表)。"""
    log = []

    def repl(m):
        expr, digits = m.group(1), m.group(2)
        d = int(digits) if digits else 2
        val = eval_placeholder(conn, expr, d)
        log.append(f"{{{{calc:{expr}|{d}}}}} => {val}")
        return val

    return PLACEHOLDER_RE.sub(repl, text), log
