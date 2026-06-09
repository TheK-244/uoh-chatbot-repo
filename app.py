from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from config import SECRET_KEY, MAIL_SERVER, MAIL_PORT, MAIL_USE_TLS, MAIL_USERNAME, MAIL_PASSWORD
from routes import register_all_routes
from routes.auth_routes import mail

app = Flask(__name__)

# يحافظ على روابط https الصحيحة عند تشغيل المشروع خلف منصة استضافة أو reverse proxy.
# هذا مهم خصوصاً لمسار Google OAuth لأن Google يرفض أو يفشل إذا اختلف redirect_uri.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# إعدادات Flask-Mail
app.config["MAIL_SERVER"] = MAIL_SERVER
app.config["MAIL_PORT"] = MAIL_PORT
app.config["MAIL_USE_TLS"] = MAIL_USE_TLS
app.config["MAIL_USERNAME"] = MAIL_USERNAME
app.config["MAIL_PASSWORD"] = MAIL_PASSWORD
app.config["MAIL_DEFAULT_SENDER"] = MAIL_USERNAME

# ربط Flask-Mail بالتطبيق حتى يعمل إرسال OTP أثناء التسجيل وتسجيل الدخول.
mail.init_app(app)

# يسجل كل مسارات المشروع من مجلد routes.
register_all_routes(app)

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)

