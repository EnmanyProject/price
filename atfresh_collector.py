# -*- coding: utf-8 -*-
"""
aT 도매시장 통합거래정보 수집 (공공데이터포털)

가락·구리·안양·대전 등 다도매시장 일별 거래량·가격.
KAMIS·가락 단일 사이트와 보완 — 도매시장 범위가 넓음.
인증키 없으면 모든 함수가 noop(0건 반환) — 안전한 fallback.

응답 구조는 사장님 키 발급 후 가이드 문서 받으면 _parse_response 패치.
"""

import requests
from datetime import datetime, timedelta

from database import get_db, upsert_sql
from config import (
    ATFRESH_API_URL, ATFRESH_API_KEY,
    PRODUCT_CODES,
)


def _has_key():
    return bool(ATFRESH_API_KEY)


def fetch_atfresh_daily(date_str, market_code=None):
    """
    aT 도매시장 일별 거래 조회
    date_str: 'YYYYMMDD'
    market_code: 시장 코드 (None이면 전체)
    반환: [{product_name, market, price, date, source}, ...]
    """
    if not _has_key():
        return []

    params = {
        'serviceKey': ATFRESH_API_KEY,
        'pageNo': 1,
        'numOfRows': 999,
        'type': 'json',
        'saleDate': date_str,
    }
    if market_code:
        params['whsalMrktCode'] = market_code

    try:
        resp = requests.get(ATFRESH_API_URL, params=params, timeout=15)
        if resp.status_code != 200:
            print(f'[aT] HTTP {resp.status_code}')
            return []
        return _parse_response(resp.json(), date_str)
    except requests.exceptions.Timeout:
        print(f'[aT] 타임아웃 ({date_str})')
    except Exception as e:
        print(f'[aT] 호출 실패 ({date_str}): {e}')
    return []


def _parse_response(data, date_str):
    """
    응답 파싱 — 정확한 필드명은 가이드 문서 받으면 패치 필요.
    공공데이터포털 표준 패턴 기반 추정.
    """
    results = []
    try:
        items = data.get('response', {}).get('body', {}).get('items', {}).get('item', [])
        if isinstance(items, dict):
            items = [items]

        for it in items:
            # 필드명 추정: prdlstNm(품목명) / avrgPrice 또는 sbidPrice(평균/낙찰가) / whsalMrktNm(시장)
            raw_name = it.get('prdlstNm') or it.get('itemNm') or ''
            price_raw = (it.get('avrgPrice') or it.get('sbidPrice') or '0')
            market = it.get('whsalMrktNm') or it.get('marketNm') or '도매시장'

            # 우리 11품목과 매칭
            product_name = _match_product(raw_name)
            if not product_name:
                continue

            try:
                price = float(str(price_raw).replace(',', '').strip())
            except (ValueError, TypeError):
                continue
            if price <= 0:
                continue

            date_iso = datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
            results.append({
                'product_name': product_name,
                'price': price,
                'date': date_iso,
                'market': market,
                'source': 'ATFRESH',
            })
    except Exception as e:
        print(f'[aT] 파싱 실패: {e}')
    return results


def _match_product(raw_name):
    """raw_name에서 우리 11품목 매칭 (가장 먼저 발견된 키워드)"""
    if not raw_name:
        return None
    for product_name in PRODUCT_CODES.keys():
        if product_name in raw_name:
            return product_name
    return None


def save_atfresh(records):
    """price_data에 upsert (KAMIS와 동일 테이블)"""
    if not records:
        return 0
    from data_collector import save_price_data
    return save_price_data(records)


def collect_atfresh_today():
    """오늘(=어제 데이터, 도매는 익일 게재) 적재 — Cron용"""
    if not _has_key():
        return 0
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    recs = fetch_atfresh_daily(yesterday)
    return save_atfresh(recs)


def collect_atfresh_history(days=365):
    """과거 N일 백필 — 초기 적재용"""
    if not _has_key():
        return 0
    saved = 0
    end = datetime.now() - timedelta(days=1)
    for d in range(days):
        date_str = (end - timedelta(days=d)).strftime('%Y%m%d')
        recs = fetch_atfresh_daily(date_str)
        saved += save_atfresh(recs)
    return saved


if __name__ == '__main__':
    if not _has_key():
        print('ATFRESH_API_KEY 미설정')
    else:
        n = collect_atfresh_history(days=30)
        print(f'30일치 적재 완료: {n}건')
