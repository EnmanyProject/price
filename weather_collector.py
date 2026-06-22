# -*- coding: utf-8 -*-
"""
기상청 ASOS 일별 자료 수집

데이터: 평균기온·최저/최고기온·일강수량·평균습도
용도: 가격 예측 모델의 weather feature
인증키 없으면 모든 함수가 noop(0건 반환) — 안전한 fallback
"""

import requests
from datetime import datetime, timedelta

from database import get_db, upsert_sql
from config import KMA_API_URL, KMA_API_KEY, KMA_STATIONS


def _has_key():
    return bool(KMA_API_KEY)


def fetch_asos_daily(stn_id, start_dt, end_dt):
    """
    ASOS 일자료 조회 — getWthrDataList
    start_dt/end_dt: 'YYYYMMDD'
    반환: [{date, station, avg_temp, min_temp, max_temp, precipitation, humidity}, ...]
    """
    if not _has_key():
        return []

    # KMA 일자료는 익일 새벽 갱신 — 오늘/미래 포함하면 빈 응답이라 어제로 보정
    today = datetime.now().strftime('%Y%m%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    if end_dt >= today:
        end_dt = yesterday
    if start_dt > end_dt:
        return []

    params = {
        'serviceKey': KMA_API_KEY,
        'pageNo': 1,
        'numOfRows': 999,
        'dataType': 'JSON',
        'dataCd': 'ASOS',
        'dateCd': 'DAY',
        'startDt': start_dt,
        'endDt': end_dt,
        'stnIds': stn_id,
    }

    try:
        resp = requests.get(KMA_API_URL, params=params, timeout=15)
        if resp.status_code != 200:
            print(f'[KMA] HTTP {resp.status_code} (stn={stn_id})')
            return []

        data = resp.json()
        items = data.get('response', {}).get('body', {}).get('items', {}).get('item', [])
        if isinstance(items, dict):
            items = [items]

        out = []
        for it in items:
            tm = it.get('tm', '')  # 'YYYY-MM-DD'
            if not tm:
                continue
            out.append({
                'date': tm,
                'station': it.get('stnNm', stn_id),
                'avg_temp': _f(it.get('avgTa')),
                'min_temp': _f(it.get('minTa')),
                'max_temp': _f(it.get('maxTa')),
                'precipitation': _f(it.get('sumRn'), default=0.0),
                'humidity': _f(it.get('avgRhm')),
            })
        return out

    except requests.exceptions.Timeout:
        print(f'[KMA] 타임아웃 (stn={stn_id})')
    except Exception as e:
        print(f'[KMA] 호출 실패 (stn={stn_id}): {e}')

    return []


def _f(v, default=None):
    """문자열 → float, 실패하면 default"""
    if v is None or v == '':
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def save_weather(records):
    """weather 테이블에 upsert"""
    if not records:
        return 0
    conn = get_db()
    cur = conn.cursor()
    sql = upsert_sql(
        'weather',
        ['date', 'station', 'avg_temp', 'min_temp', 'max_temp', 'precipitation', 'humidity'],
        ['date', 'station'],
    )
    rows = [
        (r['date'], r['station'], r['avg_temp'], r['min_temp'],
         r['max_temp'], r['precipitation'], r['humidity'])
        for r in records
    ]
    try:
        cur.executemany(sql, rows)
        conn.commit()
        return len(rows)
    except Exception as e:
        print(f'[KMA] 저장 실패: {e}')
        conn.rollback()
        return 0
    finally:
        conn.close()


def collect_weather_today():
    """오늘 1일치 — 등록된 모든 관측소"""
    if not _has_key():
        return 0
    today = datetime.now().strftime('%Y%m%d')
    saved = 0
    for stn_id in KMA_STATIONS.values():
        recs = fetch_asos_daily(stn_id, today, today)
        saved += save_weather(recs)
    return saved


def collect_weather_history(days=730):
    """과거 N일치 — 초기 적재용. KMA API는 최대 999행/콜이라 분할 호출"""
    if not _has_key():
        return 0
    end = datetime.now()
    start = end - timedelta(days=days)
    s = start.strftime('%Y%m%d')
    e = end.strftime('%Y%m%d')
    saved = 0
    for stn_id in KMA_STATIONS.values():
        recs = fetch_asos_daily(stn_id, s, e)
        saved += save_weather(recs)
        print(f'[KMA] {stn_id}: {len(recs)}일치 적재')
    return saved


def get_weather_for_date(date_iso, station='서울'):
    """예측 모델용 — 특정 날짜·관측소의 기상값"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        'SELECT avg_temp, precipitation, humidity FROM weather '
        'WHERE date=? AND station=? LIMIT 1',
        (date_iso, station),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


if __name__ == '__main__':
    if not _has_key():
        print('KMA_API_KEY 미설정 — 키 발급 후 환경변수 등록 필요')
    else:
        n = collect_weather_history(days=730)
        print(f'2년치 적재 완료: {n}건')
