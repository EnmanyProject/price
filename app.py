# -*- coding: utf-8 -*-
"""
농산물 가격 예측 시스템 - Flask 메인 애플리케이션
2021 스타일 (Flask 2.0 + jQuery + Bootstrap 4 + Chart.js 2.x)
"""

from flask import Flask, render_template, jsonify, request
from database import init_db
from data_collector import (
    collect_all_data,
    get_price_history,
    get_latest_prices,
    get_data_source_info,
)
from predictor import (
    predict_arima,
    predict_exponential_smoothing,
    predict_moving_average,
    get_price_statistics,
)
from config import PRODUCT_CODES

app = Flask(__name__)
app.config.from_object('config')


# ===== 초기화 =====
def initialize():
    """앱 시작 시 데이터베이스 초기화 및 샘플 데이터 생성"""
    init_db()
    # 최신 가격 확인 후 없으면 샘플 데이터 생성
    latest = get_latest_prices()
    if not latest:
        print("[INFO] 초기 데이터 수집 시작...")
        collect_all_data()
        print("[INFO] 초기 데이터 수집 완료!")


# ===== 페이지 라우트 =====
@app.route('/')
def index():
    """메인 페이지"""
    return render_template('index.html')


# ===== API 라우트 =====
@app.route('/api/products', methods=['GET'])
def api_products():
    """품목 목록 및 최신 가격"""
    latest_prices = get_latest_prices()
    price_map = {p['product_name']: p for p in latest_prices}

    products = []
    for name, info in PRODUCT_CODES.items():
        price_data = price_map.get(name, {})
        stats = get_price_statistics(name, days=7)

        products.append({
            'name': name,
            'code': info['item_code'],
            'category': info['category'],
            'unit': info['unit'],
            'icon': info['icon'],
            'price': price_data.get('price', 0),
            'date': price_data.get('date', '-'),
            'daily_change': stats['daily_change'] if stats else 0,
            'daily_change_pct': stats['daily_change_pct'] if stats else 0,
        })

    return jsonify({
        'success': True,
        'products': products,
    })


@app.route('/api/history/<product_name>', methods=['GET'])
def api_history(product_name):
    """품목별 가격 이력"""
    days = request.args.get('days', 90, type=int)
    history = get_price_history(product_name, days)

    return jsonify({
        'success': True,
        'product_name': product_name,
        'history': history,
        'count': len(history),
    })


@app.route('/api/statistics/<product_name>', methods=['GET'])
def api_statistics(product_name):
    """품목별 가격 통계"""
    days = request.args.get('days', 365, type=int)
    stats = get_price_statistics(product_name, days)

    if stats:
        return jsonify({
            'success': True,
            'product_name': product_name,
            'statistics': stats,
        })
    else:
        return jsonify({
            'success': False,
            'error': '통계 데이터를 계산할 수 없습니다.',
        })


@app.route('/api/predict', methods=['POST'])
def api_predict():
    """가격 예측"""
    data = request.get_json()
    product_name = data.get('product_name')
    forecast_days = data.get('forecast_days', 30)
    model_type = data.get('model_type', 'arima')

    if not product_name:
        return jsonify({'success': False, 'error': '품목을 선택해주세요.'})

    if product_name not in PRODUCT_CODES:
        return jsonify({'success': False, 'error': '지원하지 않는 품목입니다.'})

    # 모델 선택
    if model_type == 'arima':
        result = predict_arima(product_name, forecast_days)
    elif model_type == 'exp_smoothing':
        result = predict_exponential_smoothing(product_name, forecast_days)
    else:
        result = predict_moving_average(product_name, forecast_days)

    return jsonify(result)


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    """데이터 새로고침"""
    try:
        saved = collect_all_data()
        return jsonify({
            'success': True,
            'saved': saved,
            'message': f'{saved}건의 데이터가 업데이트되었습니다.',
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
        })


@app.route('/api/datasource', methods=['GET'])
def api_datasource():
    """데이터 소스 정보"""
    info = get_data_source_info()
    return jsonify({
        'success': True,
        'info': info,
    })


@app.route('/api/garak-today', methods=['GET'])
def api_garak_today():
    """가락시장 오늘 가격 (실시간 스크래핑)"""
    from data_collector import fetch_garak_all_products_single_day
    results = fetch_garak_all_products_single_day()
    return jsonify({
        'success': bool(results),
        'data': results,
        'count': len(results),
    })


# ===== 메인 =====
if __name__ == '__main__':
    initialize()
    print("\n" + "=" * 50)
    print("  농산물 가격 예측 시스템 v1.0")
    print("  http://localhost:5000")
    print("=" * 50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True)
