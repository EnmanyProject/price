# -*- coding: utf-8 -*-
"""
농산물 가격 예측 모듈
- ARIMA 시계열 예측
- 이동평균 기반 단순 예측 (폴백)
- 예측 신뢰구간 계산

Vercel 서버리스 환경을 위해 무거운 패키지는 lazy import 처리
"""

import warnings
warnings.filterwarnings('ignore')

import math
from datetime import datetime, timedelta
from data_collector import get_price_history
from database import get_db

# lazy import 대상 — 호출 시점에 로드
np = None
pd = None


def _ensure_imports():
    """numpy, pandas를 필요할 때만 로드"""
    global np, pd
    if np is None:
        import numpy
        np = numpy
    if pd is None:
        import pandas
        pd = pandas


def prepare_time_series(product_name, days=365):
    """시계열 데이터 준비"""
    _ensure_imports()
    history = get_price_history(product_name, days)
    if not history:
        return None

    df = pd.DataFrame(history)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    df = df.drop_duplicates(subset='date', keep='last')
    df = df.set_index('date')

    # 결측치 보간
    idx = pd.date_range(df.index.min(), df.index.max())
    df = df.reindex(idx)
    df['price'] = df['price'].interpolate(method='linear')
    df = df.dropna(subset=['price'])

    return df


def predict_arima(product_name, forecast_days=30):
    """ARIMA 모델을 사용한 가격 예측"""
    _ensure_imports()

    df = prepare_time_series(product_name, days=730)
    if df is None or len(df) < 60:
        return predict_moving_average(product_name, forecast_days)

    prices = df['price'].values

    try:
        from statsmodels.tsa.arima.model import ARIMA
        model = ARIMA(prices, order=(5, 1, 2))
        fitted = model.fit()

        forecast = fitted.get_forecast(steps=forecast_days)
        predicted = forecast.predicted_mean
        conf_int = forecast.conf_int(alpha=0.1)

        last_date = df.index[-1]
        results = []
        for i in range(forecast_days):
            pred_date = last_date + timedelta(days=i + 1)
            pred_price = max(predicted[i], 0)
            lower = max(conf_int[i, 0], 0)
            upper = conf_int[i, 1]

            results.append({
                'date': pred_date.strftime('%Y-%m-%d'),
                'predicted_price': round(pred_price, 0),
                'confidence_lower': round(lower, 0),
                'confidence_upper': round(upper, 0),
                'model': 'ARIMA(5,1,2)',
            })

        aic = fitted.aic
        bic = fitted.bic

        return {
            'product_name': product_name,
            'forecast_days': forecast_days,
            'predictions': results,
            'model_info': {
                'type': 'ARIMA(5,1,2)',
                'aic': round(aic, 2),
                'bic': round(bic, 2),
                'data_points': len(prices),
            },
            'success': True,
        }

    except Exception as e:
        print(f"[WARN] ARIMA 예측 실패 ({product_name}): {e}")
        return predict_moving_average(product_name, forecast_days)


def predict_exponential_smoothing(product_name, forecast_days=30):
    """지수평활법 기반 예측"""
    _ensure_imports()

    df = prepare_time_series(product_name, days=730)
    if df is None or len(df) < 60:
        return predict_moving_average(product_name, forecast_days)

    prices = df['price'].values

    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        model = ExponentialSmoothing(
            prices,
            seasonal_periods=30,
            trend='add',
            seasonal='add',
        )
        fitted = model.fit(optimized=True)
        predicted = fitted.forecast(forecast_days)

        residuals = fitted.resid
        std_resid = np.std(residuals)

        last_date = df.index[-1]
        results = []
        for i in range(forecast_days):
            pred_date = last_date + timedelta(days=i + 1)
            pred_price = max(predicted[i], 0)
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
                'type': 'Exponential Smoothing',
                'data_points': len(prices),
            },
            'success': True,
        }

    except Exception as e:
        print(f"[WARN] 지수평활법 예측 실패 ({product_name}): {e}")
        return predict_moving_average(product_name, forecast_days)


def predict_moving_average(product_name, forecast_days=30):
    """이동평균 기반 단순 예측 (폴백 모델)"""
    _ensure_imports()

    df = prepare_time_series(product_name, days=365)
    if df is None or len(df) < 7:
        return {
            'product_name': product_name,
            'forecast_days': forecast_days,
            'predictions': [],
            'model_info': {'type': 'N/A', 'error': '데이터 부족'},
            'success': False,
        }

    prices = df['price'].values

    ma7 = np.mean(prices[-7:])
    ma30 = np.mean(prices[-30:]) if len(prices) >= 30 else ma7
    std30 = np.std(prices[-30:]) if len(prices) >= 30 else np.std(prices[-7:])

    if len(prices) >= 14:
        recent_trend = (np.mean(prices[-7:]) - np.mean(prices[-14:-7])) / 7
    else:
        recent_trend = 0

    last_date = df.index[-1]
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
    _ensure_imports()

    df = prepare_time_series(product_name, days)
    if df is None or len(df) < 2:
        return None

    prices = df['price'].values

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
        'avg_price': round(np.mean(prices), 0),
        'max_price': round(np.max(prices), 0),
        'min_price': round(np.min(prices), 0),
        'std_price': round(np.std(prices), 0),
        'daily_change': round(daily_change, 0),
        'daily_change_pct': round(daily_change_pct, 2),
        'weekly_change': round(weekly_change, 0),
        'weekly_change_pct': round(weekly_change_pct, 2),
        'data_points': len(prices),
        'date_range': {
            'start': df.index[0].strftime('%Y-%m-%d'),
            'end': df.index[-1].strftime('%Y-%m-%d'),
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
