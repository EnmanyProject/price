# -*- coding: utf-8 -*-
"""
농산물 가격 데이터 수집 모듈

실제 데이터 소스:
1. KAMIS API (농산물유통정보) - 주력
   - periodRetailProductList: 소매 일별 가격 (최대 1년)
   - dailyPriceByCategoryList: 카테고리별 당일 가격
   - recentlyPriceTrendList: 최근 가격 추세
2. 샘플 데이터 (API 키 미설정 시 폴백)

API 키 발급: https://www.kamis.or.kr/customer/reference/openapi_write.do
참고: 농림축산식품부(mafra.go.kr), 농식품유통정보센터(atc.go.kr)
"""

import requests
import random
import math
from datetime import datetime, timedelta
from database import get_db
from config import (
    KAMIS_API_URL, KAMIS_CERT_KEY, KAMIS_CERT_ID,
    PRODUCT_CODES, COUNTRY_CODES,
)


# ============================================================
# KAMIS API 실제 데이터 수집
# ============================================================

def fetch_kamis_period_retail(product_name, start_date, end_date, country_code='1101'):
    """
    KAMIS API: periodRetailProductList
    소매 일별 가격을 기간별로 조회 (최대 1년 단위)

    API 문서: https://www.kamis.or.kr/customer/reference/openapi_list.do
    """
    if not KAMIS_CERT_KEY or not KAMIS_CERT_ID:
        return None

    product_info = PRODUCT_CODES.get(product_name)
    if not product_info:
        return None

    params = {
        'action': 'periodRetailProductList',
        'p_startday': start_date,
        'p_endday': end_date,
        'p_itemcategorycode': product_info['item_category_code'],
        'p_itemcode': product_info['item_code'],
        'p_kindcode': product_info['kind_code'],
        'p_productrankcode': product_info['rank_code'],
        'p_countrycode': country_code,
        'p_convert_kg_yn': 'Y',
        'p_cert_key': KAMIS_CERT_KEY,
        'p_cert_id': KAMIS_CERT_ID,
        'p_returntype': 'json',
    }

    try:
        response = requests.get(KAMIS_API_URL, params=params, timeout=15)
        response.encoding = 'utf-8'

        if response.status_code == 200:
            data = response.json()
            return _parse_period_response(data, product_name)
        else:
            print(f"[ERROR] KAMIS API HTTP {response.status_code}")
    except requests.exceptions.Timeout:
        print(f"[ERROR] KAMIS API 타임아웃 ({product_name})")
    except requests.exceptions.ConnectionError:
        print(f"[ERROR] KAMIS API 연결 실패 ({product_name}) - 네트워크 확인 필요")
    except Exception as e:
        print(f"[ERROR] KAMIS API 호출 실패 ({product_name}): {e}")

    return None


def fetch_kamis_daily_category(category_code='200', regday=None, country_code='1101'):
    """
    KAMIS API: dailyPriceByCategoryList
    카테고리별 당일 가격 조회

    category_code: 100(식량), 200(채소), 300(특용작물), 400(과일), 500(축산), 600(수산)
    """
    if not KAMIS_CERT_KEY or not KAMIS_CERT_ID:
        return None

    if regday is None:
        regday = datetime.now().strftime('%Y-%m-%d')

    params = {
        'action': 'dailyPriceByCategoryList',
        'p_product_cls_code': '01',  # 01=소매, 02=도매
        'p_item_category_code': category_code,
        'p_country_code': country_code,
        'p_regday': regday,
        'p_convert_kg_yn': 'Y',
        'p_cert_key': KAMIS_CERT_KEY,
        'p_cert_id': KAMIS_CERT_ID,
        'p_returntype': 'json',
    }

    try:
        response = requests.get(KAMIS_API_URL, params=params, timeout=15)
        response.encoding = 'utf-8'

        if response.status_code == 200:
            data = response.json()
            return _parse_daily_category_response(data)
    except Exception as e:
        print(f"[ERROR] KAMIS 카테고리 조회 실패: {e}")

    return None


def fetch_kamis_recent_trend(product_name, regday=None):
    """
    KAMIS API: recentlyPriceTrendList
    최근 가격 추세 (당일, 10일전, 20일전, 30일전, 40일전)
    """
    if not KAMIS_CERT_KEY or not KAMIS_CERT_ID:
        return None

    product_info = PRODUCT_CODES.get(product_name)
    if not product_info:
        return None

    if regday is None:
        regday = datetime.now().strftime('%Y-%m-%d')

    # productno는 item_category_code + item_code 조합
    product_no = product_info['item_code']

    params = {
        'action': 'recentlyPriceTrendList',
        'p_productno': product_no,
        'p_regday': regday,
        'p_convert_kg_yn': 'Y',
        'p_cert_key': KAMIS_CERT_KEY,
        'p_cert_id': KAMIS_CERT_ID,
        'p_returntype': 'json',
    }

    try:
        response = requests.get(KAMIS_API_URL, params=params, timeout=15)
        response.encoding = 'utf-8'

        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[ERROR] KAMIS 추세 조회 실패 ({product_name}): {e}")

    return None


# ============================================================
# KAMIS 응답 파싱
# ============================================================

def _parse_period_response(data, product_name):
    """periodRetailProductList / periodWholesaleProductList 응답 파싱"""
    results = []
    try:
        error_code = data.get('data', {}).get('error_code', '')
        if error_code == '001':
            print(f"[INFO] {product_name}: 해당 기간 데이터 없음")
            return results

        items = data.get('data', {}).get('item', [])
        if not isinstance(items, list):
            items = [items]

        for item in items:
            # 가격 문자열에서 쉼표 제거 후 숫자 변환
            price_str = str(item.get('price', item.get('dpr1', ''))).replace(',', '').strip()
            if not price_str or price_str == '-' or price_str == '0':
                continue

            try:
                price = float(price_str)
            except ValueError:
                continue

            # 날짜 파싱
            yyyy = item.get('yyyy', '')
            regday = item.get('regday', '').replace('/', '-')
            if yyyy and regday:
                date_str = f"{yyyy}-{regday}"
            else:
                date_str = item.get('date', '')

            if not date_str:
                continue

            results.append({
                'product_name': product_name,
                'price': price,
                'date': date_str,
                'market': item.get('countyname', item.get('marketname', '서울')),
                'unit': item.get('unit', 'kg'),
                'source': 'KAMIS',
            })

        print(f"[KAMIS] {product_name}: {len(results)}건 파싱 완료")

    except Exception as e:
        print(f"[ERROR] KAMIS 응답 파싱 실패 ({product_name}): {e}")

    return results


def _parse_daily_category_response(data):
    """dailyPriceByCategoryList 응답 파싱"""
    results = []
    try:
        items = data.get('data', {}).get('item', [])
        if not isinstance(items, list):
            items = [items]

        for item in items:
            item_name = item.get('item_name', '')
            price_str = str(item.get('dpr1', '')).replace(',', '').strip()

            if not price_str or price_str == '-':
                continue

            try:
                price = float(price_str)
            except ValueError:
                continue

            results.append({
                'item_name': item_name,
                'item_code': item.get('itemcode', ''),
                'kind_name': item.get('kind_name', ''),
                'rank': item.get('rank', ''),
                'unit': item.get('unit', ''),
                'price': price,
                'day': item.get('day1', ''),
            })
    except Exception as e:
        print(f"[ERROR] 카테고리 응답 파싱 실패: {e}")

    return results


# ============================================================
# 실제 데이터 수집 (KAMIS API → 최대 2년치)
# ============================================================

def fetch_real_data(product_name, years=2):
    """
    KAMIS API로 실제 가격 데이터 수집
    API는 최대 1년 단위 조회 → 여러 번 호출하여 합침
    """
    all_data = []
    end_date = datetime.now()

    for year_offset in range(years):
        period_end = end_date - timedelta(days=365 * year_offset)
        period_start = period_end - timedelta(days=364)

        start_str = period_start.strftime('%Y-%m-%d')
        end_str = period_end.strftime('%Y-%m-%d')

        print(f"  [{product_name}] {start_str} ~ {end_str} 조회 중...")

        data = fetch_kamis_period_retail(product_name, start_str, end_str)
        if data:
            all_data.extend(data)

    return all_data if all_data else None


# ============================================================
# 샘플 데이터 생성 (KAMIS API 키가 없을 때 폴백)
# ============================================================

def generate_sample_data(product_name, days=730):
    """
    실제 농산물 가격 패턴을 시뮬레이션한 샘플 데이터 생성
    - 계절 변동 (월별 계수)
    - 장기 추세 (물가상승)
    - 랜덤 노이즈
    - 이상기후 이벤트 (태풍, 한파 등)
    """
    base_prices = {
        '배추': 2800, '시금치': 3500, '상추': 4500, '고추': 12000,
        '토마토': 3800, '오이': 4000, '무': 2200, '대파': 3500,
        '양파': 2500, '감자': 3200, '사과': 8500,
    }

    seasonal_patterns = {
        '배추': [1.0, 0.95, 0.9, 1.0, 1.1, 1.3, 1.4, 1.2, 1.0, 0.8, 0.85, 0.9],
        '시금치': [1.2, 1.1, 0.9, 0.8, 0.7, 0.8, 1.0, 1.1, 1.0, 0.9, 1.0, 1.2],
        '상추': [1.3, 1.2, 1.0, 0.9, 0.8, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3],
        '고추': [1.1, 1.0, 0.9, 0.85, 0.8, 0.75, 0.8, 0.9, 1.0, 1.1, 1.15, 1.2],
        '토마토': [1.2, 1.1, 1.0, 0.9, 0.7, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2],
        '오이': [1.3, 1.2, 1.0, 0.8, 0.6, 0.5, 0.55, 0.7, 0.85, 1.0, 1.2, 1.3],
        '무': [0.9, 0.95, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1, 1.0, 0.9, 0.85, 0.9],
        '대파': [1.3, 1.2, 1.0, 0.8, 0.7, 0.75, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3],
        '양파': [1.2, 1.1, 1.0, 0.8, 0.7, 0.65, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2],
        '감자': [1.1, 1.05, 1.0, 0.9, 0.8, 0.7, 0.75, 0.85, 0.95, 1.0, 1.1, 1.15],
        '사과': [0.9, 0.95, 1.0, 1.1, 1.2, 1.3, 1.2, 1.1, 0.9, 0.8, 0.85, 0.9],
    }

    base_price = base_prices.get(product_name, 3000)
    pattern = seasonal_patterns.get(product_name, [1.0] * 12)

    data = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    current = start_date
    prev_price = base_price
    trend = random.uniform(-0.0001, 0.0003)

    while current <= end_date:
        month_idx = current.month - 1
        seasonal = pattern[month_idx]

        day_offset = (current - start_date).days
        trend_factor = 1.0 + trend * day_offset
        noise = random.gauss(0, base_price * 0.03)

        price = base_price * seasonal * trend_factor + noise

        if random.random() < 0.02:
            spike = random.choice([-1, 1]) * random.uniform(0.15, 0.35)
            price *= (1 + spike)

        max_change = prev_price * 0.08
        price = max(prev_price - max_change, min(prev_price + max_change, price))
        price = max(price, base_price * 0.3)
        price = round(price, 0)

        data.append({
            'product_name': product_name,
            'price': price,
            'date': current.strftime('%Y-%m-%d'),
            'market': '전국평균',
            'source': 'SAMPLE',
        })

        prev_price = price
        current += timedelta(days=1)

    return data


# ============================================================
# 데이터 저장 / 조회
# ============================================================

def save_price_data(data_list):
    """가격 데이터를 DB에 저장"""
    conn = get_db()
    cursor = conn.cursor()
    saved = 0

    for item in data_list:
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO price_data
                (product_name, price, date, market, source)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                item['product_name'],
                item['price'],
                item['date'],
                item.get('market', '서울'),
                item.get('source', 'KAMIS'),
            ))
            saved += 1
        except Exception as e:
            print(f"[ERROR] 데이터 저장 실패: {e}")

    conn.commit()
    conn.close()
    return saved


def collect_all_data():
    """
    모든 품목의 데이터 수집
    1) KAMIS API로 실제 데이터 시도
    2) 실패 시 샘플 데이터로 폴백
    """
    from database import init_db
    init_db()

    has_api_key = bool(KAMIS_CERT_KEY and KAMIS_CERT_ID)
    if has_api_key:
        print("[INFO] KAMIS API 키가 설정되어 있습니다. 실제 데이터를 수집합니다.")
    else:
        print("[INFO] KAMIS API 키가 설정되지 않았습니다.")
        print("[INFO] 키 발급: https://www.kamis.or.kr/customer/reference/openapi_write.do")
        print("[INFO] 샘플 데이터를 사용합니다.\n")

    total_saved = 0
    for product_name in PRODUCT_CODES.keys():
        print(f"[INFO] {product_name} 데이터 수집 중...")

        data = None
        if has_api_key:
            data = fetch_real_data(product_name, years=2)

        if not data:
            if has_api_key:
                print(f"[WARN] {product_name} KAMIS 데이터 수집 실패 → 샘플 데이터 사용")
            data = generate_sample_data(product_name)

        saved = save_price_data(data)
        total_saved += saved
        print(f"[INFO] {product_name}: {saved}건 저장 완료 (소스: {'KAMIS' if has_api_key and data and data[0].get('source') == 'KAMIS' else 'SAMPLE'})")

    print(f"\n[완료] 총 {total_saved}건 데이터 저장")
    return total_saved


def get_price_history(product_name, days=365):
    """특정 품목의 가격 이력 조회"""
    conn = get_db()
    cursor = conn.cursor()

    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT date, price, market, source
        FROM price_data
        WHERE product_name = ? AND date >= ?
        ORDER BY date ASC
    ''', (product_name, start_date))

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_latest_prices():
    """모든 품목의 최신 가격 조회"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT p1.product_name, p1.price, p1.date, p1.market, p1.source
        FROM price_data p1
        INNER JOIN (
            SELECT product_name, MAX(date) as max_date
            FROM price_data
            GROUP BY product_name
        ) p2 ON p1.product_name = p2.product_name AND p1.date = p2.max_date
        ORDER BY p1.product_name
    ''')

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_data_source_info():
    """현재 데이터 소스 정보 반환"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT source, COUNT(*) as cnt, MIN(date) as min_date, MAX(date) as max_date
        FROM price_data
        GROUP BY source
    ''')
    rows = cursor.fetchall()
    conn.close()

    return {
        'has_api_key': bool(KAMIS_CERT_KEY and KAMIS_CERT_ID),
        'sources': [dict(row) for row in rows],
    }


if __name__ == '__main__':
    collect_all_data()
