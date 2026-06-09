from functools import wraps

from flask import redirect, session, url_for


# يمنع الوصول للصفحة إلا بعد تسجيل الدخول.
def login_required(view):
    # ينفذ الصفحة الأصلية فقط إذا كان شرط تسجيل الدخول صحيحًا.
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# يمنع الوصول للصفحة إلا إذا كان المستخدم أدمن.
def admin_required(view):
    # ينفذ الصفحة الأصلية فقط إذا كان المستخدم أدمن.
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped
