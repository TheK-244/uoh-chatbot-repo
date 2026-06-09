from flask import redirect, render_template, request, session, url_for

from database import execute_fetchall, execute_fetchone, get_connection
from decorators import admin_required
from item_service import parse_meta_text, sync_one_item


# يسجل مسارات لوحة الأدمن وإدارة البيانات والطلبات.
def register_admin_routes(app):
    # يعرض لوحة الأدمن مع الطلبات وعناصر المعرفة مقسمة حسب التصنيف.
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
                    WHEN 'answered' THEN 2
                    WHEN 'ignored' THEN 3
                    ELSE 4
                END,
                user_requests.created_at DESC, user_requests.id DESC
            """
        )
        categories = execute_fetchall("SELECT id, name FROM categories ORDER BY FIELD(name, 'faculty', 'building', 'faq'), name")
        items = execute_fetchall(
            """
            SELECT items.id, items.title, items.content, categories.name AS category_name
            FROM items
            JOIN categories ON categories.id = items.category_id
            ORDER BY items.id DESC
            """
        )
        meta_rows = execute_fetchall(
            """
            SELECT item_id, meta_key, meta_value
            FROM item_meta
            ORDER BY id
            """
        )
        meta_by_item = {}
        for row in meta_rows:
            meta_by_item.setdefault(row["item_id"], []).append(row)

        items_by_category = {category["name"]: [] for category in categories}
        for item in items:
            item["meta_rows"] = meta_by_item.get(item["id"], [])
            items_by_category.setdefault(item["category_name"], []).append(item)

        return render_template(
            "admin.html",
            all_requests=all_requests,
            categories=categories,
            items_by_category=items_by_category,
            user=session,
        )

    # يحفظ رد الأدمن على طلب المستخدم ويغير حالته إلى تمت الإجابة.
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

    # يحول طلب المستخدم إلى مهمل بدون إجابة.
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

    # يعيد الطلب المهمل أو المجاب إلى حالة الانتظار.
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

    # يضيف عنصر معرفة جديد ويزامنه مع ai_documents.
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

    # يعرض نموذج تعديل العنصر ويحفظ التغييرات عند الإرسال.
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

        categories = execute_fetchall("SELECT id, name FROM categories ORDER BY FIELD(name, 'faculty', 'building', 'faq'), name")
        meta_rows = execute_fetchall(
            "SELECT meta_key, meta_value FROM item_meta WHERE item_id = %s ORDER BY id",
            (item_id,),
        )
        meta_text = "\n".join([f"{row['meta_key']}={row['meta_value']}" for row in meta_rows])
        return render_template("edit_item.html", item=item, categories=categories, meta_text=meta_text, user=session)

    # يحذف عنصر المعرفة وكل البيانات المرتبطة به.
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
