import json
import mysql.connector
from openai import OpenAI
from config import (
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
    OPENAI_API_KEY,
    EMBEDDING_MODEL
)

client = OpenAI(api_key=OPENAI_API_KEY)


def get_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )


def build_item_text(category_name, title, content, meta_rows):
    lines = [
        f"Category: {category_name}",
        f"Title: {title}"
    ]

    if content and content.strip():
        lines.append(f"Description: {content.strip()}")

    for meta_key, meta_value in meta_rows:
        if meta_value is not None and str(meta_value).strip():
            pretty_key = meta_key.replace("_", " ").title()
            lines.append(f"{pretty_key}: {str(meta_value).strip()}")

    return "\n".join(lines)


def get_embedding(text):
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text
    )
    return response.data[0].embedding


def sync_all_items():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT 
            items.id AS item_id,
            categories.name AS category_name,
            items.title,
            items.content
        FROM items
        JOIN categories ON items.category_id = categories.id
        ORDER BY items.id
    """)
    items = cursor.fetchall()

    for item in items:
        item_id = item["item_id"]

        cursor.execute("""
            SELECT meta_key, meta_value
            FROM item_meta
            WHERE item_id = %s
            ORDER BY id
        """, (item_id,))
        meta_rows_raw = cursor.fetchall()
        meta_rows = [(row["meta_key"], row["meta_value"]) for row in meta_rows_raw]

        full_text = build_item_text(
            item["category_name"],
            item["title"],
            item["content"],
            meta_rows
        )

        embedding = get_embedding(full_text)
        embedding_json = json.dumps(embedding)

        cursor.execute("SELECT id FROM ai_documents WHERE item_id = %s", (item_id,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE ai_documents
                SET content = %s, embedding = %s
                WHERE item_id = %s
            """, (full_text, embedding_json, item_id))
        else:
            cursor.execute("""
                INSERT INTO ai_documents (item_id, content, embedding)
                VALUES (%s, %s, %s)
            """, (item_id, full_text, embedding_json))

        print(f"Synced item {item_id}")

    conn.commit()
    cursor.close()
    conn.close()


if __name__ == "__main__":
    sync_all_items()