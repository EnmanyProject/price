# -*- coding: utf-8 -*-
"""
농산물 가격 예측 모듈 (경량 버전)

Vercel 서버리스 250MB 한도를 위해 numpy/pandas/statsmodels 제거
순수 Python + math 만으로 예측 수행

- 가중이동평균 예측
- 선형회귀 추세 예측
- 지수평활법 (순수 Python 구현)
"""

import math
from datetime import datetime, timedelta
from data_collector import get_price_history
from database import get_db

# 품목별 기상 elasticity (도메인 추정 — 실증 데이터 누적되면 회귀로 대체)
# 단위: 평균기온 1℃ 편차 → 가격 변동률(%)
_TEMP_ELASTICITY = {
    '배추': -0.8,    # 잎채소 — 폭염에 약함(웃자람·무름병) → 공급 감소 → 가격↑
    '시금치': -1.0,
    '상추': -0.9,
    '대파': -0.5,
    '고추': 0.3,     # 과채류 — 적정 고온에 생육 양호
    '토마토': 0.4,
    '오이': 0.3,
    '무': -0.3,
    '양파': -0.2,
    '감자': -0.4,
    '사과': -0.1,    # 영향 적음
}


def _mean(values):
    return sum(values) / len(values) if values else 0


def _std(values):
    if len(values) < 2:
        return 0
    m = _mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / len(values))


def _weather_context(days_back=30, station='서울'):
    """최근 N일 weather 요약 — weather 테이블 비어있으면 None"""
    try:
        from weather_collector import get_weather_for_date
    except ImportError:
        return None

    today = datetime.now()
    temps, rains = [], []
    for d in range(days_back):
        day = today - timedelta(days=d)
        w = get_weather_for_date(day.strftime('%Y-%m-%d'), station=station)
        if not w:
            continue
        if w.get('avg_temp') is not None:
            temps.append(w['avg_temp'])
        if w.get('precipitation') is not None:
            rains.append(w['precipitation'])

    if not temps:
        return None

    return {
        'station': station,
        'days_back': days_back,
        'days_with_data': len(temps),
        'avg_temp': round(_mean(temps), 1),
        'total_rain': round(sum(rains), 1),
    }


def _learn_temp_elasticity(product_name, days=365):
    """
    과거 가격·기온 단순 회귀로 품목별 elasticity 학습.
    실패하면 _TEMP_ELASTICITY 도메인 추정값 반환.
    반환: %/℃ (가격 변동률 per ℃)
    """
    try:
        from weather_collector import get_weather_for_date
    except ImportError:
        return _TEMP_ELASTICITY.get(product_name, 0.0)

    dates, prices = prepare_price_series(product_name, days=days)
    if not prices or len(prices) < 60:
        return _TEMP_ELASTICITY.get(product_name, 0.0)

    pairs = []
    for d, p in zip(dates, prices):
        w = get_weather_for_date(d, station='서울')
        if w and w.get('avg_temp') is not None and p > 0:
            pairs.append((w['avg_temp'], p))

    if len(pairs) < 30:
        return _TEMP_ELASTICITY.get(product_name, 0.0)

    n = len(pairs)
    tx = [t for t, _ in pairs]
    ty = [p for _, p in pairs]
    tmean = sum(tx) / n
    ymean = sum(ty) / n
    num = sum((tx[i] - tmean) * (ty[i] - ymean) for i in range(n))
    den = sum((tx[i] - tmean) ** 2 for i in range(n))
    if den == 0 or ymean == 0:
        return _TEMP_ELASTICITY.get(product_name, 0.0)

    slope = num / den       # 원/℃
    elasticity = (slope / ymean) * 100  # %/℃
    # 비현실적 값(±5% 초과)이면 도메인 값으로 후퇴
    if abs(elasticity) > 5.0:
        return _TEMP_ELASTICITY.get(product_name, 0.0)
    return round(elasticity, 3)


def _apply_weather_adjustment(product_name, base_price, weather_ctx, elasticity=None):
    """
    weather 시그널로 예측가 보정 — 평년 대비 편차만큼 elasticity 적용
    elasticity=None이면 _TEMP_ELASTICITY 또는 학습값 사용
    """
    if not weather_ctx or weather_ctx.get('days_with_data', 0) < 10:
        return base_price, 0.0

    # 평년 기준 — 6월 서울 ASOS 30년 평균(약 22℃). 데모용 상수.
    normal_temp = 22.0
    temp_dev = weather_ctx['avg_temp'] - normal_temp
    if elasticity is None:
        elasticity = _TEMP_ELASTICITY.get(product_name, 0.0)
    adj_pct = temp_dev * elasticity  # %
    # 보정폭은 ±15%로 제한 — 도메인 추정값이라 폭주 방지
    adj_pct = max(-15.0, min(15.0, adj_pct))
    adjusted = base_price * (1 + adj_pct / 100)
    return adjusted, round(adj_pct, 2)


def prepare_price_series(product_name, days=365):
    """가격 데이터를 날짜순 리스트로 준비"""
    history = get_price_history(product_name, days)
    if not history:
        return None, None

    # 날짜순 정렬 + 중복 제거
    seen = {}
    for row in history:
        seen[row['date']] = row['price']

    sorted_dates = sorted(seen.keys())
    dates = sorted_dates
    prices = [seen[d] for d in sorted_dates]

    # 결측치 선형 보간
    if len(prices) >= 2:
        full_dates = []
        full_prices = []
        start = datetime.strptime(dates[0], '%Y-%m-%d')
        end = datetime.strptime(dates[-1], '%Y-%m-%d')
        day_count = (end - start).days + 1

        price_map = dict(zip(dates, prices))

        for i in range(day_count):
            d = (start + timedelta(days=i)).strftime('%Y-%m-%d')
            full_dates.append(d)
            if d in price_map:
                full_prices.append(price_map[d])
            else:
                full_prices.append(None)

        # 선형 보간
        for i in range(len(full_prices)):
            if full_prices[i] is None:
                # 앞뒤로 값 찾기
                prev_idx = i - 1
                while prev_idx >= 0 and full_prices[prev_idx] is None:
                    prev_idx -= 1
                next_idx = i + 1
                while next_idx < len(full_prices) and full_prices[next_idx] is None:
                    next_idx += 1

                if prev_idx >= 0 and next_idx < len(full_prices):
                    ratio = (i - prev_idx) / (next_idx - prev_idx)
                    full_prices[i] = full_prices[prev_idx] + ratio * (full_prices[next_idx] - full_prices[prev_idx])
                elif prev_idx >= 0:
                    full_prices[i] = full_prices[prev_idx]
                elif next_idx < len(full_prices):
                    full_prices[i] = full_prices[next_idx]

        # None 제거
        clean_dates = []
        clean_prices = []
        for d, p in zip(full_dates, full_prices):
            if p is not None:
                clean_dates.append(d)
                clean_prices.append(p)

        return clean_dates, clean_prices

    return dates, prices


def predict_arima(product_name, forecast_days=30):
    """선형회귀 추세 + 이동평균 예측 (ARIMA 대체)"""
    dates, prices = prepare_price_series(product_name, days=730)
    if not prices or len(prices) < 30:
        return predict_moving_average(product_name, forecast_days)

    n = len(prices)

    # 선형회귀로 추세 계산
    x_mean = (n - 1) / 2
    y_mean = _mean(prices)
    numerator = sum((i - x_mean) * (prices[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = numerator / denominator if denominator != 0 else 0

    # 최근 30일 잔차의 표준편차
    recent = prices[-30:]
    residuals = []
    for i, p in enumerate(recent):
        expected = y_mean + slope * (n - 30 + i - x_mean)
        residuals.append(p - expected)
    std_resid = _std(residuals)

    # 가중이동평균 (최근 데이터에 더 큰 가중치)
    ma7 = _mean(prices[-7:])
    ma30 = _mean(prices[-30:])

    last_date = datetime.strptime(dates[-1], '%Y-%m-%d')
    last_price = prices[-1]

    weather_ctx = _weather_context()
    learned_elasticity = _learn_temp_elasticity(product_name)
    weather_adj_pct = 0.0

    results = []
    for i in range(forecast_days):
        pred_date = last_date + timedelta(days=i + 1)

        # 추세 + 가중이동평균 혼합
        trend_component = slope * (i + 1)
        base = ma7 * 0.5 + ma30 * 0.3 + last_price * 0.2
        pred_price = base + trend_component
        pred_price = max(pred_price, 0)

        # weather 보정 (학습된 elasticity 우선, 데이터 없으면 도메인값)
        pred_price, weather_adj_pct = _apply_weather_adjustment(
            product_name, pred_price, weather_ctx, learned_elasticity,
        )

        # 신뢰구간 (90%)
        margin = std_resid * 1.645 * math.sqrt(i + 1) * 0.5

        results.append({
            'date': pred_date.strftime('%Y-%m-%d'),
            'predicted_price': round(pred_price, 0),
            'confidence_lower': round(max(pred_price - margin, 0), 0),
            'confidence_upper': round(pred_price + margin, 0),
            'model': 'TrendMA',
        })

    return {
        'product_name': product_name,
        'forecast_days': forecast_days,
        'predictions': results,
        'model_info': {
            'type': '추세 + 가중이동평균',
            'trend': round(slope, 2),
            'ma7': round(ma7, 0),
            'ma30': round(ma30, 0),
            'data_points': n,
            'weather_context': weather_ctx,
            'weather_adj_pct': weather_adj_pct,
            'learned_elasticity': learned_elasticity,
        },
        'success': True,
    }


def _seasonal_factors(dates, prices):
    """월별 평균 ÷ 전체 평균 = 12개월 계절 인덱스 (충분한 데이터 없으면 1.0)"""
    by_month = {m: [] for m in range(1, 13)}
    for d, p in zip(dates, prices):
        if p <= 0:
            continue
        try:
            m = int(d[5:7])
        except (ValueError, IndexError):
            continue
        by_month[m].append(p)
    overall = _mean([p for p in prices if p > 0]) or 1.0
    factors = {}
    for m in range(1, 13):
        vals = by_month[m]
        factors[m] = (_mean(vals) / overall) if len(vals) >= 3 else 1.0
    return factors


def predict_holt_winters(product_name, forecast_days=30):
    """
    Holt-Winters 풍 계절 분해 — 추세(선형회귀) × 계절(월별 인덱스)
    농산물 12개월 cycle 반영. 365일 이상 데이터 권장.
    """
    dates, prices = prepare_price_series(product_name, days=730)
    if not prices or len(prices) < 90:
        return predict_moving_average(product_name, forecast_days)

    n = len(prices)
    seasonal = _seasonal_factors(dates, prices)

    # 계절 제거 후 선형 추세 학습
    deseasoned = []
    for i, p in enumerate(prices):
        try:
            m = int(dates[i][5:7])
        except (ValueError, IndexError):
            m = 1
        s = seasonal.get(m, 1.0) or 1.0
        deseasoned.append(p / s)

    x_mean = (n - 1) / 2
    y_mean = _mean(deseasoned)
    num = sum((i - x_mean) * (deseasoned[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0
    intercept = y_mean - slope * x_mean

    residuals = [deseasoned[i] - (intercept + slope * i) for i in range(n)]
    std_resid = _std(residuals[-90:]) if len(residuals) >= 90 else _std(residuals)

    weather_ctx = _weather_context()
    learned_elasticity = _learn_temp_elasticity(product_name)
    weather_adj_pct = 0.0

    last_date = datetime.strptime(dates[-1], '%Y-%m-%d')
    results = []
    for i in range(forecast_days):
        pred_date = last_date + timedelta(days=i + 1)
        t = n + i
        s = seasonal.get(pred_date.month, 1.0) or 1.0
        base = (intercept + slope * t) * s

        # weather 보정
        base, weather_adj_pct = _apply_weather_adjustment(
            product_name, base, weather_ctx, learned_elasticity,
        )
        pred_price = max(base, 0)

        # 신뢰구간 — 계절 인덱스 반영
        margin = std_resid * s * 1.645 * math.sqrt(i + 1) * 0.4

        results.append({
            'date': pred_date.strftime('%Y-%m-%d'),
            'predicted_price': round(pred_price, 0),
            'confidence_lower': round(max(pred_price - margin, 0), 0),
            'confidence_upper': round(pred_price + margin, 0),
            'model': 'HoltWinters',
        })

    season_range = round(max(seasonal.values()) - min(seasonal.values()), 3)
    return {
        'product_name': product_name,
        'forecast_days': forecast_days,
        'predictions': results,
        'model_info': {
            'type': 'Holt-Winters (추세 + 12개월 계절)',
            'trend_slope': round(slope, 3),
            'season_range': season_range,
            'season_peak_month': max(seasonal, key=seasonal.get),
            'season_low_month': min(seasonal, key=seasonal.get),
            'data_points': n,
            'weather_context': weather_ctx,
            'weather_adj_pct': weather_adj_pct,
            'learned_elasticity': learned_elasticity,
        },
        'success': True,
    }


def predict_ensemble(product_name, forecast_days=30):
    """
    4개 모델 평균 앙상블 — ARIMA·지수평활·이동평균·Holt-Winters
    각 모델 결과를 단순 평균(같은 가중치). 신뢰구간은 평균.
    """
    models = [
        ('TrendMA', predict_arima),
        ('ExpSmoothing', predict_exponential_smoothing),
        ('MovingAverage', predict_moving_average),
        ('HoltWinters', predict_holt_winters),
    ]

    member_results = {}
    for name, func in models:
        try:
            r = func(product_name, forecast_days)
            if r.get('success') and r.get('predictions'):
                member_results[name] = r['predictions']
        except Exception as e:
            print(f'[ensemble] {name} 실패: {e}')

    if not member_results:
        return predict_moving_average(product_name, forecast_days)

    n_models = len(member_results)
    ensemble = []
    for i in range(forecast_days):
        preds, lowers, uppers, date = [], [], [], None
        for name, preds_list in member_results.items():
            if i < len(preds_list):
                p = preds_list[i]
                preds.append(p['predicted_price'])
                lowers.append(p['confidence_lower'])
                uppers.append(p['confidence_upper'])
                date = p['date']
        if not preds:
            continue
        ensemble.append({
            'date': date,
            'predicted_price': round(sum(preds) / len(preds), 0),
            'confidence_lower': round(sum(lowers) / len(lowers), 0),
            'confidence_upper': round(sum(uppers) / len(uppers), 0),
            'model': 'Ensemble',
        })

    # 학습 데이터 수는 가장 깊은 모델 기준
    dates, prices = prepare_price_series(product_name, days=730)
    return {
        'product_name': product_name,
        'forecast_days': forecast_days,
        'predictions': ensemble,
        'model_info': {
            'type': f'앙상블 ({n_models}개 모델 평균)',
            'models_used': list(member_results.keys()),
            'data_points': len(prices) if prices else 0,
            'weather_context': _weather_context(),
            'learned_elasticity': _learn_temp_elasticity(product_name),
        },
        'success': True,
    }


def predict_exponential_smoothing(product_name, forecast_days=30):
    """순수 Python 지수평활법"""
    dates, prices = prepare_price_series(product_name, days=730)
    if not prices or len(prices) < 30:
        return predict_moving_average(product_name, forecast_days)

    # Holt 이중지수평활법 (추세 포함)
    alpha = 0.3  # 수준 평활계수
    beta = 0.1   # 추세 평활계수

    level = prices[0]
    trend = _mean(prices[1:7]) - prices[0] if len(prices) > 7 else 0

    residuals = []
    for i in range(1, len(prices)):
        new_level = alpha * prices[i] + (1 - alpha) * (level + trend)
        new_trend = beta * (new_level - level) + (1 - beta) * trend
        residuals.append(prices[i] - (level + trend))
        level = new_level
        trend = new_trend

    std_resid = _std(residuals[-30:]) if len(residuals) >= 30 else _std(residuals)

    last_date = datetime.strptime(dates[-1], '%Y-%m-%d')
    results = []
    for i in range(forecast_days):
        pred_date = last_date + timedelta(days=i + 1)
        pred_price = max(level + trend * (i + 1), 0)
        margin = std_resid * 1.645 * math.sqrt(i + 1) * 0.3

        results.append({
            'date': pred_date.strftime('%Y-%m-%d'),
            'predicted_price': round(pred_price, 0),
            'confidence_lower': round(max(pred_price - margin, 0), 0),
            'confidence_upper': round(pred_price + margin, 0),
            'model': 'ExpSmoothing',
        })

    return {
        'product_name': product_name,
        'forecast_days': forecast_days,
        'predictions': results,
        'model_info': {
            'type': '지수평활법 (Holt)',
            'alpha': alpha,
            'beta': beta,
            'data_points': len(prices),
        },
        'success': True,
    }


def predict_moving_average(product_name, forecast_days=30):
    """이동평균 기반 단순 예측 (폴백 모델)"""
    dates, prices = prepare_price_series(product_name, days=365)
    if not prices or len(prices) < 7:
        return {
            'product_name': product_name,
            'forecast_days': forecast_days,
            'predictions': [],
            'model_info': {'type': 'N/A', 'error': '데이터 부족'},
            'success': False,
        }

    ma7 = _mean(prices[-7:])
    ma30 = _mean(prices[-30:]) if len(prices) >= 30 else ma7
    std30 = _std(prices[-30:]) if len(prices) >= 30 else _std(prices[-7:])

    if len(prices) >= 14:
        recent_trend = (_mean(prices[-7:]) - _mean(prices[-14:-7])) / 7
    else:
        recent_trend = 0

    last_date = datetime.strptime(dates[-1], '%Y-%m-%d')
    results = []
    for i in range(forecast_days):
        pred_date = last_date + timedelta(days=i + 1)
        pred_price = ma7 * 0.6 + ma30 * 0.4 + recent_trend * (i + 1)
        pred_price = max(pred_price, 0)

        margin = std30 * 1.5 * math.sqrt((i + 1) / 7)

        results.append({
            'date': pred_date.strftime('%Y-%m-%d'),
            'predicted_price': round(pred_price, 0),
            'confidence_lower': round(max(pred_price - margin, 0), 0),
            'confidence_upper': round(pred_price + margin, 0),
            'model': 'MovingAverage',
        })

    return {
        'product_name': product_name,
        'forecast_days': forecast_days,
        'predictions': results,
        'model_info': {
            'type': '이동평균',
            'ma7': round(ma7, 0),
            'ma30': round(ma30, 0),
            'trend': round(recent_trend, 2),
            'data_points': len(prices),
        },
        'success': True,
    }


def get_price_statistics(product_name, days=365):
    """품목별 가격 통계"""
    dates, prices = prepare_price_series(product_name, days)
    if not prices or len(prices) < 2:
        return None

    if len(prices) >= 2:
        daily_change = prices[-1] - prices[-2]
        daily_change_pct = (daily_change / prices[-2]) * 100
    else:
        daily_change = 0
        daily_change_pct = 0

    if len(prices) >= 7:
        weekly_change = prices[-1] - prices[-7]
        weekly_change_pct = (weekly_change / prices[-7]) * 100
    else:
        weekly_change = 0
        weekly_change_pct = 0

    return {
        'current_price': round(prices[-1], 0),
        'avg_price': round(_mean(prices), 0),
        'max_price': round(max(prices), 0),
        'min_price': round(min(prices), 0),
        'std_price': round(_std(prices), 0),
        'daily_change': round(daily_change, 0),
        'daily_change_pct': round(daily_change_pct, 2),
        'weekly_change': round(weekly_change, 0),
        'weekly_change_pct': round(weekly_change_pct, 2),
        'data_points': len(prices),
        'date_range': {
            'start': dates[0],
            'end': dates[-1],
        },
    }


def save_predictions(product_name, predictions):
    """예측 결과를 DB에 저장"""
    conn = get_db()
    cursor = conn.cursor()

    for pred in predictions:
        cursor.execute('''
            INSERT INTO predictions
            (product_name, predicted_price, predicted_date,
             confidence_lower, confidence_upper, model_type)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            product_name,
            pred['predicted_price'],
            pred['date'],
            pred['confidence_lower'],
            pred['confidence_upper'],
            pred['model'],
        ))

    conn.commit()
    conn.close()
