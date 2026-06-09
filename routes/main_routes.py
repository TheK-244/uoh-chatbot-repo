from flask import redirect, render_template, session, url_for

from database import execute_fetchall


# يسجل مسارات الصفحة الرئيسية وصفحة الترحيب.
def register_main_routes(app):
    # يوجه الزائر إلى الترحيب أو يعرض صفحة الشات للمستخدم المسجل.
    @app.route("/")
    def home():
        if not session.get("user_id"):
            return redirect(url_for("welcome"))

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

    # يعرض صفحة الترحيب قبل تسجيل الدخول.
    @app.route("/welcome")
    def welcome():
        if session.get("user_id"):
            return redirect(url_for("home"))
        return render_template("welcomepage.html")
