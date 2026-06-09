import mysql.connector

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER


def get_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        use_unicode=True,
    )


def execute_fetchone(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params or ())
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def execute_fetchall(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params or ())
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def execute_commit(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    conn.commit()
    lastrowid = cursor.lastrowid
    cursor.close()
    conn.close()
    return lastrowid
