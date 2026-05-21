/**
 * 농산물 가격 예측 시스템 - 메인 JavaScript
 * jQuery + Chart.js 2.x (2021 스타일)
 */

var selectedProduct = null;
var priceChart = null;
var predictionChart = null;
var currentHistoryDays = 90;

// ===== 초기화 =====
$(document).ready(function() {
    console.log('[INIT] 페이지 로드 시작');
    loadProducts();
    updateLastUpdateTime();
    loadDataSourceInfo();
});

// ===== 품목 목록 로드 =====
function loadProducts() {
    $.ajax({
        url: '/api/products',
        method: 'GET',
        dataType: 'json',
        success: function(data) {
            console.log('[/api/products] 응답:', data);
            if (data && data.products && data.products.length > 0) {
                console.log('[/api/products] 첫 품목:', data.products[0]);
                renderProductGrid(data.products);
            } else {
                $('#productGrid').html(
                    '<div class="col-12 text-center text-warning">' +
                    '<i class="fas fa-exclamation-circle"></i> 품목 데이터가 비어 있습니다. (응답: ' +
                    JSON.stringify(data).substring(0, 200) + ')</div>'
                );
            }
        },
        error: function(xhr, status, err) {
            console.error('[/api/products] 실패:', status, err, xhr.responseText);
            $('#productGrid').html(
                '<div class="col-12 text-center text-danger">' +
                '<i class="fas fa-exclamation-triangle"></i> 데이터를 불러올 수 없습니다.<br>' +
                '<small>' + (xhr.responseText || err).substring(0, 300) + '</small>' +
                '</div>'
            );
        }
    });
}

// ===== 품목 그리드 렌더링 =====
function renderProductGrid(products) {
    var html = '';
    $.each(products, function(i, product) {
        var changeClass = 'price-same';
        var changeIcon = 'fas fa-minus';
        var changeText = '0';

        if (product.daily_change > 0) {
            changeClass = 'price-up';
            changeIcon = 'fas fa-caret-up';
            changeText = '+' + numberFormat(product.daily_change);
        } else if (product.daily_change < 0) {
            changeClass = 'price-down';
            changeIcon = 'fas fa-caret-down';
            changeText = numberFormat(product.daily_change);
        }

        html += '<div class="col-6 col-md-4 col-lg-2">' +
            '<div class="product-card" onclick="selectProduct(\'' + product.name + '\')" id="card-' + product.name + '">' +
            '<span class="product-icon">' + product.icon + '</span>' +
            '<div class="product-name">' + product.name + '</div>' +
            '<div class="product-price">' + numberFormat(product.price) + '원</div>' +
            '<div class="product-change ' + changeClass + '">' +
            '<i class="' + changeIcon + '"></i> ' + changeText + '원' +
            '</div>' +
            '</div></div>';
    });
    $('#productGrid').html(html);
}

// ===== 품목 선택 =====
function selectProduct(productName) {
    selectedProduct = productName;

    // 활성 상태 토글
    $('.product-card').removeClass('active');
    $('#card-' + productName).addClass('active');

    // 섹션 표시
    $('#priceOverview').show();
    $('#chartSection').show();
    $('#predictionSection').show();
    $('#predictionEmpty').show();
    $('#predictionTableCard').hide();

    // 데이터 로드
    loadPriceStats(productName);
    loadPriceHistory(productName, currentHistoryDays);

    // 스크롤
    $('html, body').animate({
        scrollTop: $('#priceOverview').offset().top - 80
    }, 500);
}

// ===== 가격 통계 로드 =====
function loadPriceStats(productName) {
    $.ajax({
        url: '/api/statistics/' + encodeURIComponent(productName),
        method: 'GET',
        success: function(data) {
            if (data.success) {
                renderPriceStats(data.statistics);
            }
        }
    });
}

function renderPriceStats(stats) {
    $('#currentPrice').text(numberFormat(stats.current_price));
    $('#avgPrice').text(numberFormat(stats.avg_price));

    // 전일 대비
    var dailyClass = stats.daily_change >= 0 ? 'price-up' : 'price-down';
    var dailyIcon = stats.daily_change >= 0 ? '▲' : '▼';
    if (stats.daily_change == 0) {
        dailyClass = 'price-same';
        dailyIcon = '-';
    }
    $('#dailyChange').attr('class', dailyClass).text(dailyIcon + ' ' + numberFormat(Math.abs(stats.daily_change)) + '원');
    $('#dailyChangePct').attr('class', dailyClass).text('(' + stats.daily_change_pct + '%)');
    $('#dailyChangeCard').removeClass('border-danger border-primary').addClass(
        stats.daily_change > 0 ? 'border-danger' : (stats.daily_change < 0 ? 'border-primary' : '')
    );

    // 전주 대비
    var weeklyClass = stats.weekly_change >= 0 ? 'price-up' : 'price-down';
    var weeklyIcon = stats.weekly_change >= 0 ? '▲' : '▼';
    if (stats.weekly_change == 0) {
        weeklyClass = 'price-same';
        weeklyIcon = '-';
    }
    $('#weeklyChange').attr('class', weeklyClass).text(weeklyIcon + ' ' + numberFormat(Math.abs(stats.weekly_change)) + '원');
    $('#weeklyChangePct').attr('class', weeklyClass).text('(' + stats.weekly_change_pct + '%)');
    $('#weeklyChangeCard').removeClass('border-danger border-primary').addClass(
        stats.weekly_change > 0 ? 'border-danger' : (stats.weekly_change < 0 ? 'border-primary' : '')
    );
}

// ===== 가격 이력 차트 =====
function loadPriceHistory(productName, days) {
    $.ajax({
        url: '/api/history/' + encodeURIComponent(productName) + '?days=' + days,
        method: 'GET',
        dataType: 'json',
        success: function(data) {
            console.log('[/api/history] 응답:', data);
            if (data.success && data.history && data.history.length > 0) {
                renderPriceChart(productName, data.history);
            } else {
                console.warn('[/api/history] 데이터 없음', data);
                if (priceChart) { priceChart.destroy(); priceChart = null; }
                var $canvas = $('#priceChart');
                $canvas.replaceWith('<canvas id="priceChart" height="120"></canvas>');
                $('#chartTitle').text(productName + ' — 데이터 없음');
            }
        },
        error: function(xhr, status, err) {
            console.error('[/api/history] 실패:', status, err, xhr.responseText);
        }
    });
}

function renderPriceChart(productName, history) {
    var labels = [];
    var prices = [];

    $.each(history, function(i, item) {
        labels.push(item.date);
        prices.push(item.price);
    });

    $('#chartTitle').text(productName + ' 가격 추이');

    if (priceChart) {
        priceChart.destroy();
    }

    var ctx = document.getElementById('priceChart').getContext('2d');
    priceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: productName + ' 가격 (원/kg)',
                data: prices,
                borderColor: '#28a745',
                backgroundColor: 'rgba(40, 167, 69, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 5,
                pointHoverBackgroundColor: '#28a745',
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            legend: {
                display: true,
                position: 'top',
                labels: {
                    fontSize: 12,
                    fontFamily: 'Malgun Gothic'
                }
            },
            tooltips: {
                mode: 'index',
                intersect: false,
                callbacks: {
                    label: function(tooltipItem) {
                        return productName + ': ' + numberFormat(tooltipItem.yLabel) + '원';
                    }
                }
            },
            scales: {
                xAxes: [{
                    display: true,
                    gridLines: { display: false },
                    ticks: {
                        maxTicksLimit: 10,
                        fontSize: 11
                    }
                }],
                yAxes: [{
                    display: true,
                    gridLines: { color: 'rgba(0,0,0,0.05)' },
                    ticks: {
                        callback: function(value) {
                            return numberFormat(value) + '원';
                        },
                        fontSize: 11
                    }
                }]
            },
            hover: {
                mode: 'nearest',
                intersect: true
            }
        }
    });
}

// ===== 기간 변경 =====
function changeHistoryRange(days) {
    currentHistoryDays = days;

    // 버튼 활성화 토글
    $('.btn-group .btn').removeClass('active');
    event.target.classList.add('active');

    if (selectedProduct) {
        loadPriceHistory(selectedProduct, days);
    }
}

// ===== 예측 실행 =====
function runPrediction() {
    if (!selectedProduct) {
        alert('품목을 먼저 선택해주세요.');
        return;
    }

    var forecastDays = parseInt($('#forecastPeriod').val());
    var modelType = $('#modelType').val();

    // 로딩 표시
    $('#predictionLoading').show();
    $('#predictionChart').hide();
    $('#predictionEmpty').hide();
    $('#predictionTableCard').hide();
    $('#modelInfo').hide();

    $.ajax({
        url: '/api/predict',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            product_name: selectedProduct,
            forecast_days: forecastDays,
            model_type: modelType
        }),
        success: function(data) {
            $('#predictionLoading').hide();
            $('#predictionChart').show();

            if (data.success) {
                renderPredictionChart(data);
                renderPredictionTable(data.predictions);
                renderModelInfo(data.model_info);
            } else {
                alert('예측에 실패했습니다: ' + (data.error || '데이터 부족'));
            }
        },
        error: function() {
            $('#predictionLoading').hide();
            $('#predictionChart').show();
            alert('서버 오류가 발생했습니다.');
        }
    });
}

// ===== 예측 차트 =====
function renderPredictionChart(data) {
    var labels = [];
    var predicted = [];
    var lower = [];
    var upper = [];

    $.each(data.predictions, function(i, item) {
        labels.push(item.date);
        predicted.push(item.predicted_price);
        lower.push(item.confidence_lower);
        upper.push(item.confidence_upper);
    });

    $('#predictionChartTitle').text(data.product_name + ' 가격 예측 (' + data.forecast_days + '일)');

    if (predictionChart) {
        predictionChart.destroy();
    }

    var ctx = document.getElementById('predictionChart').getContext('2d');
    predictionChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '예측 가격',
                    data: predicted,
                    borderColor: '#dc3545',
                    backgroundColor: 'transparent',
                    borderWidth: 2.5,
                    borderDash: [5, 3],
                    pointRadius: 2,
                    pointBackgroundColor: '#dc3545',
                    fill: false,
                    tension: 0.3
                },
                {
                    label: '신뢰구간 상한 (90%)',
                    data: upper,
                    borderColor: 'rgba(255, 193, 7, 0.5)',
                    backgroundColor: 'rgba(255, 193, 7, 0.1)',
                    borderWidth: 1,
                    borderDash: [3, 3],
                    pointRadius: 0,
                    fill: '+1',
                    tension: 0.3
                },
                {
                    label: '신뢰구간 하한 (90%)',
                    data: lower,
                    borderColor: 'rgba(255, 193, 7, 0.5)',
                    backgroundColor: 'rgba(255, 193, 7, 0.1)',
                    borderWidth: 1,
                    borderDash: [3, 3],
                    pointRadius: 0,
                    fill: false,
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            legend: {
                display: true,
                position: 'top',
                labels: { fontSize: 11, fontFamily: 'Malgun Gothic' }
            },
            tooltips: {
                mode: 'index',
                intersect: false,
                callbacks: {
                    label: function(tooltipItem, chartData) {
                        var label = chartData.datasets[tooltipItem.datasetIndex].label;
                        return label + ': ' + numberFormat(tooltipItem.yLabel) + '원';
                    }
                }
            },
            scales: {
                xAxes: [{
                    display: true,
                    gridLines: { display: false },
                    ticks: { maxTicksLimit: 8, fontSize: 11 }
                }],
                yAxes: [{
                    display: true,
                    gridLines: { color: 'rgba(0,0,0,0.05)' },
                    ticks: {
                        callback: function(value) {
                            return numberFormat(value) + '원';
                        },
                        fontSize: 11
                    }
                }]
            }
        }
    });
}

// ===== 예측 테이블 =====
function renderPredictionTable(predictions) {
    var html = '';
    var prevPrice = null;

    $.each(predictions, function(i, item) {
        var changeHtml = '';
        if (prevPrice !== null) {
            var diff = item.predicted_price - prevPrice;
            var pct = ((diff / prevPrice) * 100).toFixed(1);
            if (diff > 0) {
                changeHtml = '<span class="badge badge-danger badge-change">▲ ' + pct + '%</span>';
            } else if (diff < 0) {
                changeHtml = '<span class="badge badge-primary badge-change">▼ ' + Math.abs(pct) + '%</span>';
            } else {
                changeHtml = '<span class="badge badge-secondary badge-change">- 0%</span>';
            }
        } else {
            changeHtml = '<span class="badge badge-secondary badge-change">-</span>';
        }

        html += '<tr>' +
            '<td>' + item.date + '</td>' +
            '<td class="text-right font-weight-bold">' + numberFormat(item.predicted_price) + '</td>' +
            '<td class="text-right text-muted">' + numberFormat(item.confidence_lower) + '</td>' +
            '<td class="text-right text-muted">' + numberFormat(item.confidence_upper) + '</td>' +
            '<td class="text-center">' + changeHtml + '</td>' +
            '</tr>';

        prevPrice = item.predicted_price;
    });

    $('#predictionTableBody').html(html);
    $('#predictionTableCard').show();
}

// ===== 모델 정보 =====
function renderModelInfo(modelInfo) {
    var html = '';
    html += '<tr><td>모델</td><td>' + (modelInfo.type || '-') + '</td></tr>';
    html += '<tr><td>학습 데이터</td><td>' + (modelInfo.data_points || '-') + '건</td></tr>';

    if (modelInfo.aic) {
        html += '<tr><td>AIC</td><td>' + modelInfo.aic + '</td></tr>';
    }
    if (modelInfo.bic) {
        html += '<tr><td>BIC</td><td>' + modelInfo.bic + '</td></tr>';
    }
    if (modelInfo.ma7) {
        html += '<tr><td>7일 이동평균</td><td>' + numberFormat(modelInfo.ma7) + '원</td></tr>';
    }
    if (modelInfo.ma30) {
        html += '<tr><td>30일 이동평균</td><td>' + numberFormat(modelInfo.ma30) + '원</td></tr>';
    }
    if (modelInfo.trend !== undefined) {
        html += '<tr><td>일일 추세</td><td>' + modelInfo.trend + '원/일</td></tr>';
    }

    $('#modelInfoTable').html(html);
    $('#modelInfo').show();
}

// ===== 데이터 새로고침 =====
function refreshData() {
    var $btn = $('button:contains("데이터 새로고침")');
    $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> 수집 중...');

    $.ajax({
        url: '/api/refresh',
        method: 'POST',
        success: function(data) {
            $btn.prop('disabled', false).html('<i class="fas fa-sync-alt"></i> 데이터 새로고침');
            if (data.success) {
                alert('데이터 업데이트 완료! (' + data.saved + '건)');
                loadProducts();
                updateLastUpdateTime();
                if (selectedProduct) {
                    selectProduct(selectedProduct);
                }
            }
        },
        error: function() {
            $btn.prop('disabled', false).html('<i class="fas fa-sync-alt"></i> 데이터 새로고침');
            alert('데이터 새로고침에 실패했습니다.');
        }
    });
}

// ===== 최종 업데이트 시간 — 서버의 가상 기준일 사용 =====
function updateLastUpdateTime() {
    $.ajax({
        url: '/api/today',
        method: 'GET',
        dataType: 'json',
        success: function(data) {
            $('#lastUpdate').text(data.datetime || data.date || '-');
        },
        error: function() {
            // 폴백: 클라이언트 현재 시간
            var now = new Date();
            var dateStr = now.getFullYear() + '-' +
                padZero(now.getMonth() + 1) + '-' +
                padZero(now.getDate()) + ' ' +
                padZero(now.getHours()) + ':' +
                padZero(now.getMinutes());
            $('#lastUpdate').text(dateStr);
        }
    });
}

// ===== 데이터 소스 정보 =====
function loadDataSourceInfo() {
    $.ajax({
        url: '/api/datasource',
        method: 'GET',
        success: function(data) {
            if (data.success) {
                renderSourceInfo(data.info);
            }
        }
    });
}

function renderSourceInfo(info) {
    var sourceNames = {
        'GARAK': '가락시장 (도매)',
        'KAMIS': 'KAMIS API (소매)',
        'SAMPLE': '샘플 데이터',
    };
    var sourceBadges = {
        'GARAK': 'badge-success',
        'KAMIS': 'badge-info',
        'SAMPLE': 'badge-secondary',
    };

    // 헤더 소스 상태
    var statusHtml = '';
    if (info.has_garak) {
        statusHtml += '<i class="fas fa-check-circle text-success"></i> 가락시장 연결됨 ';
    }
    if (info.has_api_key) {
        statusHtml += '<i class="fas fa-check-circle text-info"></i> KAMIS API 연결됨 ';
    }
    if (!info.has_garak && !info.has_api_key) {
        statusHtml += '<i class="fas fa-info-circle text-warning"></i> 샘플 데이터 사용 중';
    }
    $('#sourceStatus').html(statusHtml);

    // 소스 상세 테이블
    var tableHtml = '';
    if (info.sources && info.sources.length > 0) {
        $.each(info.sources, function(i, src) {
            var name = sourceNames[src.source] || src.source;
            var badge = sourceBadges[src.source] || 'badge-light';
            tableHtml += '<tr>' +
                '<td><span class="badge ' + badge + '">' + name + '</span></td>' +
                '<td><i class="fas fa-check-circle text-success"></i> 활성</td>' +
                '<td>' + numberFormat(src.cnt) + '건</td>' +
                '<td>' + src.min_date + ' ~ ' + src.max_date + '</td>' +
                '</tr>';
        });
    } else {
        tableHtml = '<tr><td colspan="4" class="text-center text-muted">데이터 없음</td></tr>';
    }
    $('#sourceTableBody').html(tableHtml);
}

// ===== 유틸리티 =====
function numberFormat(num) {
    // null, undefined, 빈 문자열, NaN, 비정상 값 모두 '-'로 처리
    if (num === null || num === undefined || num === '') return '-';
    var n = Number(num);
    if (isNaN(n) || !isFinite(n)) return '-';
    return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function padZero(n) {
    return n < 10 ? '0' + n : '' + n;
}
