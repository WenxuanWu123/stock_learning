/* 原生 JS SPA（零构建），hash 路由。 */
(function () {
  var app = document.getElementById('app');

  /* ── 亮/暗色切换 ── */
  var themeBtn = document.getElementById('theme-btn');
  function paintThemeBtn() {
    var dark = document.documentElement.dataset.theme === 'dark';
    themeBtn.textContent = dark ? '切换亮色' : '切换暗色';
  }
  themeBtn.onclick = function () {
    var next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('theme', next);
    paintThemeBtn();
    window.dispatchEvent(new Event('resize')); // 触发 K 线图按新主题色重绘
  };
  paintThemeBtn();

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
      return r.json();
    });
  }
  function post(path, body) {
    return api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ── 首页：模块 / 章节导航 ── */
  function renderHome() {
    api('/api/modules').then(function (d) {
      var html = '';
      d.modules.forEach(function (m) {
        html += '<div class="module-title">' + esc(m.title) + '</div>';
        if (!m.chapters.length) {
          html += '<div class="muted" style="margin-bottom:10px">（内容建设中）</div>';
        }
        m.chapters.forEach(function (c) {
          html += '<div class="chapter-link"><span>' + esc(c.title) + '</span>' +
            '<span class="actions"><a href="#/lesson/' + c.id + '">读课文</a>' +
            '<a href="#/quiz/' + c.id + '">闯关答题</a></span></div>';
        });
      });
      app.innerHTML = html;
    });
  }

  /* ── 课文页 ── */
  function renderLesson(id) {
    api('/api/chapters/' + id + '/lesson').then(function (d) {
      var src = d.sources.length
        ? '<div class="sources muted">参考来源：' + d.sources.map(esc).join('；') + '</div>' : '';
      app.innerHTML = '<div class="card lesson">' + d.html + src + '</div>' +
        '<a class="btn" href="#/quiz/' + id + '">去做本章题 →</a> ' +
        '<a class="btn ghost" href="#/">返回目录</a>';
    });
  }

  /* ── 闯关答题 ── */
  function renderQuiz(id) {
    api('/api/chapters/' + id + '/quiz').then(function (d) {
      var qs = d.questions, cur = 0, right = 0;
      function show() {
        if (cur >= qs.length) {
          app.innerHTML = '<div class="card"><h2>本章完成！</h2>' +
            '<p>答对 <b class="up">' + right + '</b> / ' + qs.length + ' 题</p>' +
            '<p style="margin-top:14px"><a class="btn" href="#/">返回目录</a> ' +
            '<a class="btn ghost" href="#/stats">看成绩</a></p></div>';
          return;
        }
        var q = qs[cur];
        var html = '<div class="card"><div class="progress">第 ' + (cur + 1) +
          ' / ' + qs.length + ' 题</div><div class="quiz-q">' + esc(q.q) + '</div>';
        q.options.forEach(function (o, i) {
          html += '<button class="opt" data-i="' + i + '">' +
            String.fromCharCode(65 + i) + '. ' + esc(o) + '</button>';
        });
        html += '<div id="feedback"></div></div>';
        app.innerHTML = html;
        var btns = app.querySelectorAll('.opt');
        btns.forEach(function (b) {
          b.onclick = function () {
            var chosen = parseInt(b.dataset.i, 10);
            post('/api/answers', { question_id: q.id, chosen: chosen }).then(function (r) {
              btns.forEach(function (x, i) {
                x.disabled = true;
                if (i === r.answer) x.classList.add('right');
                else if (i === chosen) x.classList.add('wrong');
              });
              if (r.correct) right++;
              document.getElementById('feedback').innerHTML =
                '<div class="expl"><b>' + (r.correct ? '✓ 答对了' : '✗ 答错了，正确答案：' +
                String.fromCharCode(65 + r.answer)) + '</b><br>' + esc(r.explanation) +
                '</div><p style="margin-top:12px"><button class="btn" id="next">' +
                (cur + 1 < qs.length ? '下一题' : '查看结果') + '</button></p>';
              document.getElementById('next').onclick = function () { cur++; show(); };
            });
          };
        });
      }
      show();
    });
  }

  /* ── 关卡列表 ── */
  function renderLevels() {
    api('/api/levels').then(function (d) {
      var html = '<div class="module-title">B 型 · K线实战演练</div>';
      if (!d.levels.length) html += '<div class="muted">暂无关卡</div>';
      d.levels.forEach(function (l) {
        html += '<a class="chapter-link" href="#/level/' + l.id + '"><span>' +
          esc(l.title) + '<div class="muted">' + esc(l.symbol_name) + ' · 决策日 ' +
          esc(l.decision_date) + '</div></span>' +
          '<span>' + (l.best_score !== null ? '最好成绩 ' + l.best_score + ' 分' : '未挑战') +
          '</span></a>';
      });
      app.innerHTML = html;
    });
  }

  /* ── 关卡页 ── */
  function renderLevel(id) {
    api('/api/levels/' + id).then(function (d) {
      var state = { future: null, v5: null };
      app.innerHTML =
        '<div class="card"><h2>' + esc(d.title) + '</h2>' +
        '<p class="muted">' + esc(d.symbol_name) + ' · 决策日 ' + esc(d.decision_date) + '</p>' +
        '<p style="margin-top:8px">' + esc(d.question) + '</p></div>' +
        '<div class="chart-wrap"><canvas id="kline" height="380"></canvas></div>' +
        '<div class="card" id="decide"><div class="quiz-q">你的决策：</div>' +
        d.options.map(function (o) {
          return '<button class="opt" data-k="' + o.key + '">' + o.key + '. ' + esc(o.text) + '</button>';
        }).join('') + '<div id="result"></div></div>' +
        '<a class="btn ghost" href="#/levels">返回关卡列表</a>';

      var canvas = document.getElementById('kline');
      function draw() {
        drawCandles(canvas, d.candles, {
          markIndex: d.candles.length - 1,
          future: state.future, showFuture: !!state.future
        });
      }
      draw();
      window.onresize = draw;

      app.querySelectorAll('#decide .opt').forEach(function (b) {
        b.onclick = function () {
          post('/api/levels/' + id + '/submit', { chosen: b.dataset.k }).then(function (r) {
            state.future = r.future; state.v5 = r.v5;
            draw();
            app.querySelectorAll('#decide .opt').forEach(function (x) { x.disabled = true; });
            b.classList.add(r.score >= 60 ? 'right' : 'wrong');
            var v5 = r.v5;
            var zoneName = { mid: '常规区', high: '高位区', deep: '深跌区' }[v5.zone] || '—';
            var rows = v5.score_items.map(function (it) {
              return '<tr><td>' + esc(it.name) + '</td><td>' + it.value + '</td>' +
                '<td>' + it.points + ' / ' + it.max + '</td><td class="muted">' +
                esc(it.reason) + '</td></tr>';
            }).join('');
            var checks = v5.trigger_checks.map(function (c) {
              return '<tr><td>' + (c.ok ? '✓' : '✗') + '</td><td>' + esc(c.name) +
                '</td><td>' + c.value + '</td><td class="muted">' + esc(c.reason) + '</td></tr>';
            }).join('');
            var sigTag = v5.signal.state === 'warnq'
              ? '<span class="tag blue">警Q：快反已触发，待确认</span>'
              : v5.signal.state === 'buyq'
                ? '<span class="tag blue">买Q：确认成立</span>'
                : '<span class="tag gray">无信号</span>';
            document.getElementById('result').innerHTML =
              '<div class="expl"><span class="score-big">' + r.score + '</span> 分 ' +
              (r.reveal_return_pct !== null
                ? '（决策点后 ' + r.future.length + ' 日走势：<b class="' +
                  (r.reveal_return_pct >= 0 ? 'up' : 'down') + '">' +
                  (r.reveal_return_pct >= 0 ? '+' : '') + r.reveal_return_pct + '%</b>）' : '') +
              '<br>' + esc(r.feedback) + '</div>' +
              '<div class="card" style="margin-top:14px"><h2>V5 系统解析（决策日收盘）</h2>' +
              '<p>趋势分区：<b>' + zoneName + '</b> ｜ 六项总分：<b>' + v5.score +
              ' / 100</b> ｜ ' + sigTag + '</p>' +
              '<h2 style="margin-top:10px">快反轨四道闸</h2>' +
              '<table class="v5-table"><tr><th></th><th>闸口</th><th>实际值</th><th>含义</th></tr>' +
              checks + '</table>' +
              '<h2 style="margin-top:10px">六项打分明细</h2>' +
              '<table class="v5-table"><tr><th>项</th><th>数值</th><th>得分</th><th>说明</th></tr>' +
              rows + '</table></div>';
            window.scrollTo(0, document.body.scrollHeight);
          });
        };
      });
    });
  }

  /* ── 成绩页 ── */
  function renderStats() {
    api('/api/stats').then(function (d) {
      var html = '<div class="card"><h2>总览</h2><p>累计答题 <b>' + d.attempts +
        '</b> 次，正确 <b class="up">' + d.correct + '</b> 次，正确率 <b>' +
        (d.accuracy === null ? '—' : d.accuracy + '%') + '</b></p></div>';

      html += '<div class="card"><h2>分章成绩</h2><table class="stats">' +
        '<tr><th>章节</th><th>答题数</th><th>正确</th></tr>';
      d.chapters.forEach(function (c) {
        if (c.attempts) html += '<tr><td>' + esc(c.title) + '</td><td>' + c.attempts +
          '</td><td>' + c.correct + '</td></tr>';
      });
      html += '</table></div>';

      html += '<div class="card"><h2>关卡成绩</h2><table class="stats">' +
        '<tr><th>关卡</th><th>挑战次数</th><th>最好成绩</th></tr>';
      d.levels.forEach(function (l) {
        html += '<tr><td>' + esc(l.title) + '</td><td>' + l.attempts + '</td><td>' +
          (l.best === null ? '—' : l.best + ' 分') + '</td></tr>';
      });
      html += '</table></div>';

      html += '<div class="card"><h2>错题本（' + d.wrongbook.length + '）</h2>';
      if (!d.wrongbook.length) html += '<p class="muted">暂无错题，继续保持。</p>';
      else html += '<p>有 ' + d.wrongbook.length + ' 道错题待消灭。</p>' +
        '<p style="margin-top:12px"><a class="btn" href="#/wrongbook">去错题本重练 →</a></p>';
      html += '</div>';
      app.innerHTML = html;
    });
  }

  /* ── 错题本：独立重练页 ── */
  function renderWrongbook() {
    api('/api/wrongbook').then(function (d) {
      var items = d.items, cur = 0, cleared = 0;
      if (!items.length) {
        app.innerHTML = '<div class="card"><h2>错题本</h2>' +
          '<p class="muted">暂无错题，继续保持。</p>' +
          '<p style="margin-top:14px"><a class="btn ghost" href="#/stats">返回成绩</a></p></div>';
        return;
      }
      function show() {
        if (cur >= items.length) {
          app.innerHTML = '<div class="card"><h2>本轮重练完成！</h2>' +
            '<p>共 ' + items.length + ' 道错题，答对移出 <b class="up">' + cleared + '</b> 道' +
            (cleared < items.length ? '，剩余 <b class="down">' + (items.length - cleared) +
            '</b> 道留在错题本' : '，错题本已清空') + '。</p>' +
            '<p style="margin-top:14px"><a class="btn" href="#/wrongbook">再练一轮</a> ' +
            '<a class="btn ghost" href="#/stats">返回成绩</a></p></div>';
          return;
        }
        var w = items[cur];
        var html = '<div class="card"><div class="progress">错题 ' + (cur + 1) + ' / ' +
          items.length + ' · ' + esc(w.chapter_title) + ' · 已错 ' + w.wrong_count + ' 次</div>' +
          '<div class="quiz-q">' + esc(w.q) + '</div>';
        w.options.forEach(function (o, i) {
          html += '<button class="opt" data-i="' + i + '">' +
            String.fromCharCode(65 + i) + '. ' + esc(o) + '</button>';
        });
        html += '<div id="feedback"></div></div>';
        app.innerHTML = html;
        app.querySelectorAll('.opt').forEach(function (b) {
          b.onclick = function () {
            var chosen = parseInt(b.dataset.i, 10);
            post('/api/answers', { question_id: w.question_id, chosen: chosen }).then(function (r) {
              app.querySelectorAll('.opt').forEach(function (x, i) {
                x.disabled = true;
                if (i === r.answer) x.classList.add('right');
                else if (i === chosen) x.classList.add('wrong');
              });
              if (r.correct) cleared++;
              document.getElementById('feedback').innerHTML =
                '<div class="expl"><b>' + (r.correct ? '✓ 答对了，已移出错题本' :
                '✗ 又错了，正确答案：' + String.fromCharCode(65 + r.answer) + '，继续留在错题本') +
                '</b><br>' + esc(r.explanation) +
                '</div><p style="margin-top:12px"><button class="btn" id="next">' +
                (cur + 1 < items.length ? '下一道' : '查看结果') + '</button></p>';
              document.getElementById('next').onclick = function () { cur++; show(); };
            });
          };
        });
      }
      show();
    });
  }

  /* ── 路由 ── */
  function route() {
    window.onresize = null;
    var h = location.hash || '#/';
    var m;
    if ((m = h.match(/^#\/lesson\/(\d+)/))) renderLesson(m[1]);
    else if ((m = h.match(/^#\/quiz\/(\d+)/))) renderQuiz(m[1]);
    else if ((m = h.match(/^#\/level\/(\d+)/))) renderLevel(m[1]);
    else if (h === '#/levels') renderLevels();
    else if (h === '#/stats') renderStats();
    else if (h === '#/wrongbook') renderWrongbook();
    else renderHome();
  }
  window.addEventListener('hashchange', route);
  route();
})();
