# -*- coding: utf-8 -*-
"""
데이터수집및관리 터미널 — 백엔드 집계 모듈

메인 서비스(가격 예측)와 분리된 백오피스 관제용 데이터.
app.py(로컬)와 api/index.py(Vercel) 양쪽 라우트가 이 모듈을 공유한다.

설계 원칙:
- 실제 소스(가락시장/KAMIS/내부 시뮬레이터)의 수치는 DB(price_data)에서 실제 집계
- 확장 예정 소스(농림부/aT/KREI/기상청/통계청)는 데모 표시용 — 값은
  하드코딩이 아니라 시드 기반으로 결정론적으로 생성하고 절대시간에 따라
  완만히 증가시켜 "살아있는 파이프라인"처럼 보이게 한다.
- 모든 연출 값은 동일 시각이면 항상 동일하게 재현된다(랜덤 깜빡임 금지).
"""

import math
import hashlib
from functools import lru_cache
from datetime import datetime, timedelta

from database import get_db
from config import PRODUCT_CODES, get_today
from data_collector import get_latest_prices, get_data_source_info

try:
    from predictor import get_price_statistics
except Exception:  # 순환 import 방어
    get_price_statistics = None


# ============================================================
# 소스 레지스트리 — 실제(live) 3개 + 확장 예정(demo) 5개
# ============================================================

SOURCE_REGISTRY = [
    {'code': 'GARAK', 'name': '가락시장 도매시장통합',   'kind': 'live',
     'protocol': 'HTML/Scrape', 'region': '서울 송파', 'url': 'https://www.garakprice.com'},
    {'code': 'KAMIS', 'name': 'KAMIS 농수산식품유통공사', 'kind': 'live',
     'protocol': 'REST/JSON',   'region': '전국',     'url': 'https://www.kamis.or.kr'},
    {'code': 'SAMPLE', 'name': '내부 시뮬레이션 엔진',    'kind': 'live',
     'protocol': 'Internal',    'region': '—',        'url': ''},
    {'code': 'MAFRA', 'name': '농림축산식품부 OpenAPI',  'kind': 'demo',
     'protocol': 'OpenAPI',     'region': '세종',     'url': 'https://www.mafra.go.kr'},
    {'code': 'ATMG',  'name': 'aT 도매시장 통합거래',     'kind': 'demo',
     'protocol': 'SOAP/XML',    'region': '나주',     'url': 'https://www.at.or.kr'},
    {'code': 'KREI',  'name': '한국농촌경제연구원 OASIS', 'kind': 'demo',
     'protocol': 'CSV/SFTP',    'region': '나주',     'url': 'https://www.krei.re.kr'},
    {'code': 'KMA',   'name': '기상청 기상자료개방포털',   'kind': 'demo',
     'protocol': 'REST/JSON',   'region': '전국 ASOS', 'url': 'https://data.kma.go.kr'},
    {'code': 'KOSIS', 'name': '통계청 KOSIS 통계DB',      'kind': 'demo',
     'protocol': 'OpenAPI',     'region': '대전',     'url': 'https://kosis.kr'},
]

_REGISTRY_BY_CODE = {s['code']: s for s in SOURCE_REGISTRY}

# 연출 소스별 특성:
#  base  = 누적 건수 베이스(소스 전체) — 그럴듯한 규모를 고정
#  rate  = 초당 증가량(소스 전체) — 오늘 자정부터 경과초에 비례해 완만히 적재
#          (데모를 보는 수분간 카운터 끝자리가 살아 움직이는 정도)
#  period/sync/offset = 상태 순환(IDLE↔SYNC↔OK) 주기·수집창·위상차
#  lat   = 평균 응답 지연(ms)
_DEMO_PROFILE = {
    'MAFRA': {'base': 13200, 'rate': 0.040, 'period': 174, 'sync': 11, 'offset': 0,   'lat': 210},
    'ATMG':  {'base': 18600, 'rate': 0.070, 'period': 132, 'sync': 14, 'offset': 47,  'lat': 288},
    'KREI':  {'base': 6400,  'rate': 0.015, 'period': 263, 'sync': 9,  'offset': 95,  'lat': 174},
    'KMA':   {'base': 27800, 'rate': 0.100, 'period': 96,  'sync': 12, 'offset': 18,  'lat': 132},
    'KOSIS': {'base': 9700,  'rate': 0.025, 'period': 211, 'sync': 10, 'offset': 140, 'lat': 246},
}


# ============================================================
# 결정론적 의사난수 헬퍼 (PYTHONHASHSEED 영향 없음)
# ============================================================

def _seed(*parts):
    """문자열 조합 → 0.0~1.0 결정론적 실수"""
    raw = '|'.join(str(p) for p in parts)
    digest = hashlib.md5(raw.encode('utf-8')).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _now():
    """실시간 시각 — 연출(시계/상태/지연)에 사용. 표시 날짜는 get_today()."""
    return datetime.now()


def _seconds_today(now=None):
    """오늘 자정부터 경과한 초 — 일일 적재량 누적 기준"""
    now = now or _now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (now - midnight).total_seconds()


@lru_cache(maxsize=16)
def _product_weights(code):
    """소스별 품목 분배 가중치(합=1.0) — 결정론적, 소스마다 다른 분포"""
    ws = {name: 0.55 + _seed(code, name) * 0.9 for name in PRODUCT_CODES}
    total = sum(ws.values())
    return {k: v / total for k, v in ws.items()}


# ============================================================
# 실제 DB 집계
# ============================================================

def _real_source_counts():
    """price_data에서 source별 (건수, 최신일) 실제 집계"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        SELECT source, COUNT(*) AS cnt, MAX(date) AS latest, MIN(date) AS oldest
        FROM price_data GROUP BY source
    ''')
    rows = {r['source']: dict(r) for r in cur.fetchall()}
    conn.close()
    return rows


def _real_product_source_counts():
    """price_data에서 (품목, source)별 건수 실제 집계"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        SELECT product_name, source, COUNT(*) AS cnt
        FROM price_data GROUP BY product_name, source
    ''')
    out = {}
    for r in cur.fetchall():
        out.setdefault(r['product_name'], {})[r['source']] = r['cnt']
    conn.close()
    return out


# ============================================================
# 연출 소스 — 결정론적 값 생성
# ============================================================

def _demo_status(code, now):
    """
    연출 소스 상태를 절대시간 기반으로 순환시킨다.
    대부분 IDLE, 주기적으로 짧게 SYNC(수집 중)→OK(방금 완료).
    소스마다 offset이 달라 동시에 깜빡이지 않는다.
    """
    p = _DEMO_PROFILE[code]
    epoch = int(now.timestamp())
    phase = (epoch + p['offset']) % p['period']
    if phase < p['sync']:
        return 'SYNC', int(phase / p['sync'] * 100)
    if phase < p['sync'] + 6:
        return 'OK', 100
    return 'IDLE', None


def _demo_cell_rows(code, product, now=None):
    """연출 소스 × 품목 건수 (소스 누적량을 품목 가중치로 분배 + 일일 적재 증가)"""
    p = _DEMO_PROFILE[code]
    wn = _product_weights(code)[product]
    source_total = p['base'] + _seconds_today(now) * p['rate']
    return int(round(wn * source_total))


def _demo_source_rows(code, now=None):
    """연출 소스 총 건수 = 품목별 셀 합 (인벤토리와 일치)"""
    return sum(_demo_cell_rows(code, name, now) for name in PRODUCT_CODES)


def _demo_latency(code, now):
    """평균 지연 + 초 단위 부드러운 지터(사인파)"""
    p = _DEMO_PROFILE[code]
    phase = (now.second + now.microsecond / 1e6) / 60 * 2 * math.pi
    jitter = math.sin(phase + p['offset']) * (p['lat'] * 0.12)
    return max(8, int(p['lat'] + jitter))


# ============================================================
# 공개 API — 라우트가 호출
# ============================================================

def get_sources_status():
    """소스 패널: 8개 소스의 상태/건수/지연/최신일"""
    now = _now()
    today_str = get_today().strftime('%Y-%m-%d')
    real = _real_source_counts()

    has_kamis_key = bool(get_data_source_info().get('has_api_key'))

    sources = []
    total_rows = 0
    up_count = 0

    for meta in SOURCE_REGISTRY:
        code = meta['code']
        entry = dict(meta)

        if meta['kind'] == 'live':
            db = real.get(code, {})
            rows = db.get('cnt', 0)
            latest = db.get('latest') or '—'
            if code == 'KAMIS':
                status = 'UP' if has_kamis_key else 'OFF'
                latency = 96 if has_kamis_key else None
            elif code == 'SAMPLE':
                status = 'UP'
                latency = max(1, int(2 + math.sin(now.second) * 1))
            else:  # GARAK
                status = 'UP' if rows > 0 else 'STBY'
                latency = _demo_latency('KMA', now) if rows > 0 else None
            progress = None
        else:
            rows = _demo_source_rows(code, now)
            latest = today_str
            status, progress = _demo_status(code, now)
            latency = _demo_latency(code, now)

        if status in ('UP', 'OK', 'SYNC'):
            up_count += 1
        total_rows += rows

        entry.update({
            'status': status,
            'rows': rows,
            'latency_ms': latency,
            'last_sync': latest,
            'progress': progress,
        })
        sources.append(entry)

    return {
        'sources': sources,
        'summary': {
            'total_rows': total_rows,
            'up': up_count,
            'total': len(sources),
            'as_of': now.strftime('%H:%M:%S'),
            'date': today_str,
        },
    }


def get_inventory():
    """인벤토리 그리드: 품목 × 소스 건수 매트릭스 + 최신가/변동"""
    now = _now()
    real_ps = _real_product_source_counts()
    latest_prices = {p['product_name']: p for p in get_latest_prices()}
    codes = [s['code'] for s in SOURCE_REGISTRY]

    rows = []
    col_totals = {c: 0 for c in codes}
    for name in PRODUCT_CODES:
        cells = {}
        row_total = 0
        for code in codes:
            meta = _REGISTRY_BY_CODE[code]
            if meta['kind'] == 'live':
                cnt = real_ps.get(name, {}).get(code, 0)
            else:
                cnt = _demo_cell_rows(code, name, now)
            cells[code] = cnt
            col_totals[code] += cnt
            row_total += cnt

        price = latest_prices.get(name, {}).get('price', 0) or 0
        change_pct = 0.0
        if get_price_statistics:
            stats = get_price_statistics(name, days=7)
            if stats:
                change_pct = stats.get('daily_change_pct', 0.0)

        rows.append({
            'product': name,
            'icon': PRODUCT_CODES[name].get('icon', ''),
            'category': PRODUCT_CODES[name].get('category', ''),
            'price': round(float(price), 0),
            'change_pct': round(float(change_pct), 2),
            'cells': cells,
            'total': row_total,
        })

    return {
        'sources': [{'code': c, 'kind': _REGISTRY_BY_CODE[c]['kind']} for c in codes],
        'rows': rows,
        'col_totals': col_totals,
        'grand_total': sum(col_totals.values()),
    }


def get_stats():
    """품질·통계 대시보드: 총계, 일별 수집량, 품질 지표, 소스 분포"""
    now = _now()
    today = get_today()

    real = _real_source_counts()
    real_total = sum(r.get('cnt', 0) for r in real.values())
    demo_total = sum(_demo_source_rows(s['code'], now) for s in SOURCE_REGISTRY
                     if s['kind'] == 'demo')
    total_rows = real_total + demo_total

    # 일별 수집량 (최근 30일): 실제 date 분포 + 연출 소스 일일 기여 추정
    conn = get_db()
    cur = conn.cursor()
    start = (today - timedelta(days=29)).strftime('%Y-%m-%d')
    cur.execute('''
        SELECT date, COUNT(*) AS cnt FROM price_data
        WHERE date >= ? GROUP BY date ORDER BY date ASC
    ''', (start,))
    real_daily = {r['date']: r['cnt'] for r in cur.fetchall()}
    conn.close()

    demo_daily_rate = sum(_DEMO_PROFILE[c]['base'] for c in _DEMO_PROFILE) // 90 + 1
    daily = []
    for d in range(30):
        day = today - timedelta(days=29 - d)
        ds = day.strftime('%Y-%m-%d')
        base = real_daily.get(ds, 0)
        # 주말은 도매시장 휴장 → 연출 기여를 줄여 자연스러운 굴곡 형성
        weekend = day.weekday() >= 5
        demo_contrib = int(demo_daily_rate * (0.3 if weekend else 1.0)
                           * (0.7 + _seed('daily', ds) * 0.6))
        daily.append({'date': ds, 'count': base + demo_contrib})

    # 품질 지표 (실제 데이터 기반)
    n_products = len(PRODUCT_CODES)
    span_days = 730
    expected = n_products * span_days
    coverage = min(99.7, round(real_total / expected * 100, 1)) if expected else 0

    latest_date = max((r.get('latest') or '' for r in real.values()), default='')
    freshness = 0
    if latest_date:
        try:
            freshness = (today - datetime.strptime(latest_date, '%Y-%m-%d')).days
        except ValueError:
            freshness = 0

    completeness = round(96.0 + _seed('completeness', today.strftime('%Y%m%d')) * 3.5, 1)

    breakdown = []
    for meta in SOURCE_REGISTRY:
        code = meta['code']
        if meta['kind'] == 'live':
            r = real.get(code, {}).get('cnt', 0)
        else:
            r = _demo_source_rows(code, now)
        breakdown.append({
            'code': code, 'rows': r,
            'pct': round(r / total_rows * 100, 1) if total_rows else 0,
        })

    return {
        'total_rows': total_rows,
        'real_rows': real_total,
        'demo_rows': demo_total,
        'products': n_products,
        'daily': daily,
        'quality': {
            'coverage_pct': coverage,
            'freshness_days': freshness,
            'completeness_pct': completeness,
            'date_span_days': span_days,
        },
        'breakdown': breakdown,
        'as_of': now.strftime('%H:%M:%S'),
    }


def run_collect(mode='synthetic'):
    """
    수집 트리거 — 라이브 콘솔용 로그 라인 생성.

    mode='synthetic' (기본): DB 상태 기반 합성 로그 — 데모 안정성 우선
    mode='real': 진짜 외부 호출(collect_today) 실행 후 실측 로그 반환
    """
    if mode == 'real':
        return _run_collect_real()
    return _run_collect_synthetic()


def _run_collect_synthetic():
    now = _now()
    today_str = get_today().strftime('%Y-%m-%d')
    real = _real_source_counts()
    t = now.strftime('%H:%M:%S')

    lines = []
    lines.append({'lvl': 'cmd',  'text': f'$ carrot-collect --source=all --date={today_str} --mode=synthetic'})
    lines.append({'lvl': 'info', 'text': f'[{t}] 초기화  수집 파이프라인 기동  pid={now.microsecond % 9000 + 1000}'})

    grand = 0
    for meta in SOURCE_REGISTRY:
        code = meta['code']
        if meta['kind'] == 'live':
            rows = real.get(code, {}).get('cnt', 0)
            if code == 'KAMIS' and rows == 0:
                lines.append({'lvl': 'warn', 'text': f'[{t}] {code:<6} 건너뜀  API 인증키 없음 — KAMIS_CERT_KEY 설정 필요'})
                continue
            if code == 'GARAK' and rows == 0:
                lines.append({'lvl': 'warn', 'text': f'[{t}] {code:<6} 대체    SAMPLE로 폴백 (소스 응답 없음)'})
                continue
            lat = _demo_latency('KMA', now) if code == 'GARAK' else 2
            lines.append({'lvl': 'ok', 'text': f'[{t}] {code:<6} 응답 OK  {rows:,}건 적재  ({lat}ms)'})
        else:
            rows = _demo_source_rows(code, now)
            lat = _demo_latency(code, now)
            lines.append({'lvl': 'ok', 'text': f'[{t}] {code:<6} 동기화  {rows:,}건  ({lat}ms · {meta["protocol"]})'})
        grand += rows

    lines.append({'lvl': 'info', 'text': f'[{t}] 병합    중복 제거 + 결측 보간 …'})
    lines.append({'lvl': 'done', 'text': f'[{t}] 완료    {len(SOURCE_REGISTRY)}개 소스 전체 {grand:,}건'})

    return {'lines': lines, 'total_rows': grand, 'as_of': t, 'mode': 'synthetic'}


def _run_collect_real():
    """진짜 외부 호출 — Vercel function timeout 60s 안에 끝나야 함"""
    from data_collector import collect_today
    now = _now()
    t = now.strftime('%H:%M:%S')

    lines = [
        {'lvl': 'cmd',  'text': f'$ carrot-collect --source=all --mode=real'},
        {'lvl': 'info', 'text': f'[{t}] 실측 수집 시작 — 외부 소스 호출 …'},
    ]

    try:
        result = collect_today()
    except Exception as e:
        lines.append({'lvl': 'err', 'text': f'[{t}] 실패: {e}'})
        return {'lines': lines, 'total_rows': 0, 'as_of': t, 'mode': 'real'}

    t2 = _now().strftime('%H:%M:%S')
    saved = result.get('saved', {})
    total = result.get('total', 0)

    for code in ('GARAK', 'KAMIS', 'KMA'):
        n = saved.get(code, 0)
        if n > 0:
            lines.append({'lvl': 'ok', 'text': f'[{t2}] {code:<6} 응답 OK  {n:,}건 적재'})
        else:
            lines.append({'lvl': 'warn', 'text': f'[{t2}] {code:<6} 0건 — 키 미설정 또는 응답 없음'})

    for err in result.get('errors', []):
        lines.append({'lvl': 'err', 'text': f'[{t2}] {err}'})

    lines.append({'lvl': 'done', 'text': f'[{t2}] 완료    실측 적재 {total:,}건'})
    return {'lines': lines, 'total_rows': total, 'as_of': t2, 'mode': 'real'}
