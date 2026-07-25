# -*- coding: utf-8 -*-
"""V5「超跌反弹」信号计算（买Q 快反轨 + 六项打分）。

严格参照 cdv5_backtest.py 与《上证综指超跌反弹V5_r4 指标公式与使用手册》：
- 买Q 触发（警Q）：RSI2<=10 且 常规区(0.90<=C/MA250<=1.08)
  且 MA60>=MA250*0.97 且 5日累计涨幅>=-8%（不接瀑布）
- 买Q 确认：触发后 3 个交易日内，收盘价站上触发日最高价
- 六项打分（满分100）：RSI6 / BIAS20 / 布林%B / 60日回撤 / 恐慌形态 / 下影收复
"""
from . import indicators as ind

# V5 定型参数（与手册一致）
BAND_LO, BAND_HI = 0.90, 1.08
RSI2_TH = 10
Q_MIDTREND = 0.97
Q_NOWATERFALL = -8.0
Q_CONF_WIN = 3
PANIC_DROP, PANIC_RECLAIM, PANIC_VRT = -3.0, 0.5, 1.2


def _prepare(s):
    """对 MarketSeries 预计算 V5 所需全部序列，挂到 s._v5 上。"""
    if getattr(s, "_v5", None):
        return s._v5
    c, h, l, v = s.close, s.high, s.low, s.volume
    n = len(c)
    rsi2 = s.series(("rsi", 2))
    rsi6 = s.series(("rsi", 6))
    ma20 = s.series(("ma", 20))
    ma60 = s.series(("ma", 60))
    ma250 = s.series(("ma", 250))
    s20 = s.series(("std", 20))
    hmax60 = s.series(("hmax", 60))
    vmean20 = s.series(("vmean", 20))
    d = {
        "rsi2": rsi2, "rsi6": rsi6, "ma20": ma20, "ma60": ma60, "ma250": ma250,
        "bias20": [None if m is None else (cc - m) / m * 100 for cc, m in zip(c, ma20)],
        "pctb": [None if (m is None or sd is None or sd == 0) else (cc - (m - 2 * sd)) / (4 * sd)
                 for cc, m, sd in zip(c, ma20, s20)],
        "dd60": [None if hh is None else (cc / hh - 1) * 100 for cc, hh in zip(c, hmax60)],
        "vrt": [None if vm is None or vm == 0 else vv / vm for vv, vm in zip(v, vmean20)],
        "idrop": [None] + [(l[i] / c[i - 1] - 1) * 100 for i in range(1, n)],
        "reclaim": [(c[i] - l[i]) / (h[i] - l[i]) if h[i] > l[i] else 1.0 for i in range(n)],
        "ratio250": [None if m is None else cc / m for cc, m in zip(c, ma250)],
        "chg5": [None if i < 5 else (c[i] / c[i - 5] - 1) * 100 for i in range(n)],
    }
    s._v5 = d
    return d


def score_components(s, i):
    """第 i 根 K 线的六项打分明细。返回 (总分, [六项 dict])。数据不足返回 (0, [])。"""
    d = _prepare(s)
    if d["rsi6"][i] is None or d["bias20"][i] is None or d["pctb"][i] is None \
            or d["dd60"][i] is None or d["vrt"][i] is None:
        return 0, []
    r, b, p, dd = d["rsi6"][i], d["bias20"][i], d["pctb"][i], d["dd60"][i]
    vrt, idr, rc = d["vrt"][i], d["idrop"][i], d["reclaim"][i]
    panic = idr <= PANIC_DROP and rc >= PANIC_RECLAIM and vrt >= PANIC_VRT

    def pick(v, table):
        for th, pts in table:
            if v < th:
                return pts
        return 0

    s_rsi = pick(r, [(20, 15), (25, 12), (30, 8), (35, 4)])
    s_bias = pick(b, [(-5, 15), (-4, 12), (-3, 8), (-2, 4)])
    s_pct = pick(p, [(-0.15, 10), (0, 8), (0.1, 4)])
    s_dd = pick(dd, [(-12, 15), (-8, 12), (-5, 6)])
    if panic:
        s_vol = 30
    elif rc >= PANIC_RECLAIM and vrt >= PANIC_VRT:
        s_vol = 10
    elif vrt < 0.9:
        s_vol = 5
    else:
        s_vol = 0
    s_shdw = 15 if rc >= 0.7 else 10 if rc >= 0.5 else 4 if rc >= 0.3 else 0

    items = [
        {"name": "RSI6 超卖", "value": round(r, 2), "points": s_rsi, "max": 15,
         "reason": f"RSI6={r:.1f}（<20 满分15，<35 起评）"},
        {"name": "BIAS20 乖离", "value": round(b, 2), "points": s_bias, "max": 15,
         "reason": f"乖离率={b:.2f}%（≤-5% 满分15，≤-2% 起评）"},
        {"name": "布林 %B", "value": round(p, 3), "points": s_pct, "max": 10,
         "reason": f"%B={p:.3f}（<0 跌破下轨，<-0.15 满分10）"},
        {"name": "60日回撤", "value": round(dd, 2), "points": s_dd, "max": 15,
         "reason": f"距60日高点 {dd:.2f}%（≤-12% 满分15）"},
        {"name": "恐慌形态", "value": round(vrt, 2), "points": s_vol, "max": 30,
         "reason": ("恐慌日（盘中跌≥3%+收复一半振幅+量比≥1.2）成立，满分30"
                    if panic else
                    f"盘中跌 {idr:.2f}%、收复 {rc:.2f}、量比 {vrt:.2f}，未构成完整恐慌日")},
        {"name": "下影收复", "value": round(rc, 2), "points": s_shdw, "max": 15,
         "reason": f"收复比例={rc:.2f}（≥0.7 满分15，≥0.3 起评）"},
    ]
    return sum(x["points"] for x in items), items


def zone(s, i):
    """趋势分区：'mid' 常规区 / 'high' 高位区 / 'deep' 深跌区；数据不足 None。"""
    r = _prepare(s)["ratio250"][i]
    if r is None:
        return None
    if r > BAND_HI:
        return "high"
    if r < BAND_LO:
        return "deep"
    return "mid"


def trigger_checks(s, i):
    """买Q 触发（警Q）的四道闸明细。返回 (是否触发, [检查项 dict])。"""
    d = _prepare(s)
    rsi2, ma60, ma250, chg5 = d["rsi2"][i], d["ma60"][i], d["ma250"][i], d["chg5"][i]
    z = zone(s, i)
    if rsi2 is None or ma60 is None or ma250 is None or chg5 is None:
        return False, []
    checks = [
        {"name": f"RSI2 ≤ {RSI2_TH}", "value": round(rsi2, 2), "ok": rsi2 <= RSI2_TH,
         "reason": f"RSI2={rsi2:.1f}，2日内卖盘一边倒的极端超卖线"},
        {"name": f"常规区 {BAND_LO}~{BAND_HI}", "value": round(d["ratio250"][i], 3),
         "ok": z == "mid",
         "reason": f"C/MA250={d['ratio250'][i]:.3f}，年线附近的情绪性超卖才做"},
        {"name": f"MA60 ≥ MA250×{Q_MIDTREND}", "value": round(ma60 / ma250, 3),
         "ok": ma60 >= ma250 * Q_MIDTREND,
         "reason": f"MA60/MA250={ma60 / ma250:.3f}，中期趋势没坏"},
        {"name": f"5日累计涨幅 ≥ {Q_NOWATERFALL}%", "value": round(chg5, 2),
         "ok": chg5 >= Q_NOWATERFALL,
         "reason": f"5日累计 {chg5:+.2f}%，不接瀑布式急跌"},
    ]
    return all(c["ok"] for c in checks), checks


def scan_signals(s):
    """扫描全部历史，返回买Q 事件列表：
    [{trigger_i, confirm_i, trigger_date, confirm_date, score}]
    口径：触发后 Q_CONF_WIN 日内收盘站上触发日最高价即确认（先到先得）。"""
    _prepare(s)
    n = len(s.close)
    events = []
    last_trigger = None  # 待确认的触发下标
    for i in range(n):
        trig, _ = trigger_checks(s, i)
        if trig:
            last_trigger = i
        if last_trigger is not None and i > last_trigger:
            if i - last_trigger > Q_CONF_WIN:
                last_trigger = None  # 窗口内未确认，失效
                continue
            if s.close[i] > s.high[last_trigger]:
                score, _ = score_components(s, i)
                events.append({
                    "trigger_i": last_trigger, "confirm_i": i,
                    "trigger_date": s.dates[last_trigger],
                    "confirm_date": s.dates[i],
                    "trigger_high": s.high[last_trigger],
                    "score": score,
                })
                last_trigger = None  # 一次触发只配一次确认
    return events


def status_at(s, date):
    """某日（对齐到交易日）的 V5 状态快照，供关卡判分/展示用。"""
    i = s.idx_on_or_before(date)
    score, items = score_components(s, i)
    trig, checks = trigger_checks(s, i)
    # 是否处于「警Q 待确认」或当日即「买Q」
    pending = None
    for back in range(1, Q_CONF_WIN + 1):
        j = i - back
        if j < 0:
            break
        t, _ = trigger_checks(s, j)
        if t:
            if s.close[i] > s.high[j]:
                pending = {"state": "buyq", "trigger_date": s.dates[j],
                           "trigger_high": s.high[j]}
            else:
                pending = {"state": "waitq", "trigger_date": s.dates[j],
                           "trigger_high": s.high[j]}
            break
    return {
        "date": s.dates[i], "close": s.close[i], "zone": zone(s, i),
        "score": score, "score_items": items,
        "triggered": trig, "trigger_checks": checks,
        "signal": pending or ({"state": "warnq"} if trig else {"state": None}),
    }
