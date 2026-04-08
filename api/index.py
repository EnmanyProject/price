# -*- coding: utf-8 -*-
"""
Vercel Serverless Function 엔트리포인트
Flask 앱을 Vercel에서 구동
"""

import sys
import os

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, request
from database import init_db, get_db
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

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['SECRET_KEY'] = 'vegetable-price-predictor-2021'

# Vercel은 /tmp만 쓰기 가능 → DB 경로 오버라이드
import config
config.DATABASE_PATH = '/tmp/prices.db'


def ensure_data():
    """데이터가 없으면 초기화"""
    init_db()
    latest = get_latest_prices()
    if not latest:
        collect_all_data()


@app.route('/')
def index():
    ensure_data()
    return render_template('index.html')


@app.route('/api/products', methods=['GET'])
def api_products():
    ensure_data()
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

    return jsonify({'success': True, 'products': products})


@app.route('/api/history/<product_name>', methods=['GET'])
def api_history(product_name):
    ensure_data()
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
    ensure_data()
    days = request.args.get('days', 365, type=int)
    stats = get_price_statistics(product_name, days)
    if stats:
        return jsonify({'success': True, 'product_name': product_name, 'statistics': stats})
    else:
        return jsonify({'success': False, 'error': '통계 데이터를 계산할 수 없습니다.'})


@app.route('/api/predict', methods=['POST'])
def api_predict():
    ensure_data()
    data = request.get_json()
    product_name = data.get('product_name')
    forecast_days = data.get('forecast_days', 30)
    model_type = data.get('model_type', 'arima')

    if not product_name:
        return jsonify({'success': False, 'error': '품목을 선택해주세요.'})
    if product_name not in PRODUCT_CODES:
        return jsonify({'success': False, 'error': '지원하지 않는 품목입니다.'})

    if model_type == 'arima':
        result = predict_arima(product_name, forecast_days)
    elif model_type == 'exp_smoothing':
        result = predict_exponential_smoothing(product_name, forecast_days)
    else:
        result = predict_moving_average(product_name, forecast_days)

    return jsonify(result)


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    try:
        saved = collect_all_data()
        return jsonify({
            'success': True,
            'saved': saved,
            'message': f'{saved}건의 데이터가 업데이트되었습니다.',
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/datasource', methods=['GET'])
def api_datasource():
    info = get_data_source_info()
    return jsonify({'success': True, 'info': info})


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
