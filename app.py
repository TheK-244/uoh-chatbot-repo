import json
import re
from functools import wraps

import mysql.connector
import numpy as np
import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from openai import OpenAI
from werkzeug.security import check_password_hash, generate_password_hash

from config import (
    ALLOWED_SITES,
    CHAT_MODEL,
    CLOSE_RESULT_MARGIN,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    EMBEDDING_MODEL,
    ENABLE_WEB_SEARCH,
    GOOGLE_API_KEY,
    GOOGLE_CSE_ID,
    MIN_SIMILARITY_SCORE,
    OPENAI_API_KEY,
    SECRET_KEY,
    TOP_K,
)

app = Flask(__name__)
app.secret_key = SECRET_KEY
client = OpenAI(api_key=OPENAI_API_KEY)

GREETING_PATTERNS = (
    "السلام عليكم", "سلام", "هلا", "مرحبا", "اهلا", "أهلا", "صباح الخير", "مساء الخير",
    "hi", "hello", "hey", "good morning", "good evening"
)

CLARIFICATION_WORDS = (
    "أي", "اي", "حدد", "توضيح", "تقصد", "which", "clarify", "what do you mean"
)


def get_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


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


def is_greeting(text):
    normalized = text.strip().lower()
    return normalized in GREETING_PATTERNS or normalized.replace("!", "").replace(".", "") in GREETING_PATTERNS


def greeting_reply(text):
    if re.search(r"[\u0600-\u06FF]", text):
        return "وعليكم السلام، كيف أقدر أساعدك؟"
    return "Hello. How can I help you?"


def cosine_similarity(a, b):
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def get_query_embedding(text):
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def search_similar_documents(query_embedding, top_k=3):
    rows = execute_fetchall("SELECT item_id, content, embedding FROM ai_documents")
    results = []
    for row in rows:
        try:
            doc_embedding = json.loads(row["embedding"])
            score = cosine_similarity(query_embedding, doc_embedding)
            results.append({
                "item_id": row["item_id"],
                "content": row["content"],
                "score": score,
            })
        except Exception:
            continue
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def restricted_web_search(query):
    if not ENABLE_WEB_SEARCH:
        return []
    if not ALLOWED_SITES or not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return []

    site_filter = " OR ".join([f"site:{site}" for site in ALLOWED_SITES])
    search_query = f"({site_filter}) {query}"

    response = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": GOOGLE_API_KEY, "cx": GOOGLE_CSE_ID, "q": search_query, "num": 5},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("items", []):
        link = item.get("link", "")
        if any(site in link for site in ALLOWED_SITES):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": link,
            })
    return results


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


def assistant_already_asked_clarification(recent_messages):
    for msg in reversed(recent_messages[-4:]):
        if msg["role"] == "assistant" and any(word in msg["content"].lower() for word in CLARIFICATION_WORDS):
            return True
    return False


def needs_basic_clarification(user_message, results, recent_messages):
    text = user_message.strip()
    if assistant_already_asked_clarification(recent_messages):
        return False, ""

    if len(text.split()) <= 2 and not any(char.isdigit() for char in text):
        return True, "Your question is too short. Please specify the faculty member, building, office, or topic you mean."

    if not results or results[0]["score"] < MIN_SIMILARITY_SCORE:
        return True, "I need more details to answer accurately. Please mention the faculty member, building, or topic you mean."

    if len(results) >= 2:
        score_gap = results[0]["score"] - results[1]["score"]
        if score_gap <= CLOSE_RESULT_MARGIN:
            options = []
            for item in results[:3]:
                first_line = item["content"].splitlines()[0] if item["content"] else f"Item {item['item_id']}"
                title_line = next((line for line in item["content"].splitlines() if line.lower().startswith("title:")), first_line)
                options.append(title_line.replace("Title:", "").strip())
            options_text = " / ".join([o for o in options if o])
            return True, f"I found more than one possible answer. Which one do you mean: {options_text}?"

    return False, ""


def build_ai_reply(user_message, results, recent_messages, web_results=None):
    context_text = "\n\n---\n\n".join([r["content"] for r in results]) if results else ""
    web_text = ""
    if web_results:
        web_blocks = []
        for r in web_results:
            web_blocks.append(f"Title: {r['title']}\nSnippet: {r['snippet']}\nURL: {r['link']}")
        web_text = "\n\n---\n\n".join(web_blocks)

    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in recent_messages[-6:]])

    prompt = f"""
You are a university assistant.
Use the internal database context first. Use restricted web results only if internal context is missing or not enough.

Recent conversation:
{history_text}

Internal database context:
{context_text}

Restricted web results:
{web_text}

User question:
{user_message}

Rules:
- Respond in the same language as the user.
- Be concise and direct.
- If the user greets you, answer naturally without using database context.
- If the question is unclear, ask for clarification only once.
- If clarification was already requested and the user still did not clarify, give the best general answer possible and explain what detail is missing.
- If multiple answers are possible, ask the user to choose only once.
- Do not invent information.
- If using web results, mention that the answer is from the allowed websites only.
- If no answer is found, say that you did not find the information.
"""

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": "You are a careful university assistant that answers from provided context and avoids guessing."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


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


def sync_one_item(item_id):
    text = get_item_full_text(item_id)
    if not text:
        return
    embedding = client.embeddings.create(model=EMBEDDING_MODEL, input=text).data[0].embedding
    conn = get_connection()
    cursor = conn.cursor()
    # Delete + insert avoids depending on a UNIQUE index on ai_documents.item_id.
    cursor.execute("DELETE FROM ai_documents WHERE item_id = %s", (item_id,))
    cursor.execute(
        "INSERT INTO ai_documents (item_id, content, embedding) VALUES (%s, %s, %s)",
        (item_id, text, json.dumps(embedding)),
    )
    conn.commit()
    cursor.close()
    conn.close()


def parse_meta_text(meta_text):
    meta_rows = []
    for line in (meta_text or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and value:
            meta_rows.append((key, value))
    return meta_rows


@app.route("/")
@login_required
def home():
    conversations = execute_fetchall(
        "SELECT id, title, created_at FROM conversations WHERE user_id = %s ORDER BY updated_at DESC, id DESC",
        (session["user_id"],),
    )
    user_requests = []
    if not session.get("is_admin"):
        user_requests = execute_fetchall(
            """
            SELECT id, question, answer, status, created_at, answered_at, hidden_by_user
            FROM user_requests
            WHERE user_id = %s AND hidden_by_user = 0
            ORDER BY updated_at DESC, created_at DESC, id DESC
            LIMIT 20
            """,
            (session["user_id"],),
        )
    return render_template("index.html", conversations=conversations, user=session, user_requests=user_requests)




@app.route("/conversations")
@login_required
def list_conversations():
    conversations = execute_fetchall(
        """
        SELECT id, title, created_at
        FROM conversations
        WHERE user_id = %s
        ORDER BY updated_at DESC, id DESC
        """,
        (session["user_id"],),
    )
    return jsonify({"conversations": conversations})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = execute_fetchone("SELECT * FROM users WHERE email = %s", (email,))
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            session["is_admin"] = bool(user["is_admin"])
            return redirect(url_for("home"))
        return render_template("login.html", error="Invalid email or password.")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or not password:
            return render_template("register.html", error="All fields are required.")
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, is_admin) VALUES (%s, %s, %s, 0)",
                (name, email, generate_password_hash(password)),
            )
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for("login"))
        except mysql.connector.IntegrityError:
            return render_template("register.html", error="Email already exists.")
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    conversation_id = data.get("conversation_id")

    if not user_message:
        return jsonify({"reply": "Message is required."}), 400

    try:
        conversation_id = get_or_create_conversation(session["user_id"], conversation_id, user_message)
        recent_messages = get_recent_messages(conversation_id)
        save_message(conversation_id, "user", user_message)

        if is_greeting(user_message):
            reply = greeting_reply(user_message)
        else:
            query_embedding = get_query_embedding(user_message)
            results = search_similar_documents(query_embedding, top_k=TOP_K)

            should_clarify, clarification = needs_basic_clarification(user_message, results, recent_messages)
            if should_clarify:
                reply = clarification
            else:
                web_results = []
                if (not results or results[0]["score"] < MIN_SIMILARITY_SCORE) and ENABLE_WEB_SEARCH:
                    web_results = restricted_web_search(user_message)
                recent_messages = get_recent_messages(conversation_id)
                reply = build_ai_reply(user_message, results, recent_messages, web_results)

        save_message(conversation_id, "assistant", reply)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = %s", (conversation_id,))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"reply": reply, "conversation_id": conversation_id})
    except Exception as e:
        return jsonify({"reply": f"Server error: {str(e)}"}), 500


@app.route("/conversation/<int:conversation_id>")
@login_required
def load_conversation(conversation_id):
    row = execute_fetchone(
        "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
        (conversation_id, session["user_id"]),
    )
    if not row:
        return jsonify({"error": "Not found"}), 404
    messages = execute_fetchall(
        "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    )
    return jsonify({"conversation_id": conversation_id, "messages": messages})




@app.route("/conversation/<int:conversation_id>/delete", methods=["POST"])
@login_required
def delete_own_conversation(conversation_id):
    row = execute_fetchone(
        "SELECT id FROM conversations WHERE id = %s AND user_id = %s",
        (conversation_id, session["user_id"]),
    )
    if not row:
        return jsonify({"error": "Not found"}), 404

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM conversations WHERE id = %s AND user_id = %s",
        (conversation_id, session["user_id"]),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"ok": True, "deleted_id": conversation_id})


@app.route("/conversation/new", methods=["POST"])
@login_required
def new_conversation():
    conversation_id = get_or_create_conversation(session["user_id"], None, "New conversation")
    return jsonify({"conversation_id": conversation_id})


@app.route("/request/add", methods=["POST"])
@login_required
def add_user_request():
    # Admins answer requests; they should not create student requests.
    if session.get("is_admin"):
        return redirect(url_for("home"))

    question = request.form.get("question", "").strip()
    if not question:
        return redirect(url_for("home"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO user_requests (user_id, question, status, hidden_by_user) VALUES (%s, %s, 'pending', 0)",
        (session["user_id"], question),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("home"))


@app.route("/request/<int:request_id>/edit", methods=["POST"])
@login_required
def edit_user_request(request_id):
    if session.get("is_admin"):
        return redirect(url_for("home"))

    question = request.form.get("question", "").strip()
    if not question:
        return redirect(url_for("home"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE user_requests
        SET question = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND user_id = %s AND status IN ('pending', 'open')
        """,
        (question, request_id, session["user_id"]),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("home"))


@app.route("/request/<int:request_id>/delete", methods=["POST"])
@login_required
def delete_user_request(request_id):
    if session.get("is_admin"):
        return redirect(url_for("home"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        DELETE FROM user_requests
        WHERE id = %s AND user_id = %s AND status IN ('pending', 'open')
        """,
        (request_id, session["user_id"]),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("home"))


@app.route("/request/<int:request_id>/hide", methods=["POST"])
@login_required
def hide_user_request(request_id):
    if session.get("is_admin"):
        return redirect(url_for("home"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE user_requests
        SET hidden_by_user = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND user_id = %s AND status IN ('answered', 'ignored')
        """,
        (request_id, session["user_id"]),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("home"))


@app.route("/request-history")
@login_required
def request_history():
    if session.get("is_admin"):
        return redirect(url_for("admin"))

    requests_rows = execute_fetchall(
        """
        SELECT id, question, answer, status, created_at, updated_at, answered_at, hidden_by_user
        FROM user_requests
        WHERE user_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (session["user_id"],),
    )
    return render_template("request_history.html", requests_rows=requests_rows, user=session)


@app.route("/admin")
@admin_required
def admin():
    all_requests = execute_fetchall(
        """
        SELECT user_requests.id, user_requests.question, user_requests.answer,
               user_requests.status, user_requests.created_at, user_requests.updated_at,
               user_requests.answered_at, user_requests.hidden_by_user,
               users.name AS student_name, users.email AS student_email
        FROM user_requests
        JOIN users ON users.id = user_requests.user_id
        ORDER BY
            CASE user_requests.status
                WHEN 'pending' THEN 1
                WHEN 'open' THEN 1
                WHEN 'answered' THEN 2
                WHEN 'ignored' THEN 3
                ELSE 4
            END,
            user_requests.created_at DESC, user_requests.id DESC
        """
    )
    categories = execute_fetchall("SELECT id, name FROM categories ORDER BY FIELD(name, 'faculty', 'building', 'FAQ'), name")
    items = execute_fetchall(
        """
        SELECT items.id, items.title, items.content, categories.name AS category_name
        FROM items
        JOIN categories ON categories.id = items.category_id
        ORDER BY items.id DESC
        """
    )
    items_by_category = {category["name"]: [] for category in categories}
    for item in items:
        items_by_category.setdefault(item["category_name"], []).append(item)

    return render_template(
        "admin.html",
        all_requests=all_requests,
        categories=categories,
        items_by_category=items_by_category,
        user=session,
    )


@app.route("/admin/request/<int:request_id>/answer", methods=["POST"])
@admin_required
def answer_user_request(request_id):
    answer = request.form.get("answer", "").strip()
    if not answer:
        return redirect(url_for("admin"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE user_requests
        SET answer = %s, status = 'answered', answered_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (answer, request_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/admin/request/<int:request_id>/ignore", methods=["POST"])
@admin_required
def ignore_user_request(request_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE user_requests
        SET status = 'ignored', answer = NULL, answered_at = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (request_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/admin/request/<int:request_id>/reopen", methods=["POST"])
@admin_required
def reopen_user_request(request_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE user_requests
        SET status = 'pending', answer = NULL, answered_at = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (request_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/admin/item/add", methods=["POST"])
@admin_required
def add_item():
    category_id = request.form.get("category_id")
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    meta_text = request.form.get("meta", "").strip()
    if not category_id or not title:
        return redirect(url_for("admin"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO items (category_id, title, content) VALUES (%s, %s, %s)",
        (category_id, title, content),
    )
    item_id = cursor.lastrowid
    for key, value in parse_meta_text(meta_text):
        cursor.execute(
            "INSERT INTO item_meta (item_id, meta_key, meta_value) VALUES (%s, %s, %s)",
            (item_id, key, value),
        )
    conn.commit()
    cursor.close()
    conn.close()
    sync_one_item(item_id)
    return redirect(url_for("admin"))


@app.route("/admin/item/<int:item_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_item(item_id):
    item = execute_fetchone(
        """
        SELECT id, category_id, title, content
        FROM items
        WHERE id = %s
        """,
        (item_id,),
    )
    if not item:
        return redirect(url_for("admin"))

    if request.method == "POST":
        category_id = request.form.get("category_id")
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        meta_text = request.form.get("meta", "").strip()
        if not category_id or not title:
            return redirect(url_for("edit_item", item_id=item_id))

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE items SET category_id = %s, title = %s, content = %s WHERE id = %s",
            (category_id, title, content, item_id),
        )
        cursor.execute("DELETE FROM item_meta WHERE item_id = %s", (item_id,))
        for key, value in parse_meta_text(meta_text):
            cursor.execute(
                "INSERT INTO item_meta (item_id, meta_key, meta_value) VALUES (%s, %s, %s)",
                (item_id, key, value),
            )
        conn.commit()
        cursor.close()
        conn.close()
        sync_one_item(item_id)
        return redirect(url_for("admin"))

    categories = execute_fetchall("SELECT id, name FROM categories ORDER BY FIELD(name, 'faculty', 'building', 'FAQ'), name")
    meta_rows = execute_fetchall(
        "SELECT meta_key, meta_value FROM item_meta WHERE item_id = %s ORDER BY id",
        (item_id,),
    )
    meta_text = "\n".join([f"{row['meta_key']}={row['meta_value']}" for row in meta_rows])
    return render_template("edit_item.html", item=item, categories=categories, meta_text=meta_text, user=session)


@app.route("/admin/item/<int:item_id>/delete", methods=["POST"])
@admin_required
def delete_item(item_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ai_documents WHERE item_id = %s", (item_id,))
    cursor.execute("DELETE FROM item_meta WHERE item_id = %s", (item_id,))
    cursor.execute("DELETE FROM items WHERE id = %s", (item_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(debug=True)
