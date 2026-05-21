# -*- coding: utf-8 -*-
"""
농산물 가격 데이터 수집 모듈 (복수 소스)

데이터 소스 우선순위:
1. 가락시장 (garakprice.com) — 키 불필요, 도매 경매가
2. KAMIS API (kamis.or.kr) — 키 필요, 소매 가격
3. 샘플 데이터 (폴백)

가락시장: 서울시농수산식품공사 공공데이터 기반
KAMIS: 농산물유통정보 Open API
"""

import re
import requests
import random
import math
from datetime import datetime, timedelta
from database import get_db
from config import (
    KAMIS_API_URL, KAMIS_CERT_KEY, KAMIS_CERT_ID,
    GARAK_BASE_URL, GARAK_PRODUCT_MAP,
    PRODUCT_CODES, COUNTRY_CODES,
)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    print("[WARN] beautifulsoup4 미설치 — 가락시장 스크래핑 불가")


# ============================================================
# 가락시장 (garakprice.com) 스크래핑 — 키 불필요
# ============================================================

def fetch_garak_daily(date_str):
    """
    가락시장 일별 전체 품목 가격 스크래핑
    date_str: 'YYYYMMDD' 형식
    반환: [{'name': ..., 'unit': ..., 'grade': ..., 'price': ...}, ...]
    """
    if not HAS_BS4:
        return None

    url = f"{GARAK_BASE_URL}/index.php?go_date={date_str}"

    try:
        resp = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        resp.encoding = 'utf-8'

        if resp.status_code != 200:
            print(f"[ERROR] 가락시장 HTTP {resp.status_code}")
            return None

        soup = BeautifulSoup(resp.text, 'html.parser')
        items = []

        # 테이블 또는 리스트에서 가격 데이터 추출
        # garakprice.com은 <li> 기반 리스트 구조
        rows = soup.select('li')
        current_item = {}
        field_idx = 0

        # 헤더 이후 데이터 파싱 — 5개 필드가 반복됨
        # 품목명, 기준단위, 등급, 평균가, 날짜
        data_started = False
        fields = []

        for li in rows:
            text = li.get_text(strip=True)
            if not text:
                continue

            # 헤더 감지
            if text == '품목명':
                data_started = True
                fields = []
                continue

            if not data_started:
                continue

            fields.append(text)

            # 5개 필드가 모이면 하나의 레코드
            if len(fields) == 5:
                try:
                    price_str = fields[3].replace(',', '').strip()
                    price = int(price_str) if price_str.isdigit() else 0

                    if price > 0:
                        items.append({
                            'name': fields[0],
                            'unit': fields[1],
                            'grade': fields[2],
                            'price': price,
                            'date': fields[4],
                        })
                except (ValueError, IndexError):
                    pass
                fields = []

        # <table> 기반 구조도 시도 (사이트 구조 변경 대비)
        if not items:
            for table in soup.select('table'):
                for tr in table.select('tr'):
                    tds = tr.select('td')
                    if len(tds) >= 4:
                        try:
                            name = tds[0].get_text(strip=True)
                            unit = tds[1].get_text(strip=True)
                            grade = tds[2].get_text(strip=True)
                            price_str = tds[3].get_text(strip=True).replace(',', '')
                            price = int(price_str) if price_str.isdigit() else 0

                            if price > 0 and name:
                                items.append({
                                    'name': name,
                                    'unit': unit,
                                    'grade': grade,
                                    'price': price,
                                    'date': date_str,
                                })
                        except (ValueError, IndexError):
                            continue

        if items:
            print(f"[가락시장] {date_str}: {len(items)}건 수집")
        return items if items else None

    except requests.exceptions.Timeout:
        print(f"[ERROR] 가락시장 타임아웃 ({date_str})")
    except requests.exceptions.ConnectionError:
        print(f"[ERROR] 가락시장 연결 실패 ({date_str})")
    except Exception as e:
        print(f"[ERROR] 가락시장 스크래핑 실패 ({date_str}): {e}")

    return None


def match_garak_product(garak_items, product_name):
    """
    가락시장 데이터에서 특정 품목 매칭 → kg당 가격 변환
    """
    mapping = GARAK_PRODUCT_MAP.get(product_name)
    if not mapping or not garak_items:
        return None

    keyword = mapping['keyword']
    exclude = mapping.get('exclude', [])
    target_grade = mapping.get('grade', '상')
    default_kg = mapping.get('default_kg', 1)

    candidates = []
    for item in garak_items:
        name = item['name']

        # 키워드 매칭
        if keyword not in name:
            continue

        # 제외 키워드 체크
        skip = False
        for ex in exclude:
            if ex in name:
                skip = True
                break
        if skip:
            continue

        # 등급 매칭
        if item['grade'] != target_grade:
            continue

        candidates.append(item)

    if not candidates:
        # 등급 완화 — 아무 등급이나
        for item in garak_items:
            name = item['name']
            if keyword not in name:
                continue
            skip = False
            for ex in exclude:
                if ex in name:
                    skip = True
                    break
            if skip:
                continue
            candidates.append(item)

    if not candidates:
        return None

    # 첫 번째 매칭 사용
    best = candidates[0]

    # 단위에서 kg 추출하여 kg당 가격 계산
    unit_text = best['unit']
    kg_match = re.search(r'(\d+)\s*(?:키로|kg|KG)', unit_text)
    if kg_match:
        total_kg = float(kg_match.group(1))
    else:
        total_kg = default_kg

    price_per_kg = best['price'] / total_kg if total_kg > 0 else best['price']

    return {
        'product_name': product_name,
        'price': round(price_per_kg, 0),
        'raw_price': best['price'],
        'raw_unit': unit_text,
        'grade': best['grade'],
        'market': '가락시장',
        'source': 'GARAK',
    }


def fetch_garak_product_history(product_name, days=60):
    """
    가락시장에서 특정 품목의 일별 가격 히스토리 수집
    최근 N일간 데이터 (주말/공휴일은 거래 없음)
    """
    results = []
    end_date = datetime.now()

    for d in range(days):
        target = end_date - timedelta(days=d)
        # 주말 건너뛰기 (토=5, 일=6)
        if target.weekday() in (5, 6):
            continue

        date_str = target.strftime('%Y%m%d')
        date_iso = target.strftime('%Y-%m-%d')

        garak_items = fetch_garak_daily(date_str)
        if not garak_items:
            continue

        matched = match_garak_product(garak_items, product_name)
        if matched:
            matched['date'] = date_iso
            results.append(matched)

    print(f"[가락시장] {product_name}: {len(results)}일치 데이터 수집 완료")
    return results if results else None


def fetch_garak_all_products_single_day(date_str=None):
    """
    가락시장 하루치 데이터로 모든 품목 가격 수집
    가장 효율적 — 1번 요청으로 전체 품목 커버
    """
    if date_str is None:
        # 오늘이 주말이면 가장 최근 평일 사용
        today = datetime.now()
        while today.weekday() in (5, 6):
            today -= timedelta(days=1)
        date_str = today.strftime('%Y%m%d')

    date_iso = datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
    garak_items = fetch_garak_daily(date_str)

    if not garak_items:
        return {}

    results = {}
    for product_name in PRODUCT_CODES.keys():
        matched = match_garak_product(garak_items, product_name)
        if matched:
            matched['date'] = date_iso
            results[product_name] = matched

    return results


# ============================================================
# KAMIS API 실제 데이터 수집
# ============================================================

def fetch_kamis_period_retail(product_name, start_date, end_date, country_code='1101'):
    """
    KAMIS API: periodRetailProductList
    소매 일별 가격을 기간별로 조회 (최대 1년 단위)
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
        print(f"[ERROR] KAMIS API 연결 실패 ({product_name})")
    except Exception as e:
        print(f"[ERROR] KAMIS API 호출 실패 ({product_name}): {e}")

    return None


def _parse_period_response(data, product_name):
    """periodRetailProductList 응답 파싱"""
    results = []
    try:
        error_code = data.get('data', {}).get('error_code', '')
        if error_code == '001':
            return results

        items = data.get('data', {}).get('item', [])
        if not isinstance(items, list):
            items = [items]

        for item in items:
            price_str = str(item.get('price', item.get('dpr1', ''))).replace(',', '').strip()
            if not price_str or price_str == '-' or price_str == '0':
                continue

            try:
                price = float(price_str)
            except ValueError:
                continue

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


def fetch_real_data(product_name, years=2):
    """KAMIS API로 실제 가격 데이터 수집 (최대 1년 단위 조회)"""
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
# 샘플 데이터 생성 (폴백)
# ============================================================

def generate_sample_data(product_name, days=730):
    """실제 농산물 가격 패턴을 시뮬레이션한 샘플 데이터"""
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

    # 경량화: random.gauss 대신 uniform 사용 (Vercel cold start 최적화)
    data = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    prev_price = base_price
    trend = random.uniform(-0.0001, 0.0003)
    noise_amp = base_price * 0.03
    max_change_ratio = 0.08
    min_price = base_price * 0.3

    for day_offset in range(days + 1):
        current = start_date + timedelta(days=day_offset)
        month_idx = current.month - 1
        seasonal = pattern[month_idx]
        trend_factor = 1.0 + trend * day_offset
        noise = (random.random() - 0.5) * 2 * noise_amp

        price = base_price * seasonal * trend_factor + noise

        # 가끔 가격 급변동 (2% 확률)
        if random.random() < 0.02:
            price *= 1 + (random.random() - 0.5) * 0.6

        # 일일 변동폭 제한 (±8%)
        max_change = prev_price * max_change_ratio
        if price > prev_price + max_change:
            price = prev_price + max_change
        elif price < prev_price - max_change:
            price = prev_price - max_change
        if price < min_price:
            price = min_price

        data.append({
            'product_name': product_name,
            'price': round(price, 0),
            'date': current.strftime('%Y-%m-%d'),
            'market': '전국평균',
            'source': 'SAMPLE',
        })
        prev_price = price

    return data


# ============================================================
# 데이터 저장 / 조회
# ============================================================

def save_price_data(data_list):
    """가격 데이터를 DB에 저장 — executemany batch insert (Vercel cold start 최적화)"""
    if not data_list:
        return 0

    conn = get_db()
    cursor = conn.cursor()

    # 한 번에 모든 row를 튜플 리스트로 준비 → executemany로 일괄 INSERT
    rows = [
        (
            item['product_name'],
            item['price'],
            item['date'],
            item.get('market', '서울'),
            item.get('source', 'KAMIS'),
        )
        for item in data_list
    ]

    try:
        cursor.executemany('''
            INSERT OR REPLACE INTO price_data
            (product_name, price, date, market, source)
            VALUES (?, ?, ?, ?, ?)
        ''', rows)
        conn.commit()
        saved = len(rows)
    except Exception as e:
        print(f"[ERROR] batch insert 실패: {e}")
        saved = 0

    conn.close()
    return saved


# ============================================================
# 복수 소스 통합 수집
# ============================================================

def collect_all_data():
    """
    모든 품목 데이터를 복수 소스에서 수집
    우선순위: 가락시장 → KAMIS API → 샘플 데이터
    """
    from database import init_db
    init_db()

    has_api_key = bool(KAMIS_CERT_KEY and KAMIS_CERT_ID)
    has_bs4 = HAS_BS4

    print("=" * 50)
    print("  농산물 가격 데이터 수집 시작")
    print("=" * 50)
    print(f"[소스 1] 가락시장 (garakprice.com): {'사용 가능' if has_bs4 else '미설치 (pip install beautifulsoup4)'}")
    print(f"[소스 2] KAMIS API: {'키 설정됨' if has_api_key else '키 미설정'}")
    print(f"[소스 3] 샘플 데이터: 항상 사용 가능 (폴백)")
    print()

    total_saved = 0
    source_stats = {'GARAK': 0, 'KAMIS': 0, 'SAMPLE': 0}

    # 1단계: 가락시장 최근 데이터 수집 (최근 30일, 1회 요청으로 전체 품목)
    garak_recent = {}
    if has_bs4:
        print("[STEP 1] 가락시장 최근 가격 수집...")
        today = datetime.now()
        for d in range(30):
            target = today - timedelta(days=d)
            if target.weekday() in (5, 6):
                continue

            date_str = target.strftime('%Y%m%d')
            date_iso = target.strftime('%Y-%m-%d')

            garak_items = fetch_garak_daily(date_str)
            if not garak_items:
                continue

            for product_name in PRODUCT_CODES.keys():
                matched = match_garak_product(garak_items, product_name)
                if matched:
                    matched['date'] = date_iso
                    matched['product_name'] = product_name

                    if product_name not in garak_recent:
                        garak_recent[product_name] = []
                    garak_recent[product_name].append(matched)

        # 가락시장 데이터 저장
        for product_name, records in garak_recent.items():
            saved = save_price_data(records)
            total_saved += saved
            source_stats['GARAK'] += saved
            print(f"  [가락시장] {product_name}: {saved}건 저장")

    # 2단계: KAMIS API 데이터 수집 (키가 있을 때)
    if has_api_key:
        print("\n[STEP 2] KAMIS API 소매 가격 수집...")
        for product_name in PRODUCT_CODES.keys():
            data = fetch_real_data(product_name, years=1)
            if data:
                saved = save_price_data(data)
                total_saved += saved
                source_stats['KAMIS'] += saved
                print(f"  [KAMIS] {product_name}: {saved}건 저장")

    # 3단계: 가락시장/KAMIS 데이터가 부족한 품목은 샘플로 보충
    print("\n[STEP 3] 부족한 데이터 샘플로 보충...")
    for product_name in PRODUCT_CODES.keys():
        # 현재 DB에 있는 데이터 수 확인
        existing = get_price_history(product_name, days=730)

        if len(existing) < 60:
            print(f"  [{product_name}] 데이터 {len(existing)}건 부족 → 샘플 생성")
            sample = generate_sample_data(product_name)
            saved = save_price_data(sample)
            total_saved += saved
            source_stats['SAMPLE'] += saved
        else:
            print(f"  [{product_name}] 데이터 {len(existing)}건 충분 → 스킵")

    print()
    print("=" * 50)
    print(f"  수집 완료: 총 {total_saved}건")
    print(f"  가락시장: {source_stats['GARAK']}건")
    print(f"  KAMIS:    {source_stats['KAMIS']}건")
    print(f"  샘플:     {source_stats['SAMPLE']}건")
    print("=" * 50)

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
    """데이터 소스별 통계 정보"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT source, COUNT(*) as cnt, MIN(date) as min_date, MAX(date) as max_date
        FROM price_data
        GROUP BY source
    ''')
    rows = cursor.fetchall()

    # 품목별 소스 정보
    cursor.execute('''
        SELECT product_name, source, COUNT(*) as cnt, MAX(date) as latest
        FROM price_data
        GROUP BY product_name, source
        ORDER BY product_name, source
    ''')
    product_sources = cursor.fetchall()
    conn.close()

    return {
        'has_api_key': bool(KAMIS_CERT_KEY and KAMIS_CERT_ID),
        'has_garak': HAS_BS4,
        'sources': [dict(row) for row in rows],
        'product_sources': [dict(row) for row in product_sources],
    }


if __name__ == '__main__':
    collect_all_data()
