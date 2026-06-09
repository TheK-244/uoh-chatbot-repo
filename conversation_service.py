from database import execute_fetchall, execute_fetchone, get_connection


# يجلب محادثة موجودة أو ينشئ محادثة جديدة للمستخدم.
def get_or_create_conversation(user_id, conversation_id=None, first_message=None):
    if conversation_id:
        row = execute_fetchone(
            "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        )
        if row:
            return row["id"]

    title = (first_message or "New conversation").strip()[:80]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
        (user_id, title),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


# يحفظ رسالة المستخدم أو المساعد داخل قاعدة البيانات.
def save_message(conversation_id, role, content):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
        (conversation_id, role, content),
    )
    conn.commit()
    cursor.close()
    conn.close()


# يجلب آخر الرسائل من المحادثة لاستخدامها كسياق.
def get_recent_messages(conversation_id, limit=8):
    rows = execute_fetchall(
        """
        SELECT role, content
        FROM messages
        WHERE conversation_id = %s
        ORDER BY id DESC
        LIMIT %s
        """,
        (conversation_id, limit),
    )
    return list(reversed(rows))


# يحدث وقت آخر نشاط للمحادثة حتى تظهر في أعلى القائمة.
def touch_conversation(conversation_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (conversation_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()
