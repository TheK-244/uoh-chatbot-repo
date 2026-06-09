from flask import redirect, render_template, request, session, url_for

from database import execute_fetchall, get_connection
from decorators import login_required


# يسجل مسارات طلبات المستخدم وسجل الطلبات.
def register_request_routes(app):
    # يضيف طلب سؤال جديد من المستخدم العادي.
    @app.route("/request/add", methods=["POST"])
    @login_required
    def add_user_request():
        # الأدمن يرد على الطلبات، لذلك لا يحتاج إنشاء طلب كمستخدم.
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

    # يسمح للمستخدم بتعديل طلبه قبل رد الأدمن.
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
            WHERE id = %s AND user_id = %s AND status = 'pending'
            """,
            (question, request_id, session["user_id"]),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for("home"))

    # يسمح للمستخدم بحذف طلبه قبل رد الأدمن.
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
            WHERE id = %s AND user_id = %s AND status = 'pending'
            """,
            (request_id, session["user_id"]),
        )
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for("home"))

    # يخفي الطلب من الصفحة الرئيسية بعد الرد أو التجاهل.
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

    # يعرض سجل كل طلبات المستخدم مع الحالة والإجابة.
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
