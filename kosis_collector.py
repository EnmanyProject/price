# -*- coding: utf-8 -*-
"""
KOSIS 통계청 OpenAPI 수집 — 농산물 CPI / 신선식품지수

가격 데이터(price_data)와 별도 테이블(cpi)에 저장.
장기 가격 트렌드 보정·예측 모델 보조 입력용.
인증키 없으면 모든 함수가 noop.
"""

import requests
from datetime import datetime

from database import get_db, upsert_sql
from config import KOSIS_API_URL, KOSIS_API_KEY, KOSIS_TABLES


def _has_key():
    return bool(KOSIS_API_KEY)


def fetch_kosis_table(table_id, start_period=None, end_period=None):
    """
    KOSIS 통계표 데이터 조회
    table_id: 'DT_1J17001' 등
    period: 'YYYYMM' (월별 통계)
    반환: [{date, table_id, value, unit, item_name}, ...]
    """
    if not _has_key():
        return []

    params = {
        'method': 'getList',
        'apiKey': KOSIS_API_KEY,
        'format': 'json',
        'jsonVD': 'Y',
        'orgId': '101',  # 통계청
        'tblId': table_id,
    }
    if start_period:
        params['startPrdDe'] = start_period
    if end_period:
        params['endPrdDe'] = end_period

    try:
        resp = requests.get(KOSIS_API_URL, params=params, timeout=20)
        if resp.status_code != 200:
            print(f'[KOSIS] HTTP {resp.status_code}')
            return []
        return _parse_response(resp.json(), table_id)
    except requests.exceptions.Timeout:
        print(f'[KOSIS] 타임아웃 ({table_id})')
    except Exception as e:
        print(f'[KOSIS] 호출 실패 ({table_id}): {e}')
    return []


def _parse_response(data, table_id):
    """KOSIS 응답 파싱"""
    results = []
    try:
        if isinstance(data, dict) and data.get('err'):
            print(f'[KOSIS] {table_id} err: {data.get("errMsg")}')
            return []
        items = data if isinstance(data, list) else []
        for it in items:
            period = it.get('PRD_DE', '')  # 'YYYYMM' 또는 'YYYYMMDD'
            try:
                value = float(it.get('DT', 0) or 0)
            except (ValueError, TypeError):
                continue
            date_iso = _period_to_iso(period)
            if not date_iso:
                continue
            results.append({
                'date': date_iso,
                'table_id': table_id,
                'item_name': it.get('C1_NM') or it.get('ITM_NM') or '',
                'value': value,
                'unit': it.get('UNIT_NM', ''),
            })
    except Exception as e:
        print(f'[KOSIS] 파싱 실패 ({table_id}): {e}')
    return results


def _period_to_iso(period):
    """KOSIS 기간 코드 → 'YYYY-MM-DD' (월별이면 그 달 1일)"""
    if not period:
        return None
    p = str(period).strip()
    try:
        if len(p) == 6:
            return f'{p[:4]}-{p[4:6]}-01'
        if len(p) == 8:
            return f'{p[:4]}-{p[4:6]}-{p[6:8]}'
    except Exception:
        pass
    return None


def save_cpi(records):
    """cpi 테이블 upsert. 없으면 생성"""
    if not records:
        return 0
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS cpi (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            table_id TEXT NOT NULL,
            item_name TEXT,
            value REAL,
            unit TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, table_id, item_name)
        )
    ''')
    sql = upsert_sql(
        'cpi',
        ['date', 'table_id', 'item_name', 'value', 'unit'],
        ['date', 'table_id', 'item_name'],
    )
    rows = [(r['date'], r['table_id'], r['item_name'], r['value'], r['unit']) for r in records]
    try:
        cur.executemany(sql, rows)
        conn.commit()
        saved = len(rows)
    except Exception as e:
        print(f'[KOSIS] 저장 실패: {e}')
        conn.rollback()
        saved = 0
    conn.close()
    return saved


def collect_kosis_recent():
    """최근 24개월 — KOSIS는 월별 통계라 일 1회면 충분"""
    if not _has_key():
        return 0
    now = datetime.now()
    end_period = now.strftime('%Y%m')
    start_period = f'{now.year - 2}{now.month:02d}'
    saved = 0
    for table_id in KOSIS_TABLES.values():
        recs = fetch_kosis_table(table_id, start_period, end_period)
        saved += save_cpi(recs)
    return saved


def get_cpi_for_month(date_iso, table_id='DT_1J17001'):
    """특정 월 CPI 조회 — 예측 모델 feature용"""
    conn = get_db()
    cur = conn.cursor()
    month_key = date_iso[:7] + '-01'
    cur.execute(
        'SELECT value FROM cpi WHERE date=? AND table_id=? LIMIT 1',
        (month_key, table_id),
    )
    row = cur.fetchone()
    conn.close()
    return float(row['value']) if row else None


if __name__ == '__main__':
    if not _has_key():
        print('KOSIS_API_KEY 미설정')
    else:
        n = collect_kosis_recent()
        print(f'KOSIS 24개월 적재 완료: {n}건')
