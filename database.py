"""
데이터베이스 어댑터 — Postgres(Neon) / SQLite 듀얼 호환

DATABASE_URL 환경변수가 있으면 Postgres, 없으면 로컬 SQLite로 폴백.
호출 측 코드는 `?` placeholder만 사용 — Postgres 사용 시 자동으로 `%s` 변환.
row는 양쪽 모두 dict-like 접근 가능 (`row['col']`).
"""

import os
import sqlite3
from config import DATABASE_PATH

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
IS_POSTGRES = DATABASE_URL.startswith(('postgres://', 'postgresql://'))

if IS_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row


class _CursorWrapper:
    """`?` placeholder를 Postgres `%s`로 자동 변환하는 cursor 래퍼"""

    def __init__(self, real_cursor, is_postgres):
        self._cur = real_cursor
        self._is_pg = is_postgres

    def execute(self, sql, params=()):
        if self._is_pg:
            sql = sql.replace('?', '%s')
        return self._cur.execute(sql, params)

    def executemany(self, sql, seq):
        if self._is_pg:
            sql = sql.replace('?', '%s')
        return self._cur.executemany(sql, seq)

    def fetchall(self):
        return self._cur.fetchall()

    def fetchone(self):
        return self._cur.fetchone()

    def __iter__(self):
        return iter(self._cur)

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _ConnWrapper:
    def __init__(self, real_conn, is_postgres):
        self._conn = real_conn
        self._is_pg = is_postgres

    def cursor(self):
        if self._is_pg:
            return _CursorWrapper(self._conn.cursor(row_factory=dict_row), True)
        return _CursorWrapper(self._conn.cursor(), False)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_db():
    """DB 연결 — DATABASE_URL이 있으면 Postgres, 없으면 SQLite"""
    if IS_POSTGRES:
        # Neon은 sslmode=require가 URL에 이미 포함됨
        return _ConnWrapper(psycopg.connect(DATABASE_URL), True)

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return _ConnWrapper(conn, False)


# ============================================================
# 스키마 — dialect별로 PK/AUTOINCREMENT 처리만 다름
# ============================================================

_SCHEMA_SQLITE = [
    '''
    CREATE TABLE IF NOT EXISTS price_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        price REAL NOT NULL,
        date TEXT NOT NULL,
        market TEXT DEFAULT '전국평균',
        unit TEXT DEFAULT 'kg',
        source TEXT DEFAULT 'KAMIS',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(product_name, date, market)
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        predicted_price REAL NOT NULL,
        predicted_date TEXT NOT NULL,
        confidence_lower REAL,
        confidence_upper REAL,
        model_type TEXT DEFAULT 'ARIMA',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS weather (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        station TEXT NOT NULL,
        avg_temp REAL,
        min_temp REAL,
        max_temp REAL,
        precipitation REAL,
        humidity REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, station)
    )
    ''',
    'CREATE INDEX IF NOT EXISTS idx_price_product_date ON price_data(product_name, date)',
    'CREATE INDEX IF NOT EXISTS idx_weather_date ON weather(date)',
]

_SCHEMA_POSTGRES = [
    '''
    CREATE TABLE IF NOT EXISTS price_data (
        id SERIAL PRIMARY KEY,
        product_name TEXT NOT NULL,
        price REAL NOT NULL,
        date TEXT NOT NULL,
        market TEXT DEFAULT '전국평균',
        unit TEXT DEFAULT 'kg',
        source TEXT DEFAULT 'KAMIS',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(product_name, date, market)
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS predictions (
        id SERIAL PRIMARY KEY,
        product_name TEXT NOT NULL,
        predicted_price REAL NOT NULL,
        predicted_date TEXT NOT NULL,
        confidence_lower REAL,
        confidence_upper REAL,
        model_type TEXT DEFAULT 'ARIMA',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''',
    '''
    CREATE TABLE IF NOT EXISTS weather (
        id SERIAL PRIMARY KEY,
        date TEXT NOT NULL,
        station TEXT NOT NULL,
        avg_temp REAL,
        min_temp REAL,
        max_temp REAL,
        precipitation REAL,
        humidity REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, station)
    )
    ''',
    'CREATE INDEX IF NOT EXISTS idx_price_product_date ON price_data(product_name, date)',
    'CREATE INDEX IF NOT EXISTS idx_weather_date ON weather(date)',
]


def init_db():
    """스키마 생성 (idempotent)"""
    if not IS_POSTGRES:
        os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

    conn = get_db()
    cursor = conn.cursor()
    schema = _SCHEMA_POSTGRES if IS_POSTGRES else _SCHEMA_SQLITE
    for ddl in schema:
        cursor.execute(ddl)
    conn.commit()
    conn.close()


def upsert_sql(table, columns, conflict_cols):
    """
    INSERT ... ON CONFLICT(...) DO UPDATE — Postgres/SQLite 양쪽 호환 SQL 생성
    (SQLite 3.24+ / Postgres 9.5+ 모두 지원)
    """
    cols = ', '.join(columns)
    placeholders = ', '.join(['?'] * len(columns))
    conflict = ', '.join(conflict_cols)
    update_cols = [c for c in columns if c not in conflict_cols]
    if update_cols:
        updates = ', '.join(f'{c}=EXCLUDED.{c}' for c in update_cols)
        return (
            f'INSERT INTO {table} ({cols}) VALUES ({placeholders}) '
            f'ON CONFLICT ({conflict}) DO UPDATE SET {updates}'
        )
    return (
        f'INSERT INTO {table} ({cols}) VALUES ({placeholders}) '
        f'ON CONFLICT ({conflict}) DO NOTHING'
    )


if __name__ == '__main__':
    init_db()
    backend = 'Postgres (Neon)' if IS_POSTGRES else f'SQLite ({DATABASE_PATH})'
    print(f'데이터베이스 초기화 완료 — {backend}')
