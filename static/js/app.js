/**
 * ARANG · PRICE — 농산물 가격 인사이트
 * 디자인: 아랑 회사 홈(arang.net)과 통일된 톤
 */

var selectedProduct = null;
var priceChart = null;
var predictionChart = null;
var currentHistoryDays = 90;

// 차트 색상 토큰 (CSS 변수와 일치)
var COLOR = {
  pine: '#16352A',
  leaf: '#6FA838',
  leafBright: '#8FC74A',
  mint: '#EAF2E2',
  gold: '#C8912E',
  red: '#C44545',
  blue: '#4A6CA8',
  muted: '#5E6B62',
  line: '#E2E7DE',
};

$(document).ready(function() {
  console.log('[INIT] 페이지 로드');

  // 헤더 스크롤 감지
  var $header = $('#header');
  function onScroll() { $header.toggleClass('scrolled', window.scrollY > 40); }
  onScroll();
  $(window).on('scroll', onScroll);

  // 햄버거 메뉴
  var $burger = $('#burger'), $menu = $('#menu');
  $burger.on('click', function() { $menu.toggleClass('open'); });
  $menu.find('a').on('click', function() { $menu.removeClass('open'); });

  // 푸터 연도
  $('#ftYear').text(new Date().getFullYear());

  // 차트 글로벌 디폴트
  if (window.Chart) {
    Chart.defaults.global.defaultFontFamily = "'Pretendard', sans-serif";
    Chart.defaults.global.defaultFontColor = COLOR.muted;
    Chart.defaults.global.defaultFontSize = 11;
  }

  loadProducts();
  updateLastUpdateTime();
  loadDataSourceInfo();
});

// ============================================================
// 품목 목록
// ============================================================
function loadProducts() {
  $.ajax({
    url: '/api/products', method: 'GET', dataType: 'json',
    success: function(data) {
      if (data && data.products && data.products.length > 0) {
        renderProductGrid(data.products);
      } else {
        $('#productGrid').html('<div class="grid-loading">품목 데이터가 비어 있습니다.</div>');
      }
    },
    error: function(xhr, status, err) {
      console.error('[/api/products] 실패:', status, err);
      $('#productGrid').html('<div class="grid-loading">데이터를 불러올 수 없습니다.</div>');
    }
  });
}

function renderProductGrid(products) {
  var html = '';
  $.each(products, function(i, product) {
    var changeClass = 'price-same';
    var changeText = '0원';
    if (product.daily_change > 0) {
      changeClass = 'price-up';
      changeText = '▲ ' + numberFormat(product.daily_change) + '원';
    } else if (product.daily_change < 0) {
      changeClass = 'price-down';
      changeText = '▼ ' + numberFormat(Math.abs(product.daily_change)) + '원';
    }
    var iconHtml = product.icon && product.icon.charAt(0) === '/'
      ? '<img class="product-icon" src="' + product.icon + '" alt="' + product.name + '">'
      : '<div class="product-icon">' + (product.icon || '') + '</div>';
    html += '<button type="button" class="product-card" onclick="selectProduct(\'' + product.name + '\')" id="card-' + product.name + '">' +
      iconHtml +
      '<div class="product-name">' + product.name + '</div>' +
      '<div class="product-price">' + numberFormat(product.price) + '원</div>' +
      '<div class="product-change ' + changeClass + '">' + changeText + '</div>' +
      '</button>';
  });
  $('#productGrid').html(html);
}

// ============================================================
// 품목 선택
// ============================================================
function selectProduct(productName) {
  selectedProduct = productName;
  $('.product-card').removeClass('active');
  $('#card-' + productName).addClass('active');

  $('#priceOverview').show();
  $('#chartSection').show();
  $('#predictionSection').show();
  $('#predictionEmpty').show();
  $('#predictionTableCard').hide();

  loadPriceStats(productName);
  loadPriceHistory(productName, currentHistoryDays);

  $('html, body').animate({ scrollTop: $('#priceOverview').offset().top - 80 }, 500);
}

// ============================================================
// 가격 통계
// ============================================================
function loadPriceStats(productName) {
  $.ajax({
    url: '/api/statistics/' + encodeURIComponent(productName),
    method: 'GET',
    success: function(data) { if (data.success) renderPriceStats(data.statistics); }
  });
}

function renderPriceStats(stats) {
  $('#currentPrice').text(numberFormat(stats.current_price));
  $('#avgPrice').text(numberFormat(stats.avg_price));

  function applyChange(valueEl, pctEl, cardEl, change, changePct) {
    var $c = $(cardEl).removeClass('up down');
    var sign = change > 0 ? '▲' : (change < 0 ? '▼' : '—');
    if (change > 0) $c.addClass('up');
    else if (change < 0) $c.addClass('down');
    $(valueEl).text(sign + ' ' + numberFormat(Math.abs(change)) + '원');
    $(pctEl).text('(' + changePct + '%)');
  }
  applyChange('#dailyChange', '#dailyChangePct', '#dailyChangeCard', stats.daily_change, stats.daily_change_pct);
  applyChange('#weeklyChange', '#weeklyChangePct', '#weeklyChangeCard', stats.weekly_change, stats.weekly_change_pct);
}

// ============================================================
// 가격 이력 차트
// ============================================================
function loadPriceHistory(productName, days) {
  $.ajax({
    url: '/api/history/' + encodeURIComponent(productName) + '?days=' + days,
    method: 'GET', dataType: 'json',
    success: function(data) {
      if (data.success && data.history && data.history.length > 0) {
        renderPriceChart(productName, data.history);
      } else {
        if (priceChart) { priceChart.destroy(); priceChart = null; }
        $('#chartTitle').text(productName + ' — 데이터 없음');
      }
    }
  });
}

function renderPriceChart(productName, history) {
  var labels = [], prices = [];
  $.each(history, function(i, item) { labels.push(item.date); prices.push(item.price); });

  $('#chartTitle').text(productName + ' 가격 추이');
  if (priceChart) priceChart.destroy();

  var ctx = document.getElementById('priceChart').getContext('2d');
  // gradient fill
  var grad = ctx.createLinearGradient(0, 0, 0, 320);
  grad.addColorStop(0, 'rgba(111,168,56,0.22)');
  grad.addColorStop(1, 'rgba(111,168,56,0)');

  priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: productName + ' (원/kg)',
        data: prices,
        borderColor: COLOR.pine,
        backgroundColor: grad,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBackgroundColor: COLOR.pine,
        pointHoverBorderColor: '#fff',
        pointHoverBorderWidth: 2,
        fill: true,
        tension: 0.3,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      legend: { display: false },
      tooltips: {
        mode: 'index', intersect: false,
        backgroundColor: COLOR.pine, titleFontFamily: "'Pretendard',sans-serif",
        bodyFontFamily: "'Pretendard',sans-serif", cornerRadius: 8, padding: 12,
        callbacks: { label: function(t) { return numberFormat(t.yLabel) + '원'; } }
      },
      scales: {
        xAxes: [{ gridLines: { display: false }, ticks: { maxTicksLimit: 10, fontSize: 11, fontColor: COLOR.muted } }],
        yAxes: [{ gridLines: { color: COLOR.line, drawBorder: false }, ticks: { callback: function(v){ return numberFormat(v); }, fontSize: 11, fontColor: COLOR.muted } }]
      },
      hover: { mode: 'nearest', intersect: true }
    }
  });
}

function changeHistoryRange(days, btn) {
  currentHistoryDays = days;
  $('.range-tab').removeClass('active');
  if (btn) btn.classList.add('active');
  if (selectedProduct) loadPriceHistory(selectedProduct, days);
}

// ============================================================
// 예측
// ============================================================
function runPrediction() {
  if (!selectedProduct) { alert('품목을 먼저 선택해주세요.'); return; }
  var forecastDays = parseInt($('#forecastPeriod').val());
  var modelType = $('#modelType').val();

  $('#predictionLoading').show();
  $('#predictionEmpty').hide();
  $('#predictionTableCard').hide();
  $('#modelInfo').hide();

  $.ajax({
    url: '/api/predict', method: 'POST', contentType: 'application/json',
    data: JSON.stringify({ product_name: selectedProduct, forecast_days: forecastDays, model_type: modelType }),
    success: function(data) {
      $('#predictionLoading').hide();
      if (data.success) {
        renderPredictionChart(data);
        renderPredictionTable(data.predictions);
        renderModelInfo(data.model_info);
      } else {
        alert('예측 실패: ' + (data.error || '데이터 부족'));
      }
    },
    error: function() {
      $('#predictionLoading').hide();
      alert('서버 오류가 발생했습니다.');
    }
  });
}

function renderPredictionChart(data) {
  var labels = [], predicted = [], lower = [], upper = [];
  $.each(data.predictions, function(i, item) {
    labels.push(item.date);
    predicted.push(item.predicted_price);
    lower.push(item.confidence_lower);
    upper.push(item.confidence_upper);
  });

  $('#predictionChartTitle').text(data.product_name + ' 가격 예측 · ' + data.forecast_days + '일');
  if (predictionChart) predictionChart.destroy();

  var ctx = document.getElementById('predictionChart').getContext('2d');
  predictionChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: '예측가',
          data: predicted,
          borderColor: COLOR.pine,
          backgroundColor: 'transparent',
          borderWidth: 2.5,
          pointRadius: 2,
          pointBackgroundColor: COLOR.pine,
          fill: false, tension: 0.3,
        },
        {
          label: '신뢰구간 상한 (90%)',
          data: upper,
          borderColor: 'rgba(111,168,56,0.4)',
          backgroundColor: 'rgba(143,199,74,0.15)',
          borderWidth: 1, borderDash: [3,3],
          pointRadius: 0, fill: '+1', tension: 0.3,
        },
        {
          label: '신뢰구간 하한 (90%)',
          data: lower,
          borderColor: 'rgba(111,168,56,0.4)',
          backgroundColor: 'transparent',
          borderWidth: 1, borderDash: [3,3],
          pointRadius: 0, fill: false, tension: 0.3,
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      legend: { display: true, position: 'top', labels: { fontColor: COLOR.muted, fontSize: 11, boxWidth: 12 } },
      tooltips: {
        mode: 'index', intersect: false,
        backgroundColor: COLOR.pine, cornerRadius: 8, padding: 12,
        callbacks: { label: function(t, d) { return d.datasets[t.datasetIndex].label + ': ' + numberFormat(t.yLabel) + '원'; } }
      },
      scales: {
        xAxes: [{ gridLines: { display: false }, ticks: { maxTicksLimit: 8, fontSize: 11, fontColor: COLOR.muted } }],
        yAxes: [{ gridLines: { color: COLOR.line, drawBorder: false }, ticks: { callback: function(v){ return numberFormat(v); }, fontSize: 11, fontColor: COLOR.muted } }]
      }
    }
  });
}

function renderPredictionTable(predictions) {
  var html = '';
  var prev = null;
  $.each(predictions, function(i, item) {
    var chip = '<span class="pchip same">—</span>';
    if (prev !== null) {
      var diff = item.predicted_price - prev;
      var pct = ((diff / prev) * 100).toFixed(1);
      if (diff > 0) chip = '<span class="pchip up">▲ ' + pct + '%</span>';
      else if (diff < 0) chip = '<span class="pchip down">▼ ' + Math.abs(pct) + '%</span>';
      else chip = '<span class="pchip same">— 0%</span>';
    }
    html += '<tr>' +
      '<td>' + item.date + '</td>' +
      '<td class="r"><b>' + numberFormat(item.predicted_price) + '</b></td>' +
      '<td class="r" style="color:var(--muted)">' + numberFormat(item.confidence_lower) + '</td>' +
      '<td class="r" style="color:var(--muted)">' + numberFormat(item.confidence_upper) + '</td>' +
      '<td class="c">' + chip + '</td>' +
      '</tr>';
    prev = item.predicted_price;
  });
  $('#predictionTableBody').html(html);
  $('#predictionTableCard').show();
}

function renderModelInfo(modelInfo) {
  var html = '';
  html += '<tr><td>모델</td><td>' + (modelInfo.type || '—') + '</td></tr>';
  html += '<tr><td>학습 데이터</td><td>' + (modelInfo.data_points || '—') + '건</td></tr>';
  if (modelInfo.models_used) html += '<tr><td>참여 모델</td><td>' + modelInfo.models_used.length + '개</td></tr>';
  if (modelInfo.ma7 !== undefined) html += '<tr><td>7일 이동평균</td><td>' + numberFormat(modelInfo.ma7) + '원</td></tr>';
  if (modelInfo.ma30 !== undefined) html += '<tr><td>30일 이동평균</td><td>' + numberFormat(modelInfo.ma30) + '원</td></tr>';
  if (modelInfo.trend !== undefined) html += '<tr><td>일일 추세</td><td>' + modelInfo.trend + ' 원/일</td></tr>';
  if (modelInfo.season_range !== undefined) html += '<tr><td>계절성 진폭</td><td>' + (modelInfo.season_range * 100).toFixed(1) + '%</td></tr>';
  if (modelInfo.season_peak_month) html += '<tr><td>최고가 월</td><td>' + modelInfo.season_peak_month + '월</td></tr>';
  if (modelInfo.season_low_month) html += '<tr><td>최저가 월</td><td>' + modelInfo.season_low_month + '월</td></tr>';
  if (modelInfo.weather_context && modelInfo.weather_context.avg_temp != null) {
    html += '<tr><td>최근 평균기온</td><td>' + modelInfo.weather_context.avg_temp + '℃</td></tr>';
    if (modelInfo.weather_adj_pct !== undefined) html += '<tr><td>기상 보정</td><td>' + modelInfo.weather_adj_pct + '%</td></tr>';
    if (modelInfo.learned_elasticity !== undefined && modelInfo.learned_elasticity !== null) {
      html += '<tr><td>학습 elasticity</td><td>' + modelInfo.learned_elasticity + ' %/℃</td></tr>';
    }
  }
  $('#modelInfoTable').html(html);
  $('#modelInfo').show();
}

// ============================================================
// 새로고침
// ============================================================
function refreshData() {
  var $btn = $('#refreshBtn');
  $btn.prop('disabled', true).text('수집 중…');
  $.ajax({
    url: '/api/refresh', method: 'POST',
    success: function(data) {
      $btn.prop('disabled', false).text('새로고침');
      if (data.success) {
        loadProducts();
        updateLastUpdateTime();
        if (selectedProduct) selectProduct(selectedProduct);
      }
    },
    error: function() {
      $btn.prop('disabled', false).text('새로고침');
      alert('새로고침에 실패했습니다.');
    }
  });
}

// ============================================================
// 기준일 / 데이터 소스
// ============================================================
function updateLastUpdateTime() {
  $.ajax({
    url: '/api/today', method: 'GET', dataType: 'json',
    success: function(data) { $('#lastUpdate').text(data.date || '—'); },
    error: function() {
      var n = new Date();
      $('#lastUpdate').text(n.getFullYear() + '-' + padZero(n.getMonth()+1) + '-' + padZero(n.getDate()));
    }
  });
}

function loadDataSourceInfo() {
  $.ajax({
    url: '/api/datasource', method: 'GET',
    success: function(data) { if (data.success) renderSourceInfo(data.info); }
  });
}

function renderSourceInfo(info) {
  var sourceNames = {
    'GARAK': '가락시장 (도매)',
    'KAMIS': 'KAMIS (소매)',
    'SAMPLE': '샘플 데이터 (폴백)',
  };

  // 헤더 상태 칩
  var status;
  if (info.has_api_key) status = 'KAMIS 연결됨';
  else if (info.has_garak) status = '가락시장 연결됨';
  else status = '샘플 모드';
  $('#sourceStatus').text(status);

  // 소스 테이블
  var html = '';
  if (info.sources && info.sources.length > 0) {
    $.each(info.sources, function(i, src) {
      html += '<tr>' +
        '<td><span class="src-badge">' + (sourceNames[src.source] || src.source) + '</span></td>' +
        '<td><span class="src-on">활성</span></td>' +
        '<td class="r"><b>' + numberFormat(src.cnt) + '</b> 건</td>' +
        '<td style="color:var(--muted);font-size:13px">' + (src.min_date || '—') + ' ~ ' + (src.max_date || '—') + '</td>' +
        '</tr>';
    });
  } else {
    html = '<tr><td colspan="4" class="loading-row">데이터 없음</td></tr>';
  }
  $('#sourceTableBody').html(html);
}

// ============================================================
// 유틸
// ============================================================
function numberFormat(num) {
  if (num === null || num === undefined || num === '') return '—';
  var n = Number(num);
  if (isNaN(n) || !isFinite(n)) return '—';
  return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function padZero(n) { return n < 10 ? '0' + n : '' + n; }
