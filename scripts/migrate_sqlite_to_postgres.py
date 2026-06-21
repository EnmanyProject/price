"""
로컬 SQLite (data/prices.db) → Neon Postgres 일회성 마이그레이션

사용법 (PowerShell):
    $env:DATABASE_URL = "postgres://user:pass@host/db?sslmode=require"
    python scripts/migrate_sqlite_to_postgres.py

멱등성: upsert_sql 사용 — 여러 번 돌려도 중복 안 생김.
"""

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DATABASE_PATH
from database import IS_POSTGRES, init_db, get_db, upsert_sql


def main():
    if not IS_POSTGRES:
        print('[중단] DATABASE_URL 환경변수가 없거나 Postgres URL이 아닙니다.')
        print('       예: $env:DATABASE_URL = "postgres://...@neon.tech/...?sslmode=require"')
        sys.exit(1)

    if not os.path.exists(DATABASE_PATH):
        print(f'[중단] 로컬 SQLite를 찾을 수 없습니다: {DATABASE_PATH}')
        sys.exit(1)

    print(f'[1/4] Postgres 스키마 생성 …')
    init_db()

    print(f'[2/4] 로컬 SQLite 읽기 — {DATABASE_PATH}')
    src = sqlite3.connect(DATABASE_PATH)
    src.row_factory = sqlite3.Row

    price_rows = src.execute(
        'SELECT product_name, price, date, market, source FROM price_data'
    ).fetchall()
    pred_rows = src.execute(
        'SELECT product_name, predicted_price, predicted_date, '
        'confidence_lower, confidence_upper, model_type FROM predictions'
    ).fetchall()
    src.close()

    print(f'        - price_data {len(price_rows):,}건')
    print(f'        - predictions {len(pred_rows):,}건')

    print(f'[3/4] Postgres로 upsert …')
    conn = get_db()
    cur = conn.cursor()

    if price_rows:
        sql = upsert_sql(
            'price_data',
            ['product_name', 'price', 'date', 'market', 'source'],
            ['product_name', 'date', 'market'],
        )
        cur.executemany(sql, [tuple(r) for r in price_rows])

    if pred_rows:
        cur.executemany(
            'INSERT INTO predictions '
            '(product_name, predicted_price, predicted_date, '
            'confidence_lower, confidence_upper, model_type) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            [tuple(r) for r in pred_rows],
        )

    conn.commit()

    print(f'[4/4] 검증 …')
    cur.execute('SELECT COUNT(*) AS cnt FROM price_data')
    pg_price = cur.fetchone()['cnt']
    cur.execute('SELECT COUNT(*) AS cnt FROM predictions')
    pg_pred = cur.fetchone()['cnt']
    conn.close()

    print(f'        Postgres price_data:  {pg_price:,}건')
    print(f'        Postgres predictions: {pg_pred:,}건')
    print('완료.')


if __name__ == '__main__':
    main()
