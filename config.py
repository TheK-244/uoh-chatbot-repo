import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "chatbot_db")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
TOP_K = int(os.getenv("TOP_K", "5"))

# This version uses direct allowed-site search through sitemap/homepage links.
# Google CSE keys are no longer required.
ENABLE_WEB_SEARCH = os.getenv("ENABLE_WEB_SEARCH", "true").lower() == "true"
ALLOWED_SITES = [site.strip() for site in os.getenv("ALLOWED_SITES", "uoh.edu.sa").split(",") if site.strip()]

MIN_SIMILARITY_SCORE = float(os.getenv("MIN_SIMILARITY_SCORE", "0.25"))
CLOSE_RESULT_MARGIN = float(os.getenv("CLOSE_RESULT_MARGIN", "0.04"))

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing in .env")
# إعدادات الـ Email للتحقق (OTP)
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")

# إعدادات OAuth لجوجل
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
