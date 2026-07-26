/* C 型 · 参数实验场：控制区 + 主图（蜡烛 + 双 MA）+ 副图（MACD/KDJ/RSI/BIAS）。
   自包含模块（零依赖，风格同 chart.js），由 app.js 的路由调用 window.renderLab()。 */
(function () {
  /* ── 可调参数与默认值（与后端 app/lab.py 一致） ── */
  var state = {
    symbol: 'sh000001', days: 250, ma1: 5, ma2: 20,
    indicator: 'macd',
    macd: { fast: 12, slow: 26, signal: 9 },
    kdj: { n: 9, m1: 3, m2: 3 },
    rsi: { rsi1: 6, rsi2: 12, rsi3: 24 },
    bias: { bias_n: 20 }
  };
  var SYMBOLS = [
    ['sh000001', '上证指数'], ['sh000300', '沪深300'], ['sh000905', '中证500']
  ];
  var DAY_OPTIONS = [120, 250, 500];
  var INDICATORS = [['macd', 'MACD'], ['kdj', 'KDJ'], ['rsi', 'RSI'], ['bias', 'BIAS']];
  /* 每种副图指标的参数控件定义（label 用于界面与接口参数名对应） */
  var PARAM_DEFS = {
    macd: [
      { key: 'fast', label: '快线', min: 2, max: 60 },
      { key: 'slow', label: '慢线', min: 3, max: 120 },
      { key: 'signal', label: '信号', min: 2, max: 60 }
    ],
    kdj: [
      { key: 'n', label: 'N', min: 2, max: 60 },
      { key: 'm1', label: 'M1', min: 2, max: 30 },
      { key: 'm2', label: 'M2', min: 2, max: 30 }
    ],
    rsi: [
      { key: 'rsi1', label: 'RSI1', min: 2, max: 120 },
      { key: 'rsi2', label: 'RSI2', min: 2, max: 120 },
      { key: 'rsi3', label: 'RSI3（0=隐藏）', min: 0, max: 120 }
    ],
    bias: [
      { key: 'bias_n', label: 'N', min: 2, max: 120 }
    ]
  };
  var LINE_COLORS = ['#e8833a', '#1565c0', '#7b1fa2']; // 橙/蓝/紫，亮暗主题均可读

  var data = null;       // 最近一次 /api/lab 返回
  var fetchSeq = 0;      // 防止快速拖滑块时旧响应覆盖新响应
  var debounceTimer = null;

  function api(path) {
    return fetch(path).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
      return r.json();
    });
  }
  function cssVar(name, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  }
  function fmt(v) {
    return v === null || v === undefined ? '—' : (+v).toFixed(2);
  }

  /* ── 页面骨架 ── */
  window.renderLab = function () {
    var app = document.getElementById('app');
    app.innerHTML =
      '<div class="card"><h2>C 型 · 参数实验场</h2>' +
      '<div class="lab-controls" id="lab-base"></div>' +
      '<div style="margin-top:14px"><span class="muted">副图指标：</span><span id="lab-tabs"></span></div>' +
      '<div class="lab-controls" id="lab-params" style="margin-top:12px"></div></div>' +
      '<div class="chart-wrap"><canvas id="lab-main" height="380"></canvas></div>' +
      '<div class="chart-wrap" style="margin-top:12px"><canvas id="lab-sub" height="170"></canvas></div>' +
      '<p class="muted" style="margin-top:12px">拖参数看信号怎么变：参数越灵敏假信号越多，' +
      '越迟钝入场越晚。没有圣杯参数。</p>';
    buildBaseControls();
    buildTabs();
    buildParamControls();
    window.onresize = drawAll;
    load();
  };

  function selectCtrl(label, options, get, set) {
    var wrap = document.createElement('div');
    wrap.className = 'lab-ctrl';
    var lab = document.createElement('label');
    lab.textContent = label;
    var sel = document.createElement('select');
    options.forEach(function (o) {
      var opt = document.createElement('option');
      opt.value = o[0]; opt.textContent = o[1];
      sel.appendChild(opt);
    });
    sel.value = String(get());
    sel.onchange = function () { set(sel.value); scheduleLoad(); };
    wrap.appendChild(lab); wrap.appendChild(sel);
    return wrap;
  }

  function sliderCtrl(label, min, max, get, set) {
    var wrap = document.createElement('div');
    wrap.className = 'lab-ctrl';
    var lab = document.createElement('label');
    var slider = document.createElement('input');
    slider.type = 'range'; slider.min = min; slider.max = max; slider.value = get();
    function paint() { lab.textContent = label + '：' + slider.value; }
    slider.oninput = function () {
      paint(); set(parseInt(slider.value, 10)); scheduleLoad();
    };
    paint();
    wrap.appendChild(lab); wrap.appendChild(slider);
    return wrap;
  }

  function buildBaseControls() {
    var box = document.getElementById('lab-base');
    box.innerHTML = '';
    box.appendChild(selectCtrl('指数', SYMBOLS,
      function () { return state.symbol; },
      function (v) { state.symbol = v; }));
    box.appendChild(selectCtrl('天数', DAY_OPTIONS.map(function (d) { return [d, d + ' 日']; }),
      function () { return state.days; },
      function (v) { state.days = parseInt(v, 10); }));
    box.appendChild(sliderCtrl('MA1', 2, 250,
      function () { return state.ma1; },
      function (v) { state.ma1 = v; }));
    box.appendChild(sliderCtrl('MA2', 2, 250,
      function () { return state.ma2; },
      function (v) { state.ma2 = v; }));
  }

  function buildTabs() {
    var box = document.getElementById('lab-tabs');
    box.innerHTML = '';
    INDICATORS.forEach(function (it) {
      var b = document.createElement('button');
      b.className = 'lab-tab' + (state.indicator === it[0] ? ' active' : '');
      b.textContent = it[1];
      b.onclick = function () {
        if (state.indicator === it[0]) return;
        state.indicator = it[0];
        buildTabs(); buildParamControls(); load();
      };
      box.appendChild(b);
    });
  }

  function buildParamControls() {
    var box = document.getElementById('lab-params');
    box.innerHTML = '';
    var params = state[state.indicator];
    PARAM_DEFS[state.indicator].forEach(function (def) {
      box.appendChild(sliderCtrl(def.label, def.min, def.max,
        function () { return params[def.key]; },
        function (v) { params[def.key] = v; }));
    });
  }

  /* ── 请求数据 ── */
  function queryString() {
    var p = ['symbol=' + state.symbol, 'days=' + state.days,
      'ma1=' + state.ma1, 'ma2=' + state.ma2, 'indicator=' + state.indicator];
    var params = state[state.indicator];
    Object.keys(params).forEach(function (k) { p.push(k + '=' + params[k]); });
    return p.join('&');
  }

  function scheduleLoad() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(load, 250);
  }

  function load() {
    var seq = ++fetchSeq;
    api('/api/lab?' + queryString()).then(function (d) {
      if (seq !== fetchSeq) return; // 已有更新的请求
      data = d;
      drawAll();
    }).catch(function (e) {
      if (seq !== fetchSeq) return;
      var sub = document.getElementById('lab-sub');
      if (sub) {
        var ctx = sub.getContext('2d');
        ctx.clearRect(0, 0, sub.width, sub.height);
      }
      alert('参数无效：' + e.message);
    });
  }

  /* ── 绘图公共件 ── */
  function prepCanvas(canvas) {
    var dpr = window.devicePixelRatio || 1;
    var W = canvas.clientWidth, H = canvas.height;
    canvas.width = W * dpr; canvas.height = H * dpr;
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    return [ctx, W, H];
  }

  function drawLine(ctx, values, x, y, color) {
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.beginPath();
    var started = false;
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (v === null || v === undefined) { started = false; continue; }
      if (!started) { ctx.moveTo(x(i), y(v)); started = true; }
      else ctx.lineTo(x(i), y(v));
    }
    ctx.stroke(); ctx.lineWidth = 1;
  }

  function legend(ctx, items, x0, y0) {
    ctx.font = '11px sans-serif'; ctx.textAlign = 'left';
    var lx = x0;
    items.forEach(function (it) {
      var text = it.label + ' ' + fmt(it.value);
      ctx.fillStyle = it.color;
      ctx.fillText(text, lx, y0);
      lx += ctx.measureText(text).width + 16;
    });
  }

  function lastVal(values) {
    for (var i = values.length - 1; i >= 0; i--) {
      if (values[i] !== null && values[i] !== undefined) return values[i];
    }
    return null;
  }

  function drawAll() {
    if (!data || !document.getElementById('lab-main')) return;
    drawMain();
    drawSub();
  }

  /* ── 主图：蜡烛 + 成交量 + 双 MA ── */
  function drawMain() {
    var candles = data.candles;
    var r = prepCanvas(document.getElementById('lab-main'));
    var ctx = r[0], W = r[1], H = r[2];
    var padL = 8, padR = 56, padT = 12, volH = Math.round(H * 0.16), gap = 6;
    var priceH = H - padT - volH - gap - 18;
    var gridColor = cssVar('--chart-grid', '#eeeeee');
    var textColor = cssVar('--chart-text', '#999999');
    var upColor = cssVar('--chart-up', '#d43030');
    var downColor = cssVar('--chart-down', '#1a9e54');

    var lo = Math.min.apply(null, candles.map(function (c) { return c.low; }));
    var hi = Math.max.apply(null, candles.map(function (c) { return c.high; }));
    [data.ma.ma1.values, data.ma.ma2.values].forEach(function (vs) {
      vs.forEach(function (v) {
        if (v === null) return;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      });
    });
    if (hi === lo) hi += 1;
    var vmax = Math.max.apply(null, candles.map(function (c) { return c.volume || 0; })) || 1;
    var n = candles.length;
    var slot = (W - padL - padR) / n;
    var bw = Math.max(1, Math.min(14, slot * 0.62));
    function y(p) { return padT + (hi - p) / (hi - lo) * priceH; }
    function x(i) { return padL + slot * (i + 0.5); }

    // 网格与右侧刻度
    ctx.strokeStyle = gridColor; ctx.fillStyle = textColor; ctx.font = '11px sans-serif';
    ctx.textAlign = 'left';
    for (var g = 0; g <= 4; g++) {
      var pv = lo + (hi - lo) * g / 4, yy = y(pv);
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke();
      ctx.fillText(pv.toFixed(0), W - padR + 6, yy + 4);
    }

    // 蜡烛 + 成交量（红涨绿跌）
    for (var i = 0; i < n; i++) {
      var c = candles[i];
      var up = c.close >= c.open;
      ctx.strokeStyle = ctx.fillStyle = up ? upColor : downColor;
      ctx.beginPath(); ctx.moveTo(x(i), y(c.high)); ctx.lineTo(x(i), y(c.low)); ctx.stroke();
      var yO = y(c.open), yC = y(c.close);
      var top = Math.min(yO, yC), hgt = Math.max(1, Math.abs(yO - yC));
      ctx.fillRect(x(i) - bw / 2, top, bw, hgt);
      var vh = (c.volume || 0) / vmax * volH;
      ctx.globalAlpha = 0.55;
      ctx.fillRect(x(i) - bw / 2, padT + priceH + gap + volH - vh, bw, vh);
      ctx.globalAlpha = 1;
    }

    // 双 MA 线 + 图例
    function xm(i) { return x(i); }
    drawLine(ctx, data.ma.ma1.values, xm, y, LINE_COLORS[0]);
    drawLine(ctx, data.ma.ma2.values, xm, y, LINE_COLORS[1]);
    legend(ctx, [
      { label: 'MA' + data.ma.ma1.n, value: lastVal(data.ma.ma1.values), color: LINE_COLORS[0] },
      { label: 'MA' + data.ma.ma2.n, value: lastVal(data.ma.ma2.values), color: LINE_COLORS[1] }
    ], padL + 4, padT + 4);

    // 首尾日期
    ctx.fillStyle = textColor; ctx.textAlign = 'left';
    ctx.fillText(candles[0].date, padL, H - 4);
    ctx.textAlign = 'right';
    ctx.fillText(candles[n - 1].date, W - padR, H - 4);
  }

  /* ── 副图：MACD / KDJ / RSI / BIAS ── */
  function drawSub() {
    var ind = data.indicator;
    var r = prepCanvas(document.getElementById('lab-sub'));
    var ctx = r[0], W = r[1], H = r[2];
    var padL = 8, padR = 56, padT = 12, padB = 18;
    var plotH = H - padT - padB;
    var gridColor = cssVar('--chart-grid', '#eeeeee');
    var textColor = cssVar('--chart-text', '#999999');
    var upColor = cssVar('--chart-up', '#d43030');
    var downColor = cssVar('--chart-down', '#1a9e54');

    // 收集要画的线（label/values/color）与数值范围
    var lines = [], lo = Infinity, hi = -Infinity;
    function take(values, label, color) {
      lines.push({ values: values, label: label, color: color });
      values.forEach(function (v) {
        if (v === null || v === undefined) return;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      });
    }
    var bars = null; // 仅 MACD 有柱
    if (ind.kind === 'macd') {
      take(ind.series.dif, 'DIF', LINE_COLORS[0]);
      take(ind.series.dea, 'DEA', LINE_COLORS[1]);
      bars = ind.series.bar;
      bars.forEach(function (v) {
        if (v === null) return;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      });
      lo = Math.min(lo, 0); hi = Math.max(hi, 0);
    } else if (ind.kind === 'kdj') {
      take(ind.series.k, 'K', LINE_COLORS[0]);
      take(ind.series.d, 'D', LINE_COLORS[1]);
      take(ind.series.j, 'J', LINE_COLORS[2]);
    } else if (ind.kind === 'rsi') {
      take(ind.series.rsi1, 'RSI' + ind.params.rsi1, LINE_COLORS[0]);
      take(ind.series.rsi2, 'RSI' + ind.params.rsi2, LINE_COLORS[1]);
      if (ind.series.rsi3) take(ind.series.rsi3, 'RSI' + ind.params.rsi3, LINE_COLORS[2]);
      lo = Math.min(lo, 50); hi = Math.max(hi, 50);
    } else { // bias
      take(ind.series.bias, 'BIAS' + ind.params.n, LINE_COLORS[0]);
      lo = Math.min(lo, 0); hi = Math.max(hi, 0);
    }
    if (!isFinite(lo) || !isFinite(hi)) return;
    if (hi === lo) hi += 1;

    var n = data.candles.length;
    var slot = (W - padL - padR) / n;
    var bw = Math.max(1, Math.min(14, slot * 0.62));
    function y(v) { return padT + (hi - v) / (hi - lo) * plotH; }
    function x(i) { return padL + slot * (i + 0.5); }

    // 网格与右侧刻度
    ctx.strokeStyle = gridColor; ctx.fillStyle = textColor; ctx.font = '11px sans-serif';
    ctx.textAlign = 'left';
    for (var g = 0; g <= 2; g++) {
      var pv = lo + (hi - lo) * g / 2, yy = y(pv);
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke();
      ctx.fillText(pv.toFixed(2), W - padR + 6, yy + 4);
    }
    // 零轴（MACD / BIAS 更直观）
    if (lo < 0 && hi > 0) {
      ctx.strokeStyle = textColor; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(padL, y(0)); ctx.lineTo(W - padR, y(0)); ctx.stroke();
      ctx.setLineDash([]);
    }

    // MACD 柱（红正绿负）
    if (bars) {
      for (var i = 0; i < bars.length; i++) {
        var v = bars[i];
        if (v === null) continue;
        ctx.fillStyle = v >= 0 ? upColor : downColor;
        var y0 = y(0), y1 = y(v);
        ctx.fillRect(x(i) - bw / 2, Math.min(y0, y1), bw, Math.max(1, Math.abs(y1 - y0)));
      }
    }

    // 曲线 + 图例
    var items = [];
    lines.forEach(function (l) {
      drawLine(ctx, l.values, x, y, l.color);
      items.push({ label: l.label, value: lastVal(l.values), color: l.color });
    });
    if (bars) items.push({ label: 'MACD', value: lastVal(bars), color: textColor });
    legend(ctx, items, padL + 4, padT + 4);
  }
})();
