/* 原生 canvas 蜡烛图（红涨绿跌），无任何依赖。
   drawCandles(canvas, candles, opts):
     opts.markIndex   —— 在该下标处画一条决策点竖线
     opts.future      —— 决策点之后揭示的蜡烛（数组，可空）
     opts.showFuture  —— 是否绘制 future 部分
*/
function drawCandles(canvas, candles, opts) {
  opts = opts || {};
  var future = (opts.showFuture && opts.future) ? opts.future : [];
  var all = candles.concat(future);
  if (!all.length) return;

  var dpr = window.devicePixelRatio || 1;
  // 高度只认初始 HTML 属性，避免高分屏下每次重绘把高度再乘一次 dpr（越点越高）
  if (!canvas.dataset.h) canvas.dataset.h = canvas.height;
  var H = parseInt(canvas.dataset.h, 10);
  canvas.style.height = H + 'px';
  var W = canvas.clientWidth;
  canvas.width = W * dpr; canvas.height = H * dpr;
  var ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);

  var padL = 8, padR = 56, padT = 12, volH = Math.round(H * 0.16), gap = 6;
  var priceH = H - padT - volH - gap - 18;
  // 跟随主题的图表配色（CSS 变量在 style.css 的 :root / [data-theme="dark"] 中定义）
  var css = getComputedStyle(document.documentElement);
  var gridColor = css.getPropertyValue('--chart-grid').trim() || '#eeeeee';
  var textColor = css.getPropertyValue('--chart-text').trim() || '#999999';
  var upColor = css.getPropertyValue('--chart-up').trim() || '#d43030';
  var downColor = css.getPropertyValue('--chart-down').trim() || '#1a9e54';
  var lo = Math.min.apply(null, all.map(function (c) { return c.low; }));
  var hi = Math.max.apply(null, all.map(function (c) { return c.high; }));
  if (hi === lo) { hi += 1; }
  var vmax = Math.max.apply(null, all.map(function (c) { return c.volume || 0; })) || 1;
  var n = all.length;
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

  // 决策点之后区域浅色遮罩（揭示时区分“未来”）
  if (future.length) {
    ctx.fillStyle = 'rgba(176,58,46,0.05)';
    var fx = x(candles.length) - slot / 2;
    ctx.fillRect(fx, padT, W - padR - fx, priceH + volH + gap);
  }

  // 蜡烛
  for (var i = 0; i < n; i++) {
    var c = all[i];
    var up = c.close >= c.open;
    ctx.strokeStyle = ctx.fillStyle = up ? upColor : downColor;
    ctx.beginPath(); ctx.moveTo(x(i), y(c.high)); ctx.lineTo(x(i), y(c.low)); ctx.stroke();
    var yO = y(c.open), yC = y(c.close);
    var top = Math.min(yO, yC), hgt = Math.max(1, Math.abs(yO - yC));
    if (up) { ctx.fillRect(x(i) - bw / 2, top, bw, hgt); }
    else { ctx.fillRect(x(i) - bw / 2, top, bw, hgt); }
    // 成交量
    var vh = (c.volume || 0) / vmax * volH;
    ctx.globalAlpha = 0.55;
    ctx.fillRect(x(i) - bw / 2, padT + priceH + gap + volH - vh, bw, vh);
    ctx.globalAlpha = 1;
  }

  // 决策点竖线
  if (typeof opts.markIndex === 'number') {
    var mx = x(opts.markIndex);
    ctx.strokeStyle = '#1565c0'; ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(mx, padT); ctx.lineTo(mx, padT + priceH + gap + volH); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#1565c0'; ctx.textAlign = 'center';
    ctx.fillText('决策点', mx, padT + priceH + gap + volH + 14);
  }

  // 首尾日期
  ctx.fillStyle = textColor; ctx.textAlign = 'left';
  ctx.fillText(all[0].date, padL, H - 4);
  ctx.textAlign = 'right';
  ctx.fillText(all[n - 1].date, W - padR, H - 4);
}
