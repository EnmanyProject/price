# -*- coding: utf-8 -*-
"""
Vercel Serverless Function 엔트리포인트
Flask 앱을 Vercel에서 구동
"""

import sys
import os
import traceback
from urllib.parse import unquote

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, request

# Vercel은 /tmp만 쓰기 가능 → SQLite 폴백 시에만 경로 오버라이드
# DATABASE_URL이 있으면 Postgres(Neon)로 영속, 폴백 경로는 무시됨
import config
from database import init_db, get_db, IS_POSTGRES
if not IS_POSTGRES:
    config.DATABASE_PATH = '/tmp/prices.db'
from data_collector import (
    collect_all_data,
    get_price_history,
    get_latest_prices,
    get_data_source_info,
    generate_sample_data,
    save_price_data,
)
from predictor import (
    predict_arima,
    predict_exponential_smoothing,
    predict_moving_average,
    predict_holt_winters,
    predict_ensemble,
    get_price_statistics,
)
from config import PRODUCT_CODES

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['SECRET_KEY'] = 'vegetable-price-predictor-2021'


# 컨테이너 인스턴스 단위로 1회만 초기화하도록 글로벌 플래그
# Vercel Fluid Compute는 인스턴스를 재사용하므로 이 플래그가 유효함
_DATA_INITIALIZED = False


def ensure_data():
    """
    스키마 보장 + (SQLite 폴백 시) 샘플 데이터 재생성
    - Postgres(Neon): 영속 — 스키마만 보장, 데이터는 Cron이 적재
    - SQLite(/tmp): cold start마다 휘발 — 가상 기준일에 맞춰 SAMPLE 재생성
    """
    global _DATA_INITIALIZED
    if _DATA_INITIALIZED:
        return

    try:
        init_db()

        if IS_POSTGRES:
            # 영속 DB 운영 로직:
            # - 실데이터(KAMIS·ATFRESH 등) 100건 이상이면 SAMPLE 자동 정리
            #   (가격대 차이로 차트 들쭉날쭉 + 데이터 신뢰성 저하 방지)
            # - 완전히 비어있을 때만 SAMPLE 1회 폴백 적재
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM price_data WHERE source != ?",
                ('SAMPLE',),
            )
            real_cnt = cur.fetchone()['cnt']
            if real_cnt > 100:
                cur.execute("DELETE FROM price_data WHERE source = ?", ('SAMPLE',))
                conn.commit()
            else:
                cur.execute("SELECT COUNT(*) AS cnt FROM price_data")
                if cur.fetchone()['cnt'] == 0:
                    all_data = []
                    for product_name in PRODUCT_CODES.keys():
                        all_data.extend(generate_sample_data(product_name, days=365))
                    save_price_data(all_data)
            conn.close()
            _DATA_INITIALIZED = True
            return

        # 이하 SQLite 폴백 경로
        from config import get_today
        latest = get_latest_prices()
        today_str = get_today().strftime('%Y-%m-%d')
        needs_rebuild = not latest
        if latest:
            latest_date = max(p.get('date', '') for p in latest)
            if latest_date != today_str:
                needs_rebuild = True
                conn = get_db()
                conn.cursor().execute('DELETE FROM price_data')
                conn.commit()
                conn.close()

        if needs_rebuild:
            all_data = []
            for product_name in PRODUCT_CODES.keys():
                all_data.extend(generate_sample_data(product_name, days=365))
            save_price_data(all_data)

        _DATA_INITIALIZED = True
    except Exception as e:
        print(f"[ERROR] ensure_data 실패: {e}")
        traceback.print_exc()


# 모듈 import 시점에 즉시 초기화 → cold start 비용 한 번에 지불
# 이후 요청은 메모리/DB에서 즉시 응답
try:
    ensure_data()
except Exception as e:
    print(f"[WARN] 초기 데이터 로드 실패 (요청 시 재시도): {e}")


# 에러 핸들러 — 디버그용 상세 메시지 반환
@app.errorhandler(500)
def handle_500(e):
    return jsonify({
        'error': str(e),
        'traceback': traceback.format_exc(),
    }), 500


@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({
        'error': str(e),
        'type': type(e).__name__,
        'traceback': traceback.format_exc(),
    }), 500


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
        price_data = price_map.get(name) or {}
        stats = get_price_statistics(name, days=7)

        # price가 None/0이면 통계의 current_price로 폴백
        price_value = price_data.get('price')
        if price_value is None or price_value == 0:
            if stats and stats.get('current_price'):
                price_value = stats['current_price']
            else:
                price_value = 0

        products.append({
            'name': name,
            'code': info['item_code'],
            'category': info['category'],
            'unit': info['unit'],
            'icon': info['icon'],
            'price': float(price_value) if price_value is not None else 0,
            'date': price_data.get('date', '-'),
            'daily_change': float(stats['daily_change']) if stats else 0,
            'daily_change_pct': float(stats['daily_change_pct']) if stats else 0,
        })

    return jsonify({
        'success': True,
        'products': products,
        'debug': {
            'latest_count': len(latest_prices),
            'product_count': len(products),
            'initialized': _DATA_INITIALIZED,
        },
    })


@app.route('/api/debug', methods=['GET'])
def api_debug():
    """진단용 엔드포인트 — DB 상태와 가격 데이터 표본 반환"""
    try:
        ensure_data()
        latest = get_latest_prices()
        info = get_data_source_info()

        # 첫 품목 가격 이력 표본
        sample_history = []
        if PRODUCT_CODES:
            first_product = list(PRODUCT_CODES.keys())[0]
            history = get_price_history(first_product, days=7)
            sample_history = history[:5]

        return jsonify({
            'initialized': _DATA_INITIALIZED,
            'db_path': config.DATABASE_PATH,
            'latest_prices_count': len(latest),
            'latest_prices_sample': latest[:3],
            'source_info': info,
            'sample_history_product': list(PRODUCT_CODES.keys())[0] if PRODUCT_CODES else None,
            'sample_history': sample_history,
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'type': type(e).__name__,
            'traceback': traceback.format_exc(),
        }), 500


@app.route('/api/history/<path:product_name>', methods=['GET'])
def api_history(product_name):
    # Vercel @vercel/python builder가 URL 인코딩을 자동 디코드하지 않으므로 직접 unquote
    product_name = unquote(product_name)
    ensure_data()
    days = request.args.get('days', 90, type=int)
    history = get_price_history(product_name, days)
    return jsonify({
        'success': True,
        'product_name': product_name,
        'history': history,
        'count': len(history),
    })


@app.route('/api/statistics/<path:product_name>', methods=['GET'])
def api_statistics(product_name):
    product_name = unquote(product_name)
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

    if model_type == 'ensemble':
        result = predict_ensemble(product_name, forecast_days)
    elif model_type == 'holt_winters':
        result = predict_holt_winters(product_name, forecast_days)
    elif model_type == 'arima':
        result = predict_arima(product_name, forecast_days)
    elif model_type == 'exp_smoothing':
        result = predict_exponential_smoothing(product_name, forecast_days)
    else:
        result = predict_moving_average(product_name, forecast_days)

    return jsonify(result)


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    """데이터 새로고침 — 가락시장 실시간 + 샘플 보충"""
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
    ensure_data()
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


@app.route('/datatool')
def datatool():
    """데이터 수집·관리 관제 터미널 페이지"""
    ensure_data()
    return render_template('datatool.html')


@app.route('/api/datatool/sources', methods=['GET'])
def api_datatool_sources():
    ensure_data()
    from datatool import get_sources_status
    return jsonify(get_sources_status())


@app.route('/api/datatool/inventory', methods=['GET'])
def api_datatool_inventory():
    ensure_data()
    from datatool import get_inventory
    return jsonify(get_inventory())


@app.route('/api/datatool/stats', methods=['GET'])
def api_datatool_stats():
    ensure_data()
    from datatool import get_stats
    return jsonify(get_stats())


@app.route('/api/datatool/collect', methods=['POST'])
def api_datatool_collect():
    ensure_data()
    from datatool import run_collect
    mode = request.args.get('mode', 'synthetic')
    return jsonify(run_collect(mode=mode))


@app.after_request
def add_cors_headers(response):
    """arang.net 정적 사이트에서 /api/* 호출 가능하도록 CORS 허용"""
    if request.path.startswith('/api/'):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/api/weather/today', methods=['GET'])
def api_weather_today():
    """8개 관측소 최신 기상 — arang.net 위젯용 (CORS 허용)"""
    from config import KMA_STATIONS
    ensure_data()
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        WITH latest AS (
            SELECT station, MAX(date) AS max_date FROM weather GROUP BY station
        )
        SELECT w.station, w.date, w.avg_temp, w.min_temp, w.max_temp,
               w.precipitation, w.humidity
        FROM weather w
        JOIN latest l ON w.station = l.station AND w.date = l.max_date
    ''')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    by_name = {r['station']: r for r in rows}
    station_order = list(KMA_STATIONS.keys())
    stations = [by_name[name] for name in station_order if name in by_name]

    latest_date = max((r['date'] for r in rows), default=None)
    return jsonify({
        'date': latest_date,
        'count': len(stations),
        'stations': stations,
    })


@app.route('/api/debug/sources', methods=['GET'])
def api_debug_sources():
    """소스별 키 등록·응답 진단 (개발용)"""
    from datetime import datetime, timedelta
    from weather_collector import _has_key as kma_has_key, fetch_asos_daily
    from data_collector import fetch_garak_daily, HAS_BS4, KAMIS_CERT_KEY, KAMIS_CERT_ID

    today = datetime.now()
    while today.weekday() in (5, 6):
        today -= timedelta(days=1)
    test_date_str = today.strftime('%Y%m%d')

    result = {
        'test_date': test_date_str,
        'kma': {'has_key': kma_has_key()},
        'kamis': {'has_key': bool(KAMIS_CERT_KEY and KAMIS_CERT_ID)},
        'garak': {'bs4_installed': HAS_BS4},
    }

    if kma_has_key():
        kma_yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
        items = fetch_asos_daily('108', kma_yesterday, kma_yesterday)
        result['kma']['test_call'] = {
            'date': kma_yesterday, 'station': '108(서울)',
            'count': len(items),
            'sample': items[0] if items else None,
        }

    if HAS_BS4:
        try:
            items = fetch_garak_daily(test_date_str)
            result['garak']['test_call'] = {
                'date': test_date_str,
                'count': len(items) if items else 0,
            }
        except Exception as e:
            result['garak']['test_call'] = {'error': str(e)}

    return jsonify(result)


@app.route('/api/cron/collect', methods=['GET', 'POST'])
def api_cron_collect():
    """
    Vercel Cron 일일 수집 트리거 — vercel.json crons에서 호출
    가락시장·KAMIS·KMA 오늘 1일치만 가볍게 적재 (function timeout 회피)
    """
    cron_secret = os.environ.get('CRON_SECRET', '')
    if cron_secret:
        auth = request.headers.get('Authorization', '')
        if auth != f'Bearer {cron_secret}':
            return jsonify({'error': 'unauthorized'}), 401

    ensure_data()
    from data_collector import collect_today
    return jsonify(collect_today())


@app.route('/api/health', methods=['GET'])
def api_health():
    """헬스체크"""
    return jsonify({
        'status': 'ok',
        'python': sys.version,
        'db_backend': 'postgres' if IS_POSTGRES else 'sqlite',
    })


@app.route('/api/today', methods=['GET'])
def api_today():
    """앱 전역 기준일 — 데모용 가상 날짜"""
    from config import get_today
    today = get_today()
    return jsonify({
        'date': today.strftime('%Y-%m-%d'),
        'datetime': today.strftime('%Y-%m-%d %H:%M'),
        'year': today.year,
        'month': today.month,
        'day': today.day,
    })
