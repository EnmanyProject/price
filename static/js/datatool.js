/* ============================================================
   CARROT · DATA ACQUISITION TERMINAL — 프론트엔드 제어
   - 실시간 시계/가동시간, 소스 상태 폴링, 인벤토리 매트릭스,
     품질·통계 대시보드, 라이브 수집 콘솔(타이핑 스트림)
   ============================================================ */
(function () {
    'use strict';

    var SOURCE_LABEL = {}; // code → 표시명 (인벤토리 헤더용)
    var STATUS_KO = { UP: '가동', OK: '완료', SYNC: '수집중', IDLE: '대기', STBY: '준비', OFF: '중지' };
    var basisDate = '2022-05-21';
    var bootTs = Date.now();
    var dailyChart = null;

    // 카운터 부드러운 증가용 상태
    var counter = { current: 0, target: 0, raf: null };

    // 콘솔 타이핑 큐
    var conQueue = [];
    var conBusy = false;
    var collecting = false;

    // ---- 유틸 ----
    function fmt(n) { return (n || 0).toLocaleString('en-US'); }
    function pad(n) { return n < 10 ? '0' + n : '' + n; }
    function $(id) { return document.getElementById(id); }

    function statusClass(s) {
        return 's-' + String(s || 'idle').toLowerCase();
    }

    // ============================================================
    // 시계 / 세션
    // ============================================================
    function genSession() {
        var hex = '';
        for (var i = 0; i < 6; i++) hex += Math.floor(Math.random() * 16).toString(16);
        return 'SX-' + hex.toUpperCase();
    }

    function tickClock() {
        var now = new Date();
        $('sysClock').textContent = pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());

        var up = Math.floor((Date.now() - bootTs) / 1000);
        var h = Math.floor(up / 3600), m = Math.floor((up % 3600) / 60), s = up % 60;
        $('stUptime').textContent = pad(h) + ':' + pad(m) + ':' + pad(s);
    }

    // ============================================================
    // 카운터 롤업 (현재값 → 목표값 부드럽게)
    // ============================================================
    function setCounterTarget(v) {
        counter.target = v;
        if (counter.current === 0) counter.current = Math.floor(v * 0.985); // 첫 진입 시 근처에서 시작
        if (!counter.raf) animateCounter();
    }
    function animateCounter() {
        var diff = counter.target - counter.current;
        if (Math.abs(diff) < 1) {
            counter.current = counter.target;
            $('totalRows').textContent = fmt(Math.round(counter.current));
            counter.raf = null;
            return;
        }
        counter.current += diff * 0.08;
        $('totalRows').textContent = fmt(Math.round(counter.current));
        counter.raf = requestAnimationFrame(animateCounter);
    }

    // ============================================================
    // [A] SOURCES
    // ============================================================
    function renderSources(data) {
        var list = $('srcList');
        var html = '';
        data.sources.forEach(function (s) {
            SOURCE_LABEL[s.code] = s.name;
            var sc = statusClass(s.status);
            var isDemo = s.kind === 'demo';
            var lat = (s.latency_ms === null || s.latency_ms === undefined)
                ? '<span class="c-lat none">—</span>'
                : '<span class="c-lat">' + s.latency_ms + 'ms</span>';
            var syncBar = (s.status === 'SYNC' && s.progress != null)
                ? '<span class="sync-bar" style="width:' + s.progress + '%"></span>' : '';
            html += '' +
                '<li class="src-row' + (isDemo ? ' is-demo' : '') + '">' +
                    '<span class="c-led ' + sc + '"></span>' +
                    '<span class="c-name">' +
                        '<span class="nm"><span class="code">' + s.code + '</span>' + s.name + '</span>' +
                        '<span class="sub"><span class="st ' + sc + '">' + (STATUS_KO[s.status] || s.status) + '</span>' +
                            '<span>' + (s.region || '') + '</span></span>' +
                    '</span>' +
                    '<span class="c-proto">' + s.protocol + '</span>' +
                    lat +
                    '<span class="c-rows">' + fmt(s.rows) + '</span>' +
                    syncBar +
                '</li>';
        });
        list.innerHTML = html;

        $('sourcesAux').textContent = data.summary.up + ' / ' + data.summary.total + ' 가동';
        $('stSources').textContent = data.summary.total;
        $('stUp').textContent = data.summary.up;
        $('basisDate').textContent = data.summary.date;
        basisDate = data.summary.date;
    }

    // ============================================================
    // [C] INVENTORY MATRIX
    // ============================================================
    function renderInventory(data) {
        var codes = data.sources;

        var thead = '<tr><th class="col-prod">품목</th>';
        codes.forEach(function (c) {
            thead += '<th class="' + (c.kind === 'demo' ? 'is-demo' : '') + '">' +
                        '<span class="code">' + c.code + '</span>' +
                        '<span class="kind">' + (c.kind === 'demo' ? '확장' : '실시간') + '</span>' +
                     '</th>';
        });
        thead += '<th class="col-tot">합계</th></tr>';
        $('invHead').innerHTML = thead;

        var body = '';
        data.rows.forEach(function (r) {
            var chg = r.change_pct;
            var chgCls = chg > 0 ? 'up' : (chg < 0 ? 'down' : 'flat');
            var chgArrow = chg > 0 ? '▲' : (chg < 0 ? '▼' : '·');
            body += '<tr>';
            body += '<td class="col-prod">' +
                        r.product +
                        '<span class="p-price">' + fmt(r.price) + '원</span>' +
                        '<span class="chg ' + chgCls + '">' + chgArrow + Math.abs(chg).toFixed(1) + '%</span>' +
                    '</td>';
            codes.forEach(function (c) {
                var v = r.cells[c.code] || 0;
                var cls = v === 0 ? 'zero' : (v > 1000 ? 'hot' : '');
                body += '<td class="inv-cell ' + cls + '">' + (v === 0 ? '—' : fmt(v)) + '</td>';
            });
            body += '<td class="col-tot">' + fmt(r.total) + '</td>';
            body += '</tr>';
        });

        // 합계 행
        body += '<tr class="inv-foot"><td class="col-prod">Σ 총계</td>';
        codes.forEach(function (c) {
            body += '<td>' + fmt(data.col_totals[c.code] || 0) + '</td>';
        });
        body += '<td>' + fmt(data.grand_total) + '</td></tr>';

        $('invBody').innerHTML = body;
        $('invAux').textContent = fmt(data.grand_total) + ' 건';
    }

    // ============================================================
    // [D] STATS / QUALITY
    // ============================================================
    function renderStats(data) {
        setCounterTarget(data.total_rows);
        $('rowsBreakdown').textContent = '실시간 ' + fmt(data.real_rows) + ' · 확장 ' + fmt(data.demo_rows);
        $('stTotal').textContent = fmt(data.total_rows);
        $('statsAux').textContent = '기준 ' + data.as_of;

        var q = data.quality;
        $('gCoverage').style.width = q.coverage_pct + '%';
        $('vCoverage').textContent = q.coverage_pct + '%';
        $('gComplete').style.width = q.completeness_pct + '%';
        $('vComplete').textContent = q.completeness_pct + '%';
        $('vFresh').textContent = q.freshness_days === 0 ? '실시간' : (q.freshness_days + '일');
        $('vProducts').textContent = data.products;

        renderDailyChart(data.daily);
    }

    function renderDailyChart(daily) {
        var labels = daily.map(function (d) { return d.date.slice(5); });
        var vals = daily.map(function (d) { return d.count; });

        if (dailyChart) {
            dailyChart.data.labels = labels;
            dailyChart.data.datasets[0].data = vals;
            dailyChart.update();
            return;
        }

        var ctx = $('dailyChart').getContext('2d');
        var grad = ctx.createLinearGradient(0, 0, 0, 104);
        grad.addColorStop(0, 'rgba(245,166,35,0.95)');
        grad.addColorStop(1, 'rgba(245,166,35,0.25)');

        dailyChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    data: vals,
                    backgroundColor: grad,
                    borderWidth: 0,
                    barPercentage: 0.82,
                    categoryPercentage: 0.92
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                legend: { display: false },
                tooltip: { enabled: true },
                animation: { duration: 600 },
                scales: {
                    xAxes: [{
                        gridLines: { display: false, drawBorder: false },
                        ticks: {
                            fontColor: '#424c57', fontSize: 8,
                            fontFamily: "'IBM Plex Mono', monospace",
                            maxTicksLimit: 8, autoSkip: true, maxRotation: 0
                        }
                    }],
                    yAxes: [{
                        gridLines: { color: '#151c23', zeroLineColor: '#151c23', drawBorder: false },
                        ticks: {
                            fontColor: '#424c57', fontSize: 8,
                            fontFamily: "'IBM Plex Mono', monospace",
                            maxTicksLimit: 4, beginAtZero: true,
                            callback: function (v) { return v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v; }
                        }
                    }]
                },
                tooltips: {
                    backgroundColor: '#11171e', borderColor: '#2b353f', borderWidth: 1,
                    titleFontFamily: "'IBM Plex Mono', monospace",
                    bodyFontFamily: "'IBM Plex Mono', monospace",
                    bodyFontColor: '#f5a623', titleFontColor: '#6c7884',
                    callbacks: {
                        label: function (item) { return fmt(item.yLabel) + '건'; }
                    }
                }
            }
        });
    }

    // ============================================================
    // [B] CONSOLE — 타이핑 스트림
    // ============================================================
    function conAppend(line, fresh) {
        var box = $('console');
        var div = document.createElement('div');
        div.className = 'con-line con-' + (line.lvl || 'info') + (fresh ? ' fresh' : '');
        div.textContent = line.text;
        box.appendChild(div);
        box.scrollTop = box.scrollHeight;
        // 너무 길면 오래된 줄 정리
        while (box.children.length > 240) box.removeChild(box.firstChild);
    }

    function pumpConsole() {
        if (conBusy) return;
        if (!conQueue.length) { conBusy = false; return; }
        conBusy = true;
        var line = conQueue.shift();
        conAppend(line, true);
        var base = line.lvl === 'cmd' ? 180 : 90;
        var delay = base + Math.random() * 130;
        setTimeout(function () { conBusy = false; pumpConsole(); }, delay);
    }

    function streamLines(lines) {
        lines.forEach(function (l) { conQueue.push(l); });
        pumpConsole();
    }

    function runCollect() {
        if (collecting) return;
        collecting = true;
        var btn = $('runCollect');
        btn.disabled = true;
        $('conCursor').textContent = '▋';

        fetch('/api/datatool/collect', { method: 'POST' })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                streamLines(data.lines);
                // 콘솔이 다 흐른 뒤 버튼 복구 + 데이터 갱신
                var wait = data.lines.length * 230 + 400;
                setTimeout(function () {
                    btn.disabled = false;
                    collecting = false;
                    refreshAll();
                }, wait);
            })
            .catch(function () {
                streamLines([{ lvl: 'warn', text: '[err] collect endpoint unreachable.' }]);
                btn.disabled = false;
                collecting = false;
            });
    }

    // ============================================================
    // 폴링
    // ============================================================
    function refreshSources() {
        fetch('/api/datatool/sources').then(function (r) { return r.json(); })
            .then(renderSources).catch(function () {});
    }
    function refreshInventory() {
        fetch('/api/datatool/inventory').then(function (r) { return r.json(); })
            .then(renderInventory).catch(function () {});
    }
    function refreshStats() {
        fetch('/api/datatool/stats').then(function (r) { return r.json(); })
            .then(renderStats).catch(function () {});
    }
    function refreshAll() { refreshSources(); refreshInventory(); refreshStats(); }

    // ============================================================
    // 부팅
    // ============================================================
    function boot() {
        $('sessionId').textContent = genSession();
        tickClock();
        setInterval(tickClock, 1000);

        refreshAll();
        setInterval(refreshSources, 3000);    // 상태/지연은 자주
        setInterval(refreshStats, 5000);      // 카운터/품질
        setInterval(refreshInventory, 9000);  // 매트릭스는 덜 자주

        // 첫 진입 자동 수집 로그 (활동감)
        setTimeout(function () {
            fetch('/api/datatool/collect', { method: 'POST' })
                .then(function (r) { return r.json(); })
                .then(function (data) { streamLines(data.lines); })
                .catch(function () {});
        }, 700);

        // RUN COLLECT 버튼 / R 단축키
        $('runCollect').addEventListener('click', runCollect);
        document.addEventListener('keydown', function (e) {
            if ((e.key === 'r' || e.key === 'R') && !e.ctrlKey && !e.metaKey &&
                document.activeElement.tagName !== 'INPUT') {
                runCollect();
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
