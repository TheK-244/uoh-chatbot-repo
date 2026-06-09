import os
import secrets
import mysql.connector
from flask import redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from flask_mail import Mail, Message
from requests_oauthlib import OAuth2Session

import config
from database import execute_fetchone, get_connection
from decorators import login_required

# تهيئة كائن الـ Mail الأساسي الذي سيتم ربطه بالتطبيق في app.py
mail = Mail()

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

def _external_url(endpoint):
    url = url_for(endpoint, _external=True)
    if request.headers.get("X-Forwarded-Proto", "").lower() == "https" and url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url

def _oauth_authorization_response_url():
    url = request.url
    if request.headers.get("X-Forwarded-Proto", "").lower() == "https" and url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url

def check_password_strength(password):
    if len(password) < 8:
        return "كلمة المرور يجب أن تكون 8 أحرف على الأقل."
    if not any(c.isupper() for c in password):
        return "كلمة المرور يجب أن تحتوي على حرف كبير واحد على الأقل (A-Z)."
    if not any(c.islower() for c in password):
        return "كلمة المرور يجب أن تحتوي على حرف صغير واحد على الأقل (a-z)."
    if not any(c.isdigit() for c in password):
        return "كلمة المرور يجب أن تحتوي على رقم واحد على الأقل (0-9)."
    special_chars = "!@#$%^&*()-_=+[]{}|;':\",./<>?_ "
    if not any(c in special_chars for c in password):
        return "كلمة المرور يجب أن تحتوي على رمز خاص واحد على الأقل (!@#$...)."
    return None

def register_auth_routes(app):

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if session.get("user_id"):
            return redirect(url_for("home"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not name or not email or not password or not confirm_password:
                return render_template("register.html", error="جميع الحقول مطلوبة.")

            if password != confirm_password:
                return render_template("register.html", error="كلمة المرور وتأكيد كلمة المرور غير متطابقين.")

            pwd_error = check_password_strength(password)
            if pwd_error:
                return render_template("register.html", error=pwd_error)

            # 1. فحص حالة الإيميل في قاعدة البيانات أولاً
            user = execute_fetchone("SELECT id, is_verified FROM users WHERE email = %s", (email,))
            
            if user:
                if user["is_verified"]:
                    # إذا الحساب مسجل ومفعل بالكامل، نمنع إعادة التسجيل
                    return render_template("register.html", error="هذا البريد الإلكتروني مسجل بالفعل. يرجى تسجيل الدخول.")
                else:
                    # إذا الحساب معلّق (موجود وغير مفعل)، نحدث البيانات لتفادي الـ Duplicate Entry
                    password_hash = generate_password_hash(password)
                    try:
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE users SET name = %s, password_hash = %s WHERE id = %s",
                            (name, password_hash, user["id"])
                        )
                        conn.commit()
                        cursor.close()
                        conn.close()
                    except mysql.connector.Error as err:
                        return render_template("register.html", error=f"خطأ في تحديث البيانات: {err}")
            else:
                # 2. إذا كان الحساب جديداً تماماً، نقوم بعملية الـ INSERT الطبيعية
                password_hash = generate_password_hash(password)
                try:
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO users (name, email, password_hash, is_verified) VALUES (%s, %s, %s, 0)",
                        (name, email, password_hash)
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                except mysql.connector.Error as err:
                    return render_template("register.html", error=f"خطأ في قاعدة البيانات: {err}")

            # 3. توليد كود الـ OTP وإرساله بالإيميل فوراً (لكلا الحالتين: الجديد والمعلّق)
            otp_code = str(secrets.randbelow(900000) + 100000)
            try:
                msg = Message(
                    subject="رمز التحقق الخاص بك - UOH Assistant",
                    recipients=[email],
                    body=f"مرحباً {name}،\n\nرمز التحقق الخاص بك لتفعيل حسابك هو: {otp_code}\n\nهذا الرمز صالح للاستخدام لمرة واحدة فقط."
                )
                mail.send(msg)
            except Exception as e:
                print(f"Mail send error: {e}")
                return render_template("register.html", error="تم حفظ البيانات، ولكن فشل إرسال كود التحقق. جرب تسجيل الدخول لإعادة الإرسال.")

            # 4. حفظ الكود والإيميل في الجلسة ونقله لصفحة التحقق
            session["otp_code"] = otp_code
            session["otp_email"] = email
            
            return redirect(url_for("verify_otp_page"))

        return render_template("register.html")

    @app.route("/verify-otp", methods=["GET", "POST"])
    def verify_otp_page():
        if session.get("user_id") and session.get("is_verified"):
            return redirect(url_for("home"))

        email = session.get("otp_email")
        if not email:
            return redirect(url_for("register"))

        if request.method == "POST":
            input_code = request.form.get("code", "").strip()
            session_code = session.get("otp_code")

            if not input_code or input_code != str(session_code):
                return render_template("verify_otp.html", email=email, error="كود التحقق غير صحيح، يرجى المحاولة مرة أخرى.")

            conn = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("UPDATE users SET is_verified = 1 WHERE email = %s", (email,))
            conn.commit()

            cursor.execute("SELECT id, name, email, is_admin FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()

            session.pop("otp_code", None)
            session.pop("otp_email", None)

            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            session["is_admin"] = bool(user["is_admin"])
            session["is_verified"] = True

            return redirect(url_for("home"))

        return render_template("verify_otp.html", email=email)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("user_id"):
            return redirect(url_for("home"))

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not email or not password:
                return render_template("login.html", error="جميع الحقول مطلوبة.")

            user = execute_fetchone("SELECT * FROM users WHERE email = %s", (email,))

            if not user or not user["password_hash"] or not check_password_hash(user["password_hash"], password):
                return render_template("login.html", error="البريد الإلكتروني أو كلمة المرور غير صحيحة.")

            if not user["is_verified"]:
                otp_code = str(secrets.randbelow(900000) + 100000)
                try:
                    msg = Message(
                        subject="رمز التحقق الخاص بك - UOH Assistant",
                        recipients=[email],
                        body=f"مرحباً {user['name']}،\n\nرمز التحقق الخاص بك لتفعيل حسابك هو: {otp_code}"
                    )
                    mail.send(msg)
                    session["otp_code"] = otp_code
                    session["otp_email"] = email
                    return redirect(url_for("verify_otp_page"))
                except Exception as e:
                    print(f"Mail send error: {e}")
                    return render_template("login.html", error="الحساب غير مفعل وفشل إرسال رمز التحقق حالياً.")

            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            session["is_admin"] = bool(user["is_admin"])
            session["is_verified"] = bool(user["is_verified"])
            return redirect(url_for("home"))

        return render_template("login.html")

    @app.route("/login/google")
    def google_login():
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        if not client_id:
            return "Google OAuth client ID is not configured in .env file.", 500

        google = OAuth2Session(
            client_id,
            scope=[
                "https://www.googleapis.com/auth/userinfo.profile",
                "https://www.googleapis.com/auth/userinfo.email"
            ],
            redirect_uri=_external_url("google_callback")
        )
        authorization_url, state = google.authorization_url("https://accounts.google.com/o/oauth2/v2/auth", access_type="offline")
        session["oauth_state"] = state
        return redirect(authorization_url)

    @app.route("/login/google/callback")
    def google_callback():
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        if not client_id or not client_secret:
            return "Google OAuth credentials are missing in .env file.", 500

        google = OAuth2Session(client_id, state=session.get("oauth_state"), redirect_uri=_external_url("google_callback"))
        
        try:
            google.fetch_token(
                "https://oauth2.googleapis.com/token",
                client_secret=client_secret,
                authorization_response=_oauth_authorization_response_url()
            )
        except Exception as e:
            return render_template("login.html", error=f"Google authentication failed: {e}")

        r = google.get("https://www.googleapis.com/oauth2/v1/userinfo")
        if not r.ok:
            return render_template("login.html", error="Failed to fetch user data from Google.")

        user_info = r.json()
        email = user_info.get("email", "").strip().lower()
        name = user_info.get("name", "").strip() or "Google User"
        google_id = user_info.get("id")

        if not email:
            return render_template("login.html", error="Google did not return an email address.")

        user = execute_fetchone("SELECT * FROM users WHERE email = %s", (email,))

        if user:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET oauth_provider = 'google', oauth_id = %s, is_verified = 1 WHERE id = %s",
                (google_id, user["id"])
            )
            conn.commit()
            cursor.close()
            conn.close()
            user_id = user["id"]
            name = user["name"] or name
            is_admin = bool(user["is_admin"])
        else:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO users (name, email, password_hash, is_admin, is_verified, oauth_provider, oauth_id) \n                   VALUES (%s, %s, NULL, 0, 1, 'google', %s)""",
                (name, email, google_id)
            )
            conn.commit()
            user_id = cursor.lastrowid
            cursor.close()
            conn.close()
            is_admin = False

        session.clear()
        session["user_id"] = user_id
        session["name"] = name
        session["email"] = email
        session["is_admin"] = is_admin
        session["is_verified"] = True
        return redirect(url_for("home"))


    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings():
        user = execute_fetchone(
            "SELECT id, name, email, password_hash, oauth_provider FROM users WHERE id = %s",
            (session["user_id"],),
        )
        if not user:
            session.clear()
            return redirect(url_for("login"))

        success = None
        error = None
        has_local_password = bool(user.get("password_hash"))

        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not new_password or not confirm_password:
                error = "كلمة المرور الجديدة وتأكيدها مطلوبة."
            elif has_local_password and not check_password_hash(user["password_hash"], current_password):
                error = "كلمة المرور الحالية غير صحيحة."
            elif new_password != confirm_password:
                error = "كلمة المرور الجديدة وتأكيدها غير متطابقين."
            else:
                pwd_error = check_password_strength(new_password)
                if pwd_error:
                    error = pwd_error
                else:
                    new_hash = generate_password_hash(new_password)
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE users SET password_hash = %s WHERE id = %s",
                        (new_hash, session["user_id"]),
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()
                    success = "تم تغيير كلمة المرور بنجاح."
                    has_local_password = True

        return render_template(
            "settings.html",
            user=user,
            has_local_password=has_local_password,
            success=success,
            error=error,
        )

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("welcome"))