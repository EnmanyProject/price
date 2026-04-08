import sqlite3
import os
from config import DATABASE_PATH

def get_db():
    """데이터베이스 연결"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """데이터베이스 초기화"""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
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
    ''')

    cursor.execute('''
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
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_price_product_date
        ON price_data(product_name, date)
    ''')

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("데이터베이스 초기화 완료!")
