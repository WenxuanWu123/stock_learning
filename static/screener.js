/* 选股实验场：条件勾选 + 参数输入 + 单次筛选/历史统计 + 结果统计与命中表。
   自包含模块（零依赖，风格同 lab.js），由 app.js 的路由调用 window.renderScreener()。 */
(function () {
  /* ── 条件定义：字段默认值与后端 app/screener.py 一致 ── */
  var COND_DEFS = [
    { type: 'ma_bull', name: '均线多头排列', hint: '收盘 > MA1 > MA2 > MA3',
      fields: [{ k: 'p1', label: 'MA1', def: 5 }, { k: 'p2', label: 'MA2', def: 20 },
               { k: 'p3', label: 'MA3', def: 60 }],
      build: function (v) { return { periods: [v.p1, v.p2, v.p3] }; } },
    { type: 'rsi_max', name: 'RSI 超卖', hint: 'RSI(n) ≤ 上限',
      fields: [{ k: 'n', label: 'n', def: 6 }, { k: 'max', label: '上限', def: 20 }] },
    { type: 'bias_max', name: '乖离率过低', hint: 'BIAS(n)% ≤ 上限（负值 = 低于均线）',
      fields: [{ k: 'n', label: 'n', def: 20 }, { k: 'max', label: '上限%', def: -5 }] },
    { type: 'drawdown_min', name: '高点回撤够深', hint: '距 n 日高点回撤 ≥ min%',
      fields: [{ k: 'n', label: 'n', def: 60 }, { k: 'min', label: 'min%', def: 20 }] },
    { type: 'vol_ratio', name: '放量', hint: '当日量 / n 日均量 ≥ min',
      fields: [{ k: 'n', label: 'n', def: 5 }, { k: 'min', label: 'min', def: 2 }] },
    { type: 'chg_range', name: 'n 日涨跌幅区间', hint: 'min% ≤ n 日涨幅 ≤ max%',
      fields: [{ k: 'n', label: 'n', def: 20 }, { k: 'min', label: 'min%', def: -10 },
               { k: 'max', label: 'max%', def: 5 }] }
  ];
  var state = { on: { rsi_max: true }, vals: {}, asOf: '', fwd: 20 };
  COND_DEFS.forEach(function (c) {
    state.vals[c.type] = {};
    c.fields.forEach(function (f) { state.vals[c.type][f.k] = f.def; });
  });

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function post(path, body) {
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
      return r.json();
    });
  }
  function pct(v) {
    if (v === null || v === undefined) return '—';
    return (v > 0 ? '+' : '') + v + '%';
  }
  function cls(v) { return v > 0 ? 'up' : (v < 0 ? 'down' : ''); }

  /* ── 页面骨架 ── */
  window.renderScreener = function () {
    var app = document.getElementById('app');
    var html = '<div class="card"><h2>选股实验场</h2>' +
      '<p class="muted">自由组合技术条件筛股票。别急着信——先看它在历史上的真实战绩。</p>' +
      '<div id="scr-conds" style="margin-top:12px"></div>' +
      '<div class="scr-base" style="margin-top:6px">' +
      '<span>基准日 <input type="date" id="scr-asof"> <span class="muted">（留空 = 最新交易日）</span></span>' +
      '<span>后续观察 <input type="number" id="scr-fwd" min="1" max="120" value="20" style="width:64px"> 个交易日</span>' +
      '</div>' +
      '<div style="margin-top:14px">' +
      '<button class="btn" id="scr-run">单次筛选</button> ' +
      '<button class="btn ghost" id="scr-hist">历史统计（近 250 交易日）</button>' +
      '<span class="muted" id="scr-msg" style="margin-left:12px"></span></div>' +
      '<div id="scr-err"></div></div>' +
      '<div id="scr-result"></div>' +
      '<p class="muted" style="margin-top:12px">先看历史统计再信条件：' +
      '大多数公式的战绩和扔硬币差不多。</p>';
    app.innerHTML = html;
    buildConds();
    document.getElementById('scr-asof').onchange = function () {
      state.asOf = this.value;
    };
    document.getElementById('scr-fwd').onchange = function () {
      var v = parseInt(this.value, 10);
      state.fwd = isNaN(v) ? 20 : v;
    };
    document.getElementById('scr-run').onclick = function () { run('single'); };
    document.getElementById('scr-hist').onclick = function () { run('history'); };
  };

  function buildConds() {
    var box = document.getElementById('scr-conds');
    box.innerHTML = '';
    COND_DEFS.forEach(function (c) {
      var row = document.createElement('div');
      row.className = 'scr-cond' + (state.on[c.type] ? '' : ' off');
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !!state.on[c.type];
      cb.onchange = function () {
        state.on[c.type] = cb.checked;
        row.className = 'scr-cond' + (cb.checked ? '' : ' off');
      };
      row.appendChild(cb);
      var nm = document.createElement('span');
      nm.className = 'nm';
      nm.textContent = c.name;
      row.appendChild(nm);
      c.fields.forEach(function (f) {
        var lab = document.createElement('label');
        lab.className = 'muted';
        lab.textContent = f.label + ' ';
        var inp = document.createElement('input');
        inp.type = 'number';
        inp.value = state.vals[c.type][f.k];
        inp.onchange = function () {
          var v = parseFloat(inp.value);
          if (!isNaN(v)) state.vals[c.type][f.k] = v;
          inp.value = state.vals[c.type][f.k];
        };
        lab.appendChild(inp);
        row.appendChild(lab);
      });
      var hint = document.createElement('span');
      hint.className = 'hint';
      hint.textContent = c.hint;
      row.appendChild(hint);
      box.appendChild(row);
    });
  }

  /* ── 请求与渲染 ── */
  function buildConditions() {
    var out = [];
    COND_DEFS.forEach(function (c) {
      if (!state.on[c.type]) return;
      var v = state.vals[c.type];
      var params = c.build ? c.build(v) : {};
      if (!c.build) c.fields.forEach(function (f) { params[f.k] = v[f.k]; });
      out.push({ type: c.type, params: params });
    });
    return out;
  }

  function setBusy(busy) {
    document.getElementById('scr-run').disabled = busy;
    document.getElementById('scr-hist').disabled = busy;
    document.getElementById('scr-msg').textContent = busy ? '计算中…' : '';
  }
  function showErr(msg) {
    document.getElementById('scr-err').innerHTML =
      '<div class="scr-err">参数无效：' + esc(msg) + '</div>';
    document.getElementById('scr-result').innerHTML = '';
  }

  function run(mode) {
    var conds = buildConditions();
    document.getElementById('scr-err').innerHTML = '';
    if (!conds.length) { showErr('请先勾选至少一个条件'); return; }
    var body = { conditions: conds, forward_days: state.fwd, mode: mode };
    if (state.asOf) body.as_of = state.asOf;
    setBusy(true);
    post('/api/screener', body).then(function (d) {
      setBusy(false);
      renderResult(d);
    }).catch(function (e) {
      setBusy(false);
      showErr(e.message);
    });
  }

  function statCards(items) {
    var html = '<div class="scr-cards">';
    items.forEach(function (it) {
      html += '<div class="scr-stat"><div class="v ' + (it.cls || '') + '">' + it.v +
        '</div><div class="k">' + esc(it.k) + '</div></div>';
    });
    return html + '</div>';
  }

  function statsItems(s, fwd) {
    return [
      { v: s.count, k: '有效样本' },
      { v: s.win_rate === null ? '—' : s.win_rate + '%', k: '胜率（' + fwd + ' 日后收涨）' },
      { v: pct(s.avg), k: '平均收益', cls: cls(s.avg) },
      { v: pct(s.median), k: '中位数', cls: cls(s.median) },
      { v: pct(s.best), k: '最好', cls: cls(s.best) },
      { v: pct(s.worst), k: '最差', cls: cls(s.worst) }
    ];
  }

  function hitsTable(d, withDate) {
    if (!d.hits.length) return '<p class="muted">没有命中记录。</p>';
    var labels = d.conditions.map(function (c) { return c.label; });
    var html = '<div style="overflow-x:auto"><table class="scr-hits"><tr>' +
      (withDate ? '<th class="l">日期</th>' : '') +
      '<th class="l">代码</th><th class="l">名称</th><th>收盘</th>';
    labels.forEach(function (l) { html += '<th>' + esc(l) + '</th>'; });
    html += '<th>' + d.forward_days + ' 日后</th><th class="l">到期日</th></tr>';
    d.hits.forEach(function (r) {
      html += '<tr>' + (withDate ? '<td class="l">' + esc(r.date) + '</td>' : '') +
        '<td class="l">' + esc(r.code) + '</td><td class="l">' + esc(r.name) + '</td>' +
        '<td>' + r.close + '</td>';
      labels.forEach(function (l) {
        html += '<td>' + esc(r.values[l] !== undefined ? r.values[l] : '—') + '</td>';
      });
      html += '<td class="' + cls(r.forward_return) + '">' + pct(r.forward_return) +
        '</td><td class="l">' + (r.forward_date || '未满') + '</td></tr>';
    });
    return html + '</table></div>';
  }

  function renderResult(d) {
    var box = document.getElementById('scr-result');
    var condText = d.conditions.map(function (c) { return c.label; }).join(' ＋ ');
    var html = '';
    if (d.mode === 'single') {
      html += '<div class="card"><h2>单次筛选：' + esc(d.as_of) + '</h2>' +
        '<p class="muted">' + esc(condText) + '</p>' +
        '<p>全池 <b>' + d.pool_size + '</b> 只，命中 <b class="up">' + d.hit_count +
        '</b> 只' + (d.hit_count > d.shown ? '（仅展示前 ' + d.shown + ' 只）' : '') +
        (d.stats.pending ? '，其中 ' + d.stats.pending + ' 只后续未满 ' + d.forward_days +
          ' 个交易日，暂不计入统计' : '') + '。</p>' +
        statCards(statsItems(d.stats, d.forward_days)) +
        '<p class="muted">同期全池基准：' + d.baseline.count + ' 只有效，胜率 ' +
        (d.baseline.win_rate === null ? '—' : d.baseline.win_rate + '%') + '，平均 ' +
        pct(d.baseline.avg) + ' —— 你的条件跑赢基准才算有点东西。</p></div>' +
        '<div class="card"><h2>命中明细</h2>' + hitsTable(d, false) + '</div>';
    } else {
      var h = d.history;
      html += '<div class="card"><h2>历史统计：' + esc(h.from) + ' ~ ' + esc(h.to) +
        '（' + h.days + ' 个交易日）</h2>' +
        '<p class="muted">' + esc(condText) + '</p>' +
        '<p>同一组条件在每个交易日各跑一遍：共命中 <b class="up">' + h.hit_count +
        '</b> 次（按股·日计），分布在 <b>' + h.hit_days + '</b> 个交易日' +
        (h.pending ? '，' + h.pending + ' 次后续未满不计入' : '') + '。</p>' +
        statCards(statsItems(h.stats, d.forward_days)) +
        '<p class="muted">同期全市场基准：' + h.baseline.count + ' 个股·日，胜率 ' +
        (h.baseline.win_rate === null ? '—' : h.baseline.win_rate + '%') + '，平均 ' +
        pct(h.baseline.avg) + '，中位数 ' + pct(h.baseline.median) +
        ' —— 条件战绩和基准差不多，就说明它没用。</p>' +
        '<h2 style="margin-top:14px">命中收益分布</h2>' + histTable(h) + '</div>' +
        '<div class="card"><h2>最近命中样本（至多 ' + d.shown + ' 条）</h2>' +
        hitsTable(d, true) + '</div>';
    }
    box.innerHTML = html;
    window.scrollTo(0, box.offsetTop - 70);
  }

  function histTable(h) {
    var total = h.stats.count || 1;
    var max = Math.max.apply(null, h.histogram.counts.concat([1]));
    var html = '<table class="stats"><tr><th>区间</th><th>次数</th><th>占比</th>' +
      '<th style="width:40%"></th></tr>';
    h.histogram.buckets.forEach(function (b, i) {
      var cnt = h.histogram.counts[i];
      var share = Math.round(1000 * cnt / total) / 10;
      html += '<tr><td>' + esc(b) + '</td><td>' + cnt + '</td><td>' + share + '%</td>' +
        '<td><div style="height:8px;border-radius:4px;background:var(--accent);width:' +
        Math.round(100 * cnt / max) + '%"></div></td></tr>';
    });
    return html + '</table>';
  }
})();
