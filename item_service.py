import json

from config import EMBEDDING_MODEL
from retrieval_service import client
from database import execute_fetchall, execute_fetchone, get_connection


# يجمع بيانات العنصر والميتا في نص واحد للذكاء الاصطناعي.
def get_item_full_text(item_id):
    item = execute_fetchone(
        """
        SELECT items.id, categories.name AS category_name, items.title, items.content
        FROM items
        JOIN categories ON items.category_id = categories.id
        WHERE items.id = %s
        """,
        (item_id,),
    )
    if not item:
        return None

    meta_rows = execute_fetchall(
        "SELECT meta_key, meta_value FROM item_meta WHERE item_id = %s ORDER BY id",
        (item_id,),
    )
    lines = [f"Category: {item['category_name']}", f"Title: {item['title']}"]
    if item.get("content"):
        lines.append(f"Description: {item['content']}")
    for row in meta_rows:
        if row.get("meta_value"):
            lines.append(f"{row['meta_key'].replace('_', ' ').title()}: {row['meta_value']}")
    return "\n".join(lines)


# يحدث أو ينشئ سجل العنصر داخل جدول ai_documents.
def sync_one_item(item_id):
    text = get_item_full_text(item_id)
    if not text:
        return

    embedding = client.embeddings.create(model=EMBEDDING_MODEL, input=text).data[0].embedding
    conn = get_connection()
    cursor = conn.cursor()
    # الحذف ثم الإضافة يمنع الاعتماد على وجود فهرس UNIQUE في ai_documents.item_id.
    cursor.execute("DELETE FROM ai_documents WHERE item_id = %s", (item_id,))
    cursor.execute(
        "INSERT INTO ai_documents (item_id, content, embedding) VALUES (%s, %s, %s)",
        (item_id, text, json.dumps(embedding)),
    )
    conn.commit()
    cursor.close()
    conn.close()


# يحول نص الميتا المكتوب في الفورم إلى أزواج key و value.
def parse_meta_text(meta_text):
    """Parse admin extra fields safely.

    Supported formats:
        office=Room 101
        office: Room 101
        email name@uoh.edu.sa   -> stored as note_1

    The previous parser accepted only key=value. If the admin wrote
    "key: value" or pasted plain notes, the edit route deleted old metadata
    and inserted nothing. This parser keeps the information instead of
    silently dropping it.
    """
    meta_rows = []
    seen_keys = set()
    note_index = 1

    for raw_line in (meta_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            key, value = f"note_{note_index}", line
            note_index += 1

        key = key.strip().lower().replace(" ", "_")[:100]
        value = value.strip()
        if not key or not value:
            continue

        # Avoid duplicate keys in the same textarea. Keep the latest visible line.
        if key in seen_keys:
            meta_rows = [row for row in meta_rows if row[0] != key]
        seen_keys.add(key)
        meta_rows.append((key, value))

    return meta_rows
