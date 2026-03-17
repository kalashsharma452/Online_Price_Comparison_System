from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_compress import Compress
import os
import json
import hashlib
import re
import smtplib
import time
import uuid
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import tensorflow as tf
import psycopg2
import jwt
import bcrypt
import redis
from psycopg2.extras import RealDictCursor
import requests
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash as werkzeug_check_password_hash
from flask import send_from_directory
from PIL import Image
from tensorflow.keras.applications.imagenet_utils import decode_predictions
from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken
try:
    # Package-style imports (works with: flask --app backend.app ...)
    from .preprocessing import preprocess_for_efficientnet
    from .scrapers.ebay_mock import search_ebay_products as search_ebay_products_mock
    from .scrapers.platzi_api import search_platzi_products
    from .scrapers.dummyjson_api import search_dummyjson_products
    from .scrapers.amazon_scraper import search_amazon_products
    from .scrapers.ebay_scraper import search_ebay_products as search_ebay_products_scrape
    from .scrapers.walmart_scraper import search_walmart_products
    from .comparison import compare_prices
    from .scrapers.ebay_official import search_ebay_products
    from .auth_routes import register_auth_routes
    from .catalog_routes import register_catalog_routes
except ImportError:
    # Script-style imports (works with: python app.py from backend/)
    from preprocessing import preprocess_for_efficientnet
    from scrapers.ebay_mock import search_ebay_products as search_ebay_products_mock
    from scrapers.platzi_api import search_platzi_products
    from scrapers.dummyjson_api import search_dummyjson_products
    from scrapers.amazon_scraper import search_amazon_products
    from scrapers.ebay_scraper import search_ebay_products as search_ebay_products_scrape
    from scrapers.walmart_scraper import search_walmart_products
    from comparison import compare_prices
    from scrapers.ebay_official import search_ebay_products
    from auth_routes import register_auth_routes
    from catalog_routes import register_catalog_routes

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB
app.config["SECRET_KEY"] = (os.getenv("SECRET_KEY") or "price-intelligence-secret").strip()
app.config["COMPRESS_MIMETYPES"] = ["application/json", "text/html", "text/css", "application/javascript"]
app.config["COMPRESS_LEVEL"] = int(os.getenv("COMPRESS_LEVEL", "6"))
Compress(app)
if app.config["SECRET_KEY"] == "price-intelligence-secret":
    print("WARNING: SECRET_KEY is using the default value. Set SECRET_KEY in production.")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._]+$")
THUMBNAIL_SUFFIX = "__thumb"
THUMBNAIL_SIZE = (480, 480)
UPLOAD_RESULT_CACHE_SECONDS = int(os.getenv("UPLOAD_RESULT_CACHE_SECONDS", str(60 * 60 * 24)))


def _env_flag(name, default=True):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


FORCE_HTTPS = _env_flag("FORCE_HTTPS", False)
TRUST_PROXY_HEADERS = _env_flag("TRUST_PROXY_HEADERS", True)
CORS_ALLOW_CREDENTIALS = _env_flag("CORS_ALLOW_CREDENTIALS", True)


def _parse_cors_origins(raw_value):
    if not raw_value:
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    return [origin.strip() for origin in raw_value.split(",") if origin.strip()]


CORS_ALLOWED_ORIGINS = _parse_cors_origins(os.getenv("CORS_ALLOWED_ORIGINS", ""))

CORS(
    app,
    resources={r"/api/*": {"origins": CORS_ALLOWED_ORIGINS}},
    supports_credentials=CORS_ALLOW_CREDENTIALS,
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    max_age=3600,
)

ENABLE_EBAY = _env_flag("ENABLE_EBAY", _env_flag("EBAY", True))
_EBAY_MASTER_EXPLICIT = os.getenv("ENABLE_EBAY") is not None or os.getenv("EBAY") is not None
if _EBAY_MASTER_EXPLICIT and not ENABLE_EBAY:
    # Master kill-switch: EBAY=false (or ENABLE_EBAY=false) disables both paths.
    ENABLE_EBAY_OFFICIAL = False
    ENABLE_EBAY_SCRAPER = False
else:
    ENABLE_EBAY_OFFICIAL = _env_flag("ENABLE_EBAY_OFFICIAL", ENABLE_EBAY)
    ENABLE_EBAY_SCRAPER = _env_flag("ENABLE_EBAY_SCRAPER", ENABLE_EBAY)

USD_TO_INR = float(os.getenv("USD_TO_INR", "83.0"))
EUR_TO_INR = float(os.getenv("EUR_TO_INR", "90.0"))
GBP_TO_INR = float(os.getenv("GBP_TO_INR", "105.0"))
JPY_TO_INR = float(os.getenv("JPY_TO_INR", "0.56"))
AUD_TO_INR = float(os.getenv("AUD_TO_INR", "54.0"))
CAD_TO_INR = float(os.getenv("CAD_TO_INR", "61.0"))
CURRENCY_TO_INR_RATES = {
    "INR": 1.0,
    "USD": USD_TO_INR,
    "EUR": EUR_TO_INR,
    "GBP": GBP_TO_INR,
    "JPY": JPY_TO_INR,
    "AUD": AUD_TO_INR,
    "CAD": CAD_TO_INR,
}
FX_CACHE_SECONDS = int(os.getenv("FX_CACHE_SECONDS", "21600"))  # 6 hours
FX_CACHE = {"loaded_at": 0.0, "rates_to_inr": dict(CURRENCY_TO_INR_RATES)}
SCRAPE_CACHE_SECONDS = int(os.getenv("SCRAPE_CACHE_SECONDS", "300"))  # 5 minutes
SCRAPE_CACHE = {}
SCRAPE_HEALTH_LOG = []
SCRAPE_HEALTH_MAX = 200
CACHE_PREFIX = (os.getenv("CACHE_PREFIX") or "price-intel").strip()
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
API_RESPONSE_CACHE_SECONDS = int(os.getenv("API_RESPONSE_CACHE_SECONDS", "180"))
USER_DASHBOARD_CACHE_SECONDS = int(os.getenv("USER_DASHBOARD_CACHE_SECONDS", "120"))
POPULAR_SEARCH_CACHE_SECONDS = int(os.getenv("POPULAR_SEARCH_CACHE_SECONDS", "300"))
LOCAL_RESPONSE_CACHE = {}
LOCAL_CACHE_VERSIONS = {}
REDIS_CLIENT = None
SCRAPER_MAX_WORKERS = int(os.getenv("SCRAPER_MAX_WORKERS", "3"))
SCRAPE_EXECUTOR = ThreadPoolExecutor(max_workers=max(SCRAPER_MAX_WORKERS, 2))
SCRAPE_RESULT_LIMIT = int(os.getenv("SCRAPE_RESULT_LIMIT", "30"))
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", str(60 * 60 * 24)))
SLOW_REQUEST_MS = int(os.getenv("SLOW_REQUEST_MS", "750"))
API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", "120"))
API_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("API_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_STORE = {}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
TARGET_SIZE = (224, 224)
MODEL_INSTANCE = None
MODEL_LOCK = Lock()
IST_TZ = timezone(timedelta(hours=5, minutes=30))
JWT_SECRET = (os.getenv("JWT_SECRET") or app.config["SECRET_KEY"]).strip()
JWT_ALGORITHM = (os.getenv("JWT_ALGORITHM") or "HS256").strip()
JWT_EXPIRY_SECONDS = int(os.getenv("JWT_EXPIRY_SECONDS", str(60 * 60 * 24 * 7)))
PASSWORD_RESET_EXPIRY_SECONDS = int(os.getenv("PASSWORD_RESET_EXPIRY_SECONDS", str(60 * 30)))
SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = (os.getenv("SMTP_USERNAME") or "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or ""
SMTP_FROM_EMAIL = (os.getenv("SMTP_FROM_EMAIL") or SMTP_USERNAME or "").strip()
SMTP_USE_TLS = _env_flag("SMTP_USE_TLS", True)
UPLOAD_CDN_BASE = (os.getenv("UPLOAD_CDN_BASE") or "").strip().rstrip("/")
MALWARE_SCAN_ENABLED = _env_flag("MALWARE_SCAN_ENABLED", False)
MALWARE_SCAN_COMMAND = (os.getenv("MALWARE_SCAN_COMMAND") or "clamscan").strip()
CREDENTIALS_ENCRYPTION_KEY = (os.getenv("CREDENTIALS_ENCRYPTION_KEY") or "").strip()
FERNET_INSTANCE = None


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required and must point to PostgreSQL.")
    if DATABASE_URL.lower().startswith("sqlite"):
        raise RuntimeError("SQLite is not allowed. Use PostgreSQL (or MySQL/MongoDB).")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            phone TEXT,
            postal_code TEXT,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS email TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS phone TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS postal_code TEXT
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id SERIAL PRIMARY KEY,
            image_id TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            predictions_json TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            product_id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            image_url TEXT,
            brand TEXT,
            source_query TEXT,
            details_json TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            price_id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL,
            store_name TEXT NOT NULL,
            price DOUBLE PRECISION NOT NULL CHECK(price >= 0),
            timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            product_url TEXT NOT NULL,
            availability TEXT,
            seller_rating DOUBLE PRECISION,
            currency TEXT,
            original_price DOUBLE PRECISION,
            original_currency TEXT,
            source_query TEXT,
            details_json TEXT,
            FOREIGN KEY(product_id) REFERENCES products(product_id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS search_history (
            search_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS price_alerts (
            alert_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            query_text TEXT NOT NULL,
            target_price DOUBLE PRECISION NOT NULL CHECK(target_price >= 0),
            notification_channel TEXT NOT NULL DEFAULT 'in_app',
            contact_email TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_triggered BOOLEAN NOT NULL DEFAULT FALSE,
            last_checked_at TIMESTAMP,
            triggered_at TIMESTAMP,
            last_triggered_price DOUBLE PRECISION,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_notifications (
            notification_id SERIAL PRIMARY KEY,
            alert_id INTEGER NOT NULL REFERENCES price_alerts(alert_id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message TEXT NOT NULL,
            matched_price DOUBLE PRECISION,
            matched_product_name TEXT,
            matched_store_name TEXT,
            matched_product_url TEXT,
            delivery_channel TEXT NOT NULL DEFAULT 'in_app',
            delivery_status TEXT NOT NULL DEFAULT 'delivered',
            is_read BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wishlist_items (
            wishlist_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            store_name TEXT,
            current_price DOUBLE PRECISION,
            product_url TEXT NOT NULL,
            image_url TEXT,
            source_query TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, product_url)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS third_party_credentials (
            credential_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            label TEXT NOT NULL,
            encrypted_value TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, provider, label)
        )
        """
    )
    cursor.execute(
        """
        ALTER TABLE price_alerts
        ADD COLUMN IF NOT EXISTS notification_channel TEXT NOT NULL DEFAULT 'in_app'
        """
    )
    cursor.execute(
        """
        ALTER TABLE price_alerts
        ADD COLUMN IF NOT EXISTS contact_email TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE price_alerts
        ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE
        """
    )
    cursor.execute(
        """
        ALTER TABLE price_alerts
        ADD COLUMN IF NOT EXISTS is_triggered BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    cursor.execute(
        """
        ALTER TABLE price_alerts
        ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMP
        """
    )
    cursor.execute(
        """
        ALTER TABLE price_alerts
        ADD COLUMN IF NOT EXISTS triggered_at TIMESTAMP
        """
    )
    cursor.execute(
        """
        ALTER TABLE price_alerts
        ADD COLUMN IF NOT EXISTS last_triggered_price DOUBLE PRECISION
        """
    )
    cursor.execute(
        """
        ALTER TABLE price_alerts
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        """
    )
    cursor.execute(
        """
        ALTER TABLE price_alerts
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        """
    )
    cursor.execute(
        """
        ALTER TABLE wishlist_items
        ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general'
        """
    )
    cursor.execute(
        """
        ALTER TABLE wishlist_items
        ADD COLUMN IF NOT EXISTS store_name TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE wishlist_items
        ADD COLUMN IF NOT EXISTS current_price DOUBLE PRECISION
        """
    )
    cursor.execute(
        """
        ALTER TABLE wishlist_items
        ADD COLUMN IF NOT EXISTS image_url TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE wishlist_items
        ADD COLUMN IF NOT EXISTS source_query TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS brand TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS source_query TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS details_json TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE prices
        ADD COLUMN IF NOT EXISTS availability TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE prices
        ADD COLUMN IF NOT EXISTS seller_rating DOUBLE PRECISION
        """
    )
    cursor.execute(
        """
        ALTER TABLE prices
        ADD COLUMN IF NOT EXISTS currency TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE prices
        ADD COLUMN IF NOT EXISTS original_price DOUBLE PRECISION
        """
    )
    cursor.execute(
        """
        ALTER TABLE prices
        ADD COLUMN IF NOT EXISTS original_currency TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE prices
        ADD COLUMN IF NOT EXISTS source_query TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE prices
        ADD COLUMN IF NOT EXISTS details_json TEXT
        """
    )
    cursor.execute(
        """
        ALTER TABLE wishlist_items
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prices_product_time
        ON prices(product_id, timestamp DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_search_history_user_time
        ON search_history(user_id, timestamp DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_name
        ON products(name)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prices_store_name
        ON prices(store_name)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_search_history_query
        ON search_history(query)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_price_alerts_user_active
        ON price_alerts(user_id, is_active, created_at DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_price_alerts_query
        ON price_alerts(query_text)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alert_notifications_user_read
        ON alert_notifications(user_id, is_read, created_at DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wishlist_items_user_created
        ON wishlist_items(user_id, created_at DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_users_email_lower
        ON users(LOWER(email))
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_uploads_user_uploaded
        ON uploads(user_id, uploaded_at DESC, id DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prices_product_store_time
        ON prices(product_id, store_name, timestamp DESC, price_id DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_search_history_user_query_time
        ON search_history(user_id, query, timestamp DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_name_lower
        ON products(LOWER(name))
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_credentials_user
        ON third_party_credentials(user_id, provider)
        """
    )
    conn.commit()
    cursor.close()
    conn.close()


def allowed_image_file(file):
    _, ext = os.path.splitext(file.filename.lower())
    return ext in ALLOWED_EXTENSIONS and file.mimetype in ALLOWED_MIME_TYPES


def _get_fernet():
    global FERNET_INSTANCE
    if FERNET_INSTANCE is not None:
        return FERNET_INSTANCE
    if not CREDENTIALS_ENCRYPTION_KEY:
        return None
    try:
        FERNET_INSTANCE = Fernet(CREDENTIALS_ENCRYPTION_KEY)
    except Exception:
        FERNET_INSTANCE = None
    return FERNET_INSTANCE


def _encrypt_secret(value):
    fernet = _get_fernet()
    if not fernet:
        return None
    return fernet.encrypt(str(value).encode("utf-8")).decode("utf-8")


def _decrypt_secret(value):
    fernet = _get_fernet()
    if not fernet or not value:
        return None
    try:
        return fernet.decrypt(str(value).encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def _mask_secret(value):
    if not value:
        return None
    tail = value[-4:] if len(value) >= 4 else value
    return f"****{tail}"


def _validate_image_stream(file_storage):
    try:
        stream = file_storage.stream
        original_pos = stream.tell()
        stream.seek(0)
        try:
            with Image.open(stream) as img:
                img.verify()
                if (img.format or "").upper() not in ALLOWED_IMAGE_FORMATS:
                    return False, "Unsupported image format"
        except Exception:
            if os.getenv("ALLOW_FAKE_TEST_UPLOADS", "").strip().lower() in {"1", "true", "yes"}:
                return True, None
            return False, "Invalid or corrupted image file"
        stream.seek(original_pos)
    except Exception:
        try:
            stream.seek(original_pos)
        except Exception:
            pass
        return False, "Invalid or corrupted image file"
    return True, None


def _scan_for_malware(filepath):
    if not MALWARE_SCAN_ENABLED:
        return True, None
    # Execute an external scanner (e.g., ClamAV) if configured.
    scanner = MALWARE_SCAN_COMMAND or "clamscan"
    if not shutil.which(scanner):
        return False, "Malware scanner is not available on the server"
    try:
        result = subprocess.run(
            [scanner, "--no-summary", filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        return False, "Malware scanner failed"

    if result.returncode == 0:
        return True, None
    if result.returncode == 1:
        return False, "Malware detected in uploaded file"
    return False, "Malware scan returned an error"


def create_token(user_id):
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "user_id": int(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=JWT_EXPIRY_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _is_bcrypt_hash(password_hash):
    value = str(password_hash or "")
    return value.startswith(("$2a$", "$2b$", "$2y$"))


def _check_password(password, password_hash):
    if not password_hash:
        return False
    stored_value = str(password_hash)
    if stored_value.startswith(("pbkdf2:", "scrypt:")):
        try:
            return werkzeug_check_password_hash(stored_value, password)
        except (ValueError, TypeError):
            return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_value.encode("utf-8"))
    except ValueError:
        # Older local databases may still contain pre-bcrypt plaintext values.
        return stored_value == password


def _create_password_reset_token(user_id, email):
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "user_id": int(user_id),
        "email": email,
        "scope": "password_reset",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=PASSWORD_RESET_EXPIRY_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_password_reset_token(token, verify_exp=True):
    payload = jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
        options={"verify_exp": verify_exp},
    )
    if payload.get("scope") != "password_reset":
        raise jwt.InvalidTokenError("Invalid token scope")
    return payload


def get_user_id_from_request():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    try:
        return int(payload.get("user_id") or payload.get("sub"))
    except (TypeError, ValueError):
        return None


def require_user():
    user_id = getattr(g, "user_id", None)
    if not user_id:
        user_id = get_user_id_from_request()
    if not user_id:
        return None, (jsonify({"status": "error", "error": "Unauthorized"}), 401)
    g.user_id = user_id
    return user_id, None


def auth_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({"status": "error", "error": "Unauthorized"}), 401
        g.user_id = user_id
        return view_func(*args, **kwargs)

    return wrapper


def _build_public_user_payload(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row.get("email"),
        "phone": row.get("phone"),
        "postal_code": row.get("postal_code"),
        "created_at": _convert_datetimes_to_ist(row.get("created_at")),
    }


def _get_model():
    global MODEL_INSTANCE
    if MODEL_INSTANCE is not None:
        return MODEL_INSTANCE
    with MODEL_LOCK:
        if MODEL_INSTANCE is None:
            MODEL_INSTANCE = tf.keras.applications.EfficientNetB0(weights="imagenet")
    return MODEL_INSTANCE


def _build_upload_url(filename):
    if not filename:
        return None
    if UPLOAD_CDN_BASE:
        return f"{UPLOAD_CDN_BASE}/{filename}"
    return f"{request.host_url.rstrip('/')}/api/uploads/{filename}"


def _build_thumbnail_filename(filename):
    if not filename:
        return None
    stem, ext = os.path.splitext(filename)
    return f"{stem}{THUMBNAIL_SUFFIX}{ext}"


def _build_upload_asset_urls(filename):
    thumbnail_filename = _build_thumbnail_filename(filename)
    thumbnail_path = os.path.join(UPLOAD_FOLDER, thumbnail_filename) if thumbnail_filename else None
    thumbnail_url = _build_upload_url(thumbnail_filename) if thumbnail_path and os.path.isfile(thumbnail_path) else None
    return {
        "image_url": _build_upload_url(filename),
        "thumbnail_url": thumbnail_url,
    }


def _compute_upload_sha256(file_storage):
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return None
    try:
        original_position = stream.tell()
        stream.seek(0)
        hasher = hashlib.sha256()
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
        stream.seek(0)
        return hasher.hexdigest()
    except Exception:
        try:
            stream.seek(original_position)
        except Exception:
            pass
        return None


def _ensure_upload_thumbnail(filepath, filename):
    thumbnail_filename = _build_thumbnail_filename(filename)
    if not thumbnail_filename:
        return None
    thumbnail_path = os.path.join(UPLOAD_FOLDER, thumbnail_filename)
    try:
        with Image.open(filepath) as img:
            thumb = img.convert("RGB")
            thumb.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            thumb.save(thumbnail_path, optimize=True, quality=82)
        return thumbnail_filename
    except Exception:
        return None


def _get_redis_client():
    global REDIS_CLIENT
    if not REDIS_URL:
        return None
    if REDIS_CLIENT is not None:
        return REDIS_CLIENT
    try:
        REDIS_CLIENT = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
        REDIS_CLIENT.ping()
    except Exception:
        REDIS_CLIENT = None
    return REDIS_CLIENT


def _cache_full_key(namespace, raw_key):
    digest = hashlib.sha256(str(raw_key).encode("utf-8")).hexdigest()
    return f"{CACHE_PREFIX}:{namespace}:{digest}"


def _cache_get(namespace, raw_key):
    key = _cache_full_key(namespace, raw_key)
    client = _get_redis_client()
    if client:
        try:
            payload = client.get(key)
            return json.loads(payload) if payload else None
        except Exception:
            pass

    cached = LOCAL_RESPONSE_CACHE.get(key)
    if not cached:
        return None
    if time.time() >= cached["expires_at"]:
        LOCAL_RESPONSE_CACHE.pop(key, None)
        return None
    return json.loads(json.dumps(cached["value"]))


def _cache_set(namespace, raw_key, value, ttl_seconds):
    key = _cache_full_key(namespace, raw_key)
    serialized = json.dumps(value)
    client = _get_redis_client()
    if client:
        try:
            client.setex(key, int(ttl_seconds), serialized)
            return
        except Exception:
            pass
    LOCAL_RESPONSE_CACHE[key] = {
        "expires_at": time.time() + int(ttl_seconds),
        "value": json.loads(serialized),
    }


def _get_cache_version(scope):
    client = _get_redis_client()
    if client:
        try:
            value = client.get(f"{CACHE_PREFIX}:version:{scope}")
            return int(value) if value is not None else 1
        except Exception:
            pass
    return int(LOCAL_CACHE_VERSIONS.get(scope, 1))


def _bump_cache_version(scope):
    client = _get_redis_client()
    if client:
        try:
            client.incr(f"{CACHE_PREFIX}:version:{scope}")
            return
        except Exception:
            pass
    LOCAL_CACHE_VERSIONS[scope] = _get_cache_version(scope) + 1


def _user_cache_scope(user_id):
    return f"user:{int(user_id)}"


def _explain_query(cursor, sql, params=()):
    cursor.execute("EXPLAIN " + sql, tuple(params))
    return [row.get("QUERY PLAN") or next(iter(row.values())) for row in cursor.fetchall()]


def _record_scrape_health(items):
    if not items:
        return
    SCRAPE_HEALTH_LOG.extend(items)
    if len(SCRAPE_HEALTH_LOG) > SCRAPE_HEALTH_MAX:
        del SCRAPE_HEALTH_LOG[:len(SCRAPE_HEALTH_LOG) - SCRAPE_HEALTH_MAX]


def _run_scrape_tasks(task_defs):
    if not task_defs:
        return [], []

    futures = {
        SCRAPE_EXECUTOR.submit(task["fn"], *task.get("args", ()), **task.get("kwargs", {})): task
        for task in task_defs
    }
    results = []
    health = []
    for future in as_completed(futures):
        task = futures[future]
        try:
            rows = future.result()
            row_count = len(rows or [])
            health.append({
                "provider": task["provider"],
                "status": "ok" if row_count else "empty",
                "rows": row_count,
            })
            if rows:
                results.append({"provider": task["provider"], "rows": rows})
        except Exception as exc:
            health.append({
                "provider": task["provider"],
                "status": "error",
                "rows": 0,
                "error": str(exc),
            })
            print(f"{task['provider']} failed:", exc)
    _record_scrape_health(health)
    return results, health


def _rate_limit_key():
    forwarded_for = (request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    return (request.remote_addr or "unknown").strip()


def _consume_rate_limit_bucket(identity):
    now = time.time()
    key = str(identity or "unknown").strip() or "unknown"
    # Prefer Redis for distributed rate limiting across multiple instances.
    client = _get_redis_client()
    if client:
        window = int(API_RATE_LIMIT_WINDOW_SECONDS)
        window_id = int(now // window)
        redis_key = f"{CACHE_PREFIX}:ratelimit:{key}:{window_id}"
        try:
            count = int(client.incr(redis_key))
            if count == 1:
                client.expire(redis_key, window)
            remaining = max(API_RATE_LIMIT - count, 0)
            allowed = count <= API_RATE_LIMIT
            retry_after = max(int(window - (now - (window_id * window))), 1) if not allowed else 0
            return allowed, remaining, retry_after
        except Exception:
            pass

    bucket = RATE_LIMIT_STORE.get(key)
    if not bucket or now >= bucket["window_ends_at"]:
        bucket = {
            "count": 0,
            "window_ends_at": now + API_RATE_LIMIT_WINDOW_SECONDS,
        }
        RATE_LIMIT_STORE[key] = bucket

    if bucket["count"] < API_RATE_LIMIT:
        bucket["count"] += 1
        remaining = max(API_RATE_LIMIT - bucket["count"], 0)
        return True, remaining, 0

    retry_after = max(int(bucket["window_ends_at"] - now), 1)
    return False, 0, retry_after


def _sanitize_text(value, max_len=255, allow_newlines=False):
    if value is None:
        return ""
    text = str(value)
    if allow_newlines:
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    else:
        text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    if "<" in text or ">" in text:
        text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"(?i)javascript:", "", text)
    text = re.sub(r"(?i)on[a-z0-9_]+\\s*=", "", text)
    text = re.sub(r"\\s+", " ", text).strip()
    if max_len and len(text) > max_len:
        text = text[:max_len].strip()
    return text


def _sanitize_query_param(value, max_len=255):
    if value is None:
        return ""
    return _sanitize_text(value, max_len=max_len)


def _validate_non_empty_text(value, field_name, max_len=255):
    if not isinstance(value, str):
        return None, f"{field_name} must be a string"
    cleaned = _sanitize_text(value, max_len=max_len)
    if not cleaned:
        return None, f"{field_name} is required"
    return cleaned, None


def _validate_optional_text(value, field_name, max_len=255):
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{field_name} must be a string"
    cleaned = _sanitize_text(value, max_len=max_len)
    return cleaned or None, None


def _validate_optional_url(value, field_name="url"):
    cleaned, err = _validate_optional_text(value, field_name, max_len=2000)
    if err or cleaned is None:
        return cleaned, err
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        return None, f"{field_name} must start with http:// or https://"
    return cleaned, None


def _validate_required_url(value, field_name="url"):
    cleaned, err = _validate_non_empty_text(value, field_name, max_len=2000)
    if err:
        return None, err
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        return None, f"{field_name} must start with http:// or https://"
    return cleaned, None


def _validate_optional_email(value, field_name="contact_email"):
    cleaned, err = _validate_optional_text(value, field_name, max_len=320)
    if err or cleaned is None:
        return cleaned, err
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", cleaned):
        return None, f"{field_name} must be a valid email address"
    return cleaned, None


def _validate_required_email(value, field_name="email"):
    cleaned, err = _validate_optional_email(value, field_name=field_name)
    if err:
        return None, err
    if not cleaned:
        return None, f"{field_name} is required"
    return cleaned, None


def _validate_positive_int(value, field_name):
    try:
        int_value = int(value)
    except (TypeError, ValueError):
        return None, f"{field_name} must be an integer"
    if int_value <= 0:
        return None, f"{field_name} must be > 0"
    return int_value, None


def _validate_non_negative_price(value):
    try:
        price_value = float(value)
    except (TypeError, ValueError):
        return None, "price must be a number"
    if price_value < 0:
        return None, "price must be >= 0"
    return price_value, None


def _parse_timestamp(value, field_name="timestamp"):
    if value in (None, ""):
        return None, None
    if not isinstance(value, str):
        return None, f"{field_name} must be an ISO timestamp string"
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw), None
    except ValueError:
        return None, f"{field_name} must be ISO format, e.g. 2026-02-27T12:30:00+00:00"


def _to_ist_iso(value):
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IST_TZ).isoformat(timespec="seconds")


def _convert_datetimes_to_ist(value):
    if isinstance(value, datetime):
        return _to_ist_iso(value)
    if isinstance(value, list):
        return [_convert_datetimes_to_ist(item) for item in value]
    if isinstance(value, dict):
        return {key: _convert_datetimes_to_ist(item) for key, item in value.items()}
    return value


def _parse_limit_offset():
    try:
        limit = min(max(int(request.args.get("limit", 20)), 1), 200)
    except ValueError:
        limit = 20
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        offset = 0
    return limit, offset


def _parse_page_per_page(default_per_page=20, max_per_page=50):
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        return None, None, "page must be an integer"
    try:
        per_page = int(request.args.get("per_page", default_per_page))
    except ValueError:
        return None, None, "per_page must be an integer"

    if page <= 0:
        return None, None, "page must be >= 1"
    if per_page <= 0:
        return None, None, "per_page must be >= 1"
    per_page = min(per_page, max_per_page)
    return page, per_page, None


def _paginate_rows(rows, page, per_page):
    total = len(rows or [])
    total_pages = (total + per_page - 1) // per_page if total else 0
    start = (page - 1) * per_page
    end = start + per_page
    items = (rows or [])[start:end]
    return items, {
        "page": page,
        "per_page": per_page,
        "total_items": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1 and total_pages > 0,
    }


def _build_comparison_filters():
    filters = {}

    min_seller_rating_raw = (request.args.get("min_seller_rating") or "").strip()
    if min_seller_rating_raw:
        try:
            min_seller_rating = float(min_seller_rating_raw)
        except ValueError:
            return None, "min_seller_rating must be a number"
        if min_seller_rating < 0 or min_seller_rating > 5:
            return None, "min_seller_rating must be between 0 and 5"
        filters["min_seller_rating"] = min_seller_rating

    max_shipping_cost_raw = (request.args.get("max_shipping_cost") or "").strip()
    if max_shipping_cost_raw:
        try:
            max_shipping_cost = float(max_shipping_cost_raw)
        except ValueError:
            return None, "max_shipping_cost must be a number"
        if max_shipping_cost < 0:
            return None, "max_shipping_cost must be >= 0"
        filters["max_shipping_cost"] = max_shipping_cost

    availability_raw = (request.args.get("availability") or "").strip().lower()
    if availability_raw:
        allowed = {"any", "in_stock", "out_of_stock"}
        if availability_raw not in allowed:
            return None, "availability must be one of: any, in_stock, out_of_stock"
        filters["availability"] = availability_raw

    tax_rate_raw = (request.args.get("tax_rate") or "").strip()
    if tax_rate_raw:
        try:
            tax_rate_value = float(tax_rate_raw)
        except ValueError:
            return None, "tax_rate must be a number"
        if tax_rate_value < 0:
            return None, "tax_rate must be >= 0"
        if tax_rate_value > 1:
            if tax_rate_value <= 100:
                tax_rate_value = tax_rate_value / 100.0
            else:
                return None, "tax_rate > 1 must be a percentage between 0 and 100"
        filters["tax_rate"] = tax_rate_value

    weight_price_raw = (request.args.get("weight_price") or "").strip()
    weight_shipping_raw = (request.args.get("weight_shipping") or "").strip()
    weight_reputation_raw = (request.args.get("weight_reputation") or "").strip()
    if weight_price_raw or weight_shipping_raw or weight_reputation_raw:
        weights = {}
        for key, raw_value in (
            ("price", weight_price_raw),
            ("shipping", weight_shipping_raw),
            ("reputation", weight_reputation_raw),
        ):
            if not raw_value:
                continue
            try:
                parsed = float(raw_value)
            except ValueError:
                return None, f"{key} weight must be a number"
            if parsed < 0:
                return None, f"{key} weight must be >= 0"
            weights[key] = parsed
        if not weights:
            return None, "At least one scoring weight must be provided"
        filters["weights"] = weights

    return filters, None


def _build_search_terms(product, identifier, predictions, max_terms=3):
    terms = []
    if identifier:
        cleaned_identifier = _sanitize_text(identifier, max_len=120)
        if cleaned_identifier:
            terms.append(cleaned_identifier)
    if product:
        cleaned_product = _sanitize_text(product, max_len=120)
        if cleaned_product:
            terms.append(cleaned_product)

    top_prediction = (predictions or [None])[0] or {}
    top_label = (top_prediction.get("label") or "").replace("_", " ").strip()
    if top_label:
        terms.append(top_label)

    unique = []
    seen = set()
    for term in terms:
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(term)
        if len(unique) >= max_terms:
            break
    return unique


def _canonical_search_query(value):
    raw = _sanitize_text(value or "", max_len=500)
    if not raw:
        return ""
    primary = raw.split("|", 1)[0].strip()
    return primary or raw


def _get_predictions_from_upload(user_id, image_id=None):
    conn = get_db()
    cursor = conn.cursor()
    if image_id:
        cursor.execute(
            """
            SELECT predictions_json
            FROM uploads
            WHERE user_id = %s AND image_id = %s
            ORDER BY uploaded_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, image_id),
        )
    else:
        cursor.execute(
            """
            SELECT predictions_json
            FROM uploads
            WHERE user_id = %s
            ORDER BY uploaded_at DESC, id DESC
            LIMIT 1
            """,
            (user_id,),
        )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return []
    try:
        value = json.loads(row["predictions_json"])
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _safe_price(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _infer_currency_code(item):
    currency = (item.get("currency") or "").strip().upper()
    if currency:
        return currency

    store = (item.get("store") or item.get("store_name") or "").strip().lower()
    if "walmart" in store or "ebay" in store:
        return "USD"
    if "amazon" in store:
        return "INR"
    return "INR"


def _refresh_live_fx_rates_if_needed():
    now = time.time()
    if now - FX_CACHE["loaded_at"] < FX_CACHE_SECONDS:
        return

    try:
        # Free endpoint: base USD with broad currency coverage.
        response = requests.get("https://open.er-api.com/v6/latest/USD", timeout=6)
        response.raise_for_status()
        payload = response.json()
        rates = payload.get("rates", {}) if isinstance(payload, dict) else {}
        inr_per_usd = float(rates.get("INR", 0))
        if inr_per_usd <= 0:
            raise ValueError("Missing INR rate")

        updated = {"INR": 1.0}
        for code in ("USD", "EUR", "GBP", "JPY", "AUD", "CAD"):
            if code == "USD":
                updated["USD"] = inr_per_usd
                continue
            per_usd = float(rates.get(code, 0))
            if per_usd > 0:
                # rates are currency-per-USD, so INR-per-currency = INR-per-USD / currency-per-USD
                updated[code] = inr_per_usd / per_usd

        # Keep configured fallbacks for anything missing.
        merged = dict(CURRENCY_TO_INR_RATES)
        merged.update(updated)
        FX_CACHE["rates_to_inr"] = merged
        FX_CACHE["loaded_at"] = now
    except Exception:
        # Keep fallback rates if live fetch fails.
        FX_CACHE["rates_to_inr"] = dict(CURRENCY_TO_INR_RATES)
        FX_CACHE["loaded_at"] = now


def _convert_results_to_inr(items):
    _refresh_live_fx_rates_if_needed()
    rates_map = FX_CACHE.get("rates_to_inr", CURRENCY_TO_INR_RATES)

    converted = []
    for raw in items or []:
        row = dict(raw)
        price_value = _safe_price(row.get("price"))
        if price_value is None:
            converted.append(row)
            continue

        original_currency = _infer_currency_code(row)
        rate = rates_map.get(original_currency, rates_map.get("USD", USD_TO_INR))
        converted_price = round(price_value * rate, 2)

        row["original_price"] = price_value
        row["original_currency"] = original_currency
        row["conversion_rate_to_inr"] = round(rate, 6)
        row["price"] = converted_price
        row["currency"] = "INR"
        converted.append(row)
    return converted


def _normalize_result_product(raw_product):
    if not isinstance(raw_product, dict):
        return None

    name = (
        raw_product.get("name")
        or raw_product.get("title")
        or raw_product.get("product_name")
        or ""
    ).strip()
    if not name:
        return None

    price_value = _safe_price(raw_product.get("price"))
    if price_value is None:
        return None

    store_name = (
        raw_product.get("store")
        or raw_product.get("store_name")
        or raw_product.get("source")
        or "Unknown"
    ).strip() or "Unknown"

    product_url = (
        raw_product.get("url")
        or raw_product.get("product_url")
        or raw_product.get("link")
        or ""
    ).strip()
    if not product_url:
        product_url = _build_fallback_product_url(raw_product, name=name, store_name=store_name)

    image_url = (
        raw_product.get("image_url")
        or raw_product.get("image")
        or raw_product.get("thumbnail")
        or None
    )

    category = _infer_result_category(raw_product, name)
    brand = _clean_result_text(raw_product.get("brand"), max_len=120)
    availability = _clean_result_text(raw_product.get("availability"), max_len=120)
    source_query = _clean_result_text(raw_product.get("source_query"), max_len=255)
    seller_rating = _safe_rating(raw_product.get("seller_rating"))
    currency = (raw_product.get("currency") or "").strip().upper() or "INR"
    original_currency = (raw_product.get("original_currency") or "").strip().upper() or currency
    original_price = _safe_price(raw_product.get("original_price"))
    details_json = _serialize_result_details(raw_product)

    return {
        "name": name,
        "category": category,
        "image_url": image_url,
        "brand": brand,
        "source_query": source_query,
        "availability": availability,
        "seller_rating": seller_rating,
        "currency": currency,
        "original_price": original_price if original_price is not None else price_value,
        "original_currency": original_currency,
        "details_json": details_json,
        "store_name": store_name,
        "price": price_value,
        "product_url": product_url,
    }


def _build_fallback_product_url(raw_product, name, store_name):
    category = _infer_result_category(raw_product, name).lower()
    image_url = (
        raw_product.get("image_url")
        or raw_product.get("image")
        or raw_product.get("thumbnail")
        or ""
    )
    identity = "|".join(
        [
            str(name or "").strip().lower(),
            str(store_name or "").strip().lower(),
            category,
            str(image_url or "").strip().lower(),
        ]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"internal://product/{digest}"


def _clean_result_text(value, max_len=255):
    if value is None:
        return None
    cleaned = _sanitize_text(str(value).replace("_", " "), max_len=max_len)
    if not cleaned:
        return None
    return cleaned


def _infer_result_category(raw_product, fallback_name=""):
    for key in ("category", "department", "type"):
        candidate = _clean_result_text(raw_product.get(key), max_len=120)
        if candidate and candidate.lower() != "general":
            return candidate
    source_query = _clean_result_text(raw_product.get("source_query"), max_len=120)
    if source_query:
        return source_query
    fallback = _clean_result_text(fallback_name, max_len=120)
    return fallback or "general"


def _safe_rating(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if 0 <= parsed <= 5 else None
    match = re.search(r"([0-5](?:\.[0-9]+)?)", str(value))
    if not match:
        return None
    parsed = float(match.group(1))
    return parsed if 0 <= parsed <= 5 else None


def _serialize_result_details(raw_product):
    if not isinstance(raw_product, dict):
        return None
    try:
        return json.dumps(raw_product, default=str)
    except Exception:
        return None


def _normalize_wishlist_item(raw_item):
    if not isinstance(raw_item, dict):
        return None, "payload must be a JSON object"

    product_name, err = _validate_non_empty_text(
        raw_item.get("product_name") or raw_item.get("name") or raw_item.get("title"),
        "product_name",
        max_len=255,
    )
    if err:
        return None, err

    product_url, err = _validate_required_url(
        raw_item.get("product_url") or raw_item.get("url") or raw_item.get("link"),
        "product_url",
    )
    if err:
        return None, err

    category, err = _validate_optional_text(raw_item.get("category"), "category", max_len=120)
    if err:
        return None, err

    store_name, err = _validate_optional_text(
        raw_item.get("store_name") or raw_item.get("store"),
        "store_name",
        max_len=120,
    )
    if err:
        return None, err

    current_price = None
    if raw_item.get("current_price") is not None or raw_item.get("price") is not None:
        current_price, err = _validate_non_negative_price(
            raw_item.get("current_price") if raw_item.get("current_price") is not None else raw_item.get("price")
        )
        if err:
            return None, "current_price must be a number >= 0"

    image_url, err = _validate_optional_url(
        raw_item.get("image_url") or raw_item.get("image") or raw_item.get("thumbnail"),
        "image_url",
    )
    if err:
        return None, err

    source_query, err = _validate_optional_text(raw_item.get("source_query"), "source_query", max_len=255)
    if err:
        return None, err

    return {
        "product_name": product_name,
        "category": category or "general",
        "store_name": store_name,
        "current_price": current_price,
        "product_url": product_url,
        "image_url": image_url,
        "source_query": source_query,
    }, None


def _persist_search_products(raw_products):
    normalized_rows = []
    for raw_product in raw_products or []:
        normalized = _normalize_result_product(raw_product)
        if normalized:
            normalized_rows.append(normalized)

    if not normalized_rows:
        return 0

    conn = get_db()
    cursor = conn.cursor()
    inserted_count = 0
    try:
        for row in normalized_rows:
            product_id = _find_or_create_product_id(cursor, row)
            if not _insert_price_if_new(cursor, product_id, row):
                continue
            inserted_count += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    return inserted_count


def _find_or_create_product_id(cursor, row):
    cursor.execute(
        """
        SELECT p.product_id, p.image_url, p.category, p.brand, p.source_query, p.details_json
        FROM products p
        JOIN prices pr ON pr.product_id = p.product_id
        WHERE LOWER(pr.store_name) = LOWER(%s)
          AND pr.product_url = %s
        ORDER BY pr.timestamp DESC, pr.price_id DESC
        LIMIT 1
        """,
        (row["store_name"], row["product_url"]),
    )
    existing = cursor.fetchone()
    if existing:
        should_update = (
            (row.get("image_url") and not existing.get("image_url"))
            or ((not existing.get("category")) or str(existing.get("category")).strip().lower() == "general")
            or (row.get("brand") and not existing.get("brand"))
            or (row.get("source_query") and not existing.get("source_query"))
            or (row.get("details_json") and not existing.get("details_json"))
        )
        if should_update:
            cursor.execute(
                """
                UPDATE products
                SET image_url = COALESCE(%s, image_url),
                    category = CASE
                        WHEN category IS NULL OR TRIM(category) = '' OR LOWER(category) = 'general' THEN %s
                        ELSE category
                    END,
                    brand = COALESCE(brand, %s),
                    source_query = COALESCE(source_query, %s),
                    details_json = COALESCE(%s, details_json)
                WHERE product_id = %s
                """,
                (
                    row["image_url"],
                    row["category"],
                    row["brand"],
                    row["source_query"],
                    row["details_json"],
                    existing["product_id"],
                ),
            )
        return existing["product_id"]

    cursor.execute(
        """
        INSERT INTO products (name, category, image_url, brand, source_query, details_json)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING product_id
        """,
        (row["name"], row["category"], row["image_url"], row["brand"], row["source_query"], row["details_json"]),
    )
    return cursor.fetchone()["product_id"]


def _insert_price_if_new(cursor, product_id, row):
    cursor.execute(
        """
        SELECT price_id
        FROM prices
        WHERE product_id = %s
          AND LOWER(store_name) = LOWER(%s)
          AND price = %s
          AND product_url = %s
        LIMIT 1
        """,
        (product_id, row["store_name"], row["price"], row["product_url"]),
    )
    if cursor.fetchone():
        return False

    cursor.execute(
        """
        INSERT INTO prices (
            product_id, store_name, price, product_url, availability, seller_rating,
            currency, original_price, original_currency, source_query, details_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            product_id,
            row["store_name"],
            row["price"],
            row["product_url"],
            row["availability"],
            row["seller_rating"],
            row["currency"],
            row["original_price"],
            row["original_currency"],
            row["source_query"],
            row["details_json"],
        ),
    )
    return True


def _save_search_history(user_id, query):
    normalized_query = (query or "").strip()
    if not normalized_query:
        return

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO search_history (user_id, query)
            VALUES (%s, %s)
            """,
            (user_id, normalized_query),
        )
        conn.commit()
        _bump_cache_version(_user_cache_scope(user_id))
        _bump_cache_version("popular_searches")
    finally:
        cursor.close()
        conn.close()



def _dedupe_scraped_products(rows):
    deduped = []
    seen_keys = set()
    for item in rows or []:
        key = (
            (item.get("store") or item.get("store_name") or "").strip().lower(),
            (item.get("name") or item.get("title") or "").strip().lower(),
            (item.get("url") or item.get("product_url") or "").strip(),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)
    return deduped


def _normalize_match_text(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _query_tokens(query):
    stopwords = {
        "the", "and", "for", "with", "from", "new", "best", "to", "of", "in", "on", "at",
        "a", "an", "by", "or",
    }
    tokens = [t for t in _normalize_match_text(query).split() if len(t) >= 3 and t not in stopwords]
    unique = []
    seen = set()
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        unique.append(t)
    return unique


def _token_matches_text(token, text):
    if token in text:
        return True
    if token.endswith("s") and len(token) > 3 and token[:-1] in text:
        return True
    if not token.endswith("s") and f"{token}s" in text:
        return True
    return False


def _is_relevant_result(item, query):
    tokens = _query_tokens(query)
    if not tokens:
        return True

    phrase = _normalize_match_text(query)
    searchable = " ".join(
        [
            item.get("name") or item.get("title") or "",
            item.get("category") or "",
            item.get("source_query") or "",
        ]
    )
    searchable_text = _normalize_match_text(searchable)
    if phrase and phrase in searchable_text:
        return True

    matches = sum(1 for token in tokens if _token_matches_text(token, searchable_text))
    if len(tokens) == 1:
        return matches >= 1
    if len(tokens) == 2:
        return matches >= 1
    return matches >= max(1, (len(tokens) + 2) // 3)


def _normalize_notification_channel(value):
    channel = str(value or "in_app").strip().lower()
    if channel not in {"in_app", "email"}:
        return None
    return channel


def _serialize_price_alert(row):
    return _convert_datetimes_to_ist(dict(row)) if row else row


def _serialize_notification(row):
    return _convert_datetimes_to_ist(dict(row)) if row else row


def _build_trend_points(rows):
    grouped = {}
    for row in rows or []:
        timestamp_value = row.get("timestamp")
        if not isinstance(timestamp_value, datetime):
            continue
        bucket_key = timestamp_value.date().isoformat()
        bucket = grouped.setdefault(bucket_key, {"prices": [], "timestamp": timestamp_value})
        bucket["prices"].append(float(row["price"]))
        if timestamp_value > bucket["timestamp"]:
            bucket["timestamp"] = timestamp_value

    points = []
    for bucket_key in sorted(grouped.keys()):
        bucket = grouped[bucket_key]
        prices = bucket["prices"]
        points.append({
            "date": bucket_key,
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            "average_price": round(sum(prices) / len(prices), 2),
            "sample_count": len(prices),
            "timestamp": bucket["timestamp"],
        })
    return points


def _recommendation_score(row, recent_queries, wishlist_names):
    name_text = _normalize_match_text(row.get("name"))
    score = 0
    matched_terms = set()
    for query in recent_queries:
        for token in _query_tokens(query):
            if token and token in name_text:
                score += 2
                matched_terms.add(token)
    for token in wishlist_names:
        if token and token in name_text:
            score += 3
            matched_terms.add(token)
    if row.get("price_count"):
        score += min(int(row["price_count"]), 5)
    return score, sorted(matched_terms)


def _find_best_alert_match(cursor, query_text):
    cursor.execute(
        """
        SELECT DISTINCT ON (pr.product_id, pr.store_name)
            pr.price_id,
            pr.product_id,
            pr.store_name,
            pr.price,
            pr.timestamp,
            pr.product_url,
            p.name,
            p.category,
            p.image_url
        FROM prices pr
        JOIN products p ON p.product_id = pr.product_id
        ORDER BY pr.product_id, pr.store_name, pr.timestamp DESC, pr.price_id DESC
        """
    )
    rows = cursor.fetchall()
    matches = []
    for row in rows:
        if not _is_relevant_result(row, query_text):
            continue
        matches.append(row)
    if not matches:
        return None
    matches.sort(key=lambda row: (float(row["price"]), row["timestamp"]), reverse=False)
    return matches[0]


def _send_alert_email(recipient_email, subject, message):
    if not recipient_email:
        return "email_skipped"
    if not (SMTP_HOST and SMTP_FROM_EMAIL):
        return "email_not_configured"

    email_message = EmailMessage()
    email_message["Subject"] = subject
    email_message["From"] = SMTP_FROM_EMAIL
    email_message["To"] = recipient_email
    email_message.set_content(message)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(email_message)
        return "email_sent"
    except Exception:
        return "email_failed"


def _send_password_reset_email(recipient_email, reset_token):
    reset_link = f"{(os.getenv('FRONTEND_URL') or 'http://127.0.0.1:3000').rstrip('/')}/?reset_token={reset_token}"
    message = (
        "We received a request to reset your password.\n\n"
        f"Use this link to set a new password: {reset_link}\n\n"
        f"This link expires in {PASSWORD_RESET_EXPIRY_SECONDS // 60} minutes."
    )
    return _send_alert_email(recipient_email, "Reset your Price Intelligence password", message)


def _evaluate_price_alerts(conn, alert_ids=None):
    cursor = conn.cursor()
    notifications = []
    try:
        sql = """
            SELECT alert_id, user_id, query_text, target_price, notification_channel, contact_email,
                   is_active, is_triggered, last_checked_at, triggered_at, last_triggered_price,
                   created_at, updated_at
            FROM price_alerts
            WHERE is_active = TRUE
        """
        params = []
        if alert_ids:
            sql += " AND alert_id = ANY(%s)"
            params.append(list(alert_ids))
        sql += " ORDER BY created_at DESC, alert_id DESC"
        cursor.execute(sql, tuple(params))
        alerts = cursor.fetchall()

        now = datetime.utcnow()
        for alert in alerts:
            match = _find_best_alert_match(cursor, alert["query_text"])
            should_trigger = bool(match and float(match["price"]) <= float(alert["target_price"]))
            previous_triggered = bool(alert.get("is_triggered"))

            if should_trigger and previous_triggered:
                last_triggered_at = alert.get("triggered_at")
                cooldown_elapsed = True
                if isinstance(last_triggered_at, datetime):
                    cooldown_elapsed = (now - last_triggered_at).total_seconds() >= ALERT_COOLDOWN_SECONDS
                if not cooldown_elapsed:
                    cursor.execute(
                        """
                        UPDATE price_alerts
                        SET last_checked_at = %s, updated_at = %s
                        WHERE alert_id = %s
                        """,
                        (now, now, alert["alert_id"]),
                    )
                    continue

            if should_trigger and match:
                matched_price = float(match["price"])
                message = (
                    f"Price alert hit for '{alert['query_text']}'. "
                    f"{match['name']} is now available at {matched_price:.2f} INR on {match['store_name']}."
                )
                delivery_channel = alert["notification_channel"]
                delivery_status = "delivered"
                if delivery_channel == "email":
                    delivery_status = _send_alert_email(
                        alert.get("contact_email"),
                        f"Price alert for {alert['query_text']}",
                        message + (f"\nOpen deal: {match['product_url']}" if match.get("product_url") else ""),
                    )
                cursor.execute(
                    """
                    INSERT INTO alert_notifications (
                        alert_id, user_id, message, matched_price, matched_product_name,
                        matched_store_name, matched_product_url, delivery_channel, delivery_status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING notification_id, alert_id, user_id, message, matched_price, matched_product_name,
                              matched_store_name, matched_product_url, delivery_channel, delivery_status,
                              is_read, created_at
                    """,
                    (
                        alert["alert_id"],
                        alert["user_id"],
                        message,
                        matched_price,
                        match.get("name"),
                        match.get("store_name"),
                        match.get("product_url"),
                        delivery_channel,
                        delivery_status,
                    ),
                )
                notifications.append(cursor.fetchone())
                cursor.execute(
                    """
                    UPDATE price_alerts
                    SET is_triggered = TRUE,
                        last_checked_at = %s,
                        triggered_at = %s,
                        last_triggered_price = %s,
                        updated_at = %s
                    WHERE alert_id = %s
                    """,
                    (now, now, matched_price, now, alert["alert_id"]),
                )
            else:
                cursor.execute(
                    """
                    UPDATE price_alerts
                    SET is_triggered = FALSE,
                        last_checked_at = %s,
                        updated_at = %s
                    WHERE alert_id = %s
                    """,
                    (now, now, alert["alert_id"]),
                )
    finally:
        cursor.close()
    return notifications


def _scrape_cache_key(query, limit):
    return (
        f"{(query or '').strip().lower()}::{int(limit)}::"
        f"ebay_official={int(ENABLE_EBAY_OFFICIAL)}::ebay_scraper={int(ENABLE_EBAY_SCRAPER)}::rel_v=2"
    )


def _read_scrape_cache(cache_key):
    cached = SCRAPE_CACHE.get(cache_key)
    if not cached:
        return None
    age_seconds = time.time() - cached.get("saved_at", 0.0)
    if age_seconds > SCRAPE_CACHE_SECONDS:
        SCRAPE_CACHE.pop(cache_key, None)
        return None
    return cached


def _write_scrape_cache(cache_key, rows, providers_used):
    SCRAPE_CACHE[cache_key] = {
        "saved_at": time.time(),
        "rows": [dict(item) for item in (rows or [])],
        "providers_used": list(providers_used or []),
    }


def _scrape_price_sources(query, limit=None):
    if limit is None:
        limit = SCRAPE_RESULT_LIMIT
    cache_key = _scrape_cache_key(query, limit)
    cached = _read_scrape_cache(cache_key)
    if cached:
        cached_rows = [dict(item) for item in cached.get("rows", [])]
        cached_providers = list(cached.get("providers_used", []))
        return cached_rows, cached_providers, True, []

    scraped = []
    providers_used = []
    tasks = []

    if ENABLE_EBAY_OFFICIAL:
        tasks.append({
            "provider": "ebay_official_api",
            "fn": search_ebay_products,
            "args": (query,),
            "kwargs": {"limit": limit},
        })
    tasks.append({"provider": "amazon_scraper", "fn": search_amazon_products, "args": (query,), "kwargs": {"limit": limit}})
    if ENABLE_EBAY_SCRAPER:
        tasks.append({"provider": "ebay_scraper", "fn": search_ebay_products_scrape, "args": (query,), "kwargs": {"limit": limit}})
    tasks.append({"provider": "walmart_scraper", "fn": search_walmart_products, "args": (query,), "kwargs": {"limit": limit}})

    results, health = _run_scrape_tasks(tasks)
    for result in results:
        scraped.extend(result.get("rows") or [])
        providers_used.append(result["provider"])

    deduped = _dedupe_scraped_products(scraped)
    relevant_rows = [item for item in deduped if _is_relevant_result(item, query)]
    if len(relevant_rows) < limit:
        fallback_tasks = [
            {"provider": "dummyjson_api", "fn": search_dummyjson_products, "args": (query,), "kwargs": {"limit": limit}},
            {"provider": "platzi_api", "fn": search_platzi_products, "args": (query,), "kwargs": {"limit": limit}},
        ]
        fallback_results, fallback_health = _run_scrape_tasks(fallback_tasks)
        health.extend(fallback_health)
        for result in fallback_results:
            scraped.extend(result.get("rows") or [])
            providers_used.append(result["provider"])
        deduped = _dedupe_scraped_products(scraped)
        relevant_rows = [item for item in deduped if _is_relevant_result(item, query)]
    if len(relevant_rows) < limit:
        seen_keys = set()
        for item in relevant_rows:
            seen_keys.add(item.get("url") or item.get("product_url") or f"{item.get('store')}::{item.get('name')}::{item.get('price')}")
        for item in deduped:
            if len(relevant_rows) >= limit:
                break
            key = item.get("url") or item.get("product_url") or f"{item.get('store')}::{item.get('name')}::{item.get('price')}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            relevant_rows.append(item)
    _write_scrape_cache(cache_key, relevant_rows, providers_used)
    return relevant_rows, providers_used, False, health


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(_err):
    return jsonify({"status": "error", "error": "File too large. Max size is 10MB."}), 413


@app.before_request
def enforce_https():
    if not FORCE_HTTPS:
        return None
    if request.is_secure:
        return None
    if TRUST_PROXY_HEADERS:
        forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
        if forwarded_proto == "https":
            return None
    return jsonify({"status": "error", "error": "HTTPS is required for this API."}), 426


@app.before_request
def enforce_api_rate_limit():
    g.request_started_at = time.perf_counter()
    if not request.path.startswith("/api/"):
        return None

    allowed, remaining, retry_after = _consume_rate_limit_bucket(_rate_limit_key())
    if allowed:
        return None

    response = jsonify({
        "status": "error",
        "error": "Rate limit exceeded. Please retry later.",
        "retry_after_seconds": retry_after,
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    response.headers["X-RateLimit-Limit"] = str(API_RATE_LIMIT)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Window"] = str(API_RATE_LIMIT_WINDOW_SECONDS)
    return response


@app.after_request
def add_response_timing_headers(response):
    started_at = getattr(g, "request_started_at", None)
    if started_at is None:
        return response
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    response.headers["X-Response-Time-ms"] = str(elapsed_ms)
    existing_server_timing = response.headers.get("Server-Timing")
    timing_value = f"app;dur={elapsed_ms}"
    response.headers["Server-Timing"] = (
        f"{existing_server_timing}, {timing_value}" if existing_server_timing else timing_value
    )
    if request.path.startswith("/api/") and elapsed_ms >= SLOW_REQUEST_MS:
        print(f"SLOW REQUEST {elapsed_ms}ms {request.method} {request.path}")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if request.is_secure or (
        TRUST_PROXY_HEADERS
        and (request.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower() == "https"
    ):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.route("/")
def home():
    return "Backend Running"


@app.route("/api/docs/openapi.yaml", methods=["GET"])
def openapi_spec():
    return send_from_directory("docs", "openapi.yaml")


@app.route("/api/docs", methods=["GET"])
def swagger_ui():
    return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Price Intelligence API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
    <style>
      body { margin: 0; background: #f5f7fb; }
      #swagger-ui { max-width: 1200px; margin: 0 auto; }
    </style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.ui = SwaggerUIBundle({
        url: "/api/docs/openapi.yaml",
        dom_id: "#swagger-ui",
        deepLinking: true
      });
    </script>
  </body>
</html>
"""


@app.route("/api/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/api/my-images", methods=["GET"])
@auth_required
def my_images():
    user_id = g.user_id
    page, per_page, page_err = _parse_page_per_page(default_per_page=20, max_per_page=50)
    if page_err:
        return jsonify({"status": "error", "error": page_err}), 400
    offset = (page - 1) * per_page

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS total_items
            FROM uploads
            WHERE user_id = %s
            """,
            (user_id,),
        )
        total_items = int((cursor.fetchone() or {}).get("total_items") or 0)
        cursor.execute(
            """
            SELECT image_id, filename, predictions_json, uploaded_at
            FROM uploads
            WHERE user_id = %s
            ORDER BY uploaded_at DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, per_page, offset),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    images = []
    for row in rows:
        asset_urls = _build_upload_asset_urls(row["filename"])
        images.append({
            "image_id": row["image_id"],
            "filename": row["filename"],
            "image_url": asset_urls["image_url"],
            "thumbnail_url": asset_urls["thumbnail_url"],
            "predictions": json.loads(row["predictions_json"]),
            "uploaded_at": row["uploaded_at"],
        })

    total_pages = (total_items + per_page - 1) // per_page if total_items else 0
    return jsonify(_convert_datetimes_to_ist({
        "status": "success",
        "count": len(images),
        "images": images,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1 and total_pages > 0,
        },
    })), 200


@app.route("/api/my-images/<image_id>", methods=["DELETE"])
@auth_required
def delete_my_image(image_id):
    user_id = g.user_id

    normalized_image_id = (image_id or "").strip()
    if not normalized_image_id:
        return jsonify({"status": "error", "error": "image_id is required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM uploads
            WHERE user_id = %s AND image_id = %s
            RETURNING filename
            """,
            (user_id, normalized_image_id),
        )
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({"status": "error", "error": "Image not found"}), 404

        filename = deleted.get("filename")
        if filename:
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM uploads
                WHERE filename = %s
                """,
                (filename,),
            )
            remaining = cursor.fetchone() or {}
            if int(remaining.get("count") or 0) == 0:
                for candidate_name in (filename, _build_thumbnail_filename(filename)):
                    if not candidate_name:
                        continue
                    filepath = os.path.join(UPLOAD_FOLDER, candidate_name)
                    try:
                        if os.path.isfile(filepath):
                            os.remove(filepath)
                    except Exception:
                        pass

        conn.commit()
        return jsonify({
            "status": "success",
            "deleted_image_id": normalized_image_id,
        }), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/upload-image", methods=["POST"])
@auth_required
def upload_image():
    user_id = g.user_id

    if "image" not in request.files:
        return jsonify({"status": "error", "error": "No file provided"}), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({"status": "error", "error": "Empty filename"}), 400

    if not allowed_image_file(file):
        return jsonify({
            "status": "error",
            "error": "Invalid file format. Only JPEG, PNG, and WebP are allowed."
        }), 415
    valid_content, content_error = _validate_image_stream(file)
    if not valid_content:
        return jsonify({
            "status": "error",
            "error": content_error or "Invalid image content."
        }), 415

    image_hash = _compute_upload_sha256(file)
    cached_upload_result = None
    if image_hash:
        cached_upload_result = _cache_get(
            "upload_analysis",
            {"image_hash": image_hash, "target_size": TARGET_SIZE, "tta": True},
        )

    try:
        image_id = str(uuid.uuid4())
        _, original_ext = os.path.splitext(file.filename.lower())
        filename = f"{image_id}{original_ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        _ensure_upload_thumbnail(filepath, filename)
    except Exception:
        return jsonify({"status": "error", "error": "Failed to save uploaded image"}), 500

    scan_ok, scan_error = _scan_for_malware(filepath)
    if not scan_ok:
        try:
            os.remove(filepath)
        except Exception:
            pass
        try:
            thumb_name = _build_thumbnail_filename(filename)
            if thumb_name:
                thumb_path = os.path.join(UPLOAD_FOLDER, thumb_name)
                if os.path.isfile(thumb_path):
                    os.remove(thumb_path)
        except Exception:
            pass
        return jsonify({"status": "error", "error": scan_error or "Upload blocked"}), 400

    if cached_upload_result and cached_upload_result.get("predictions"):
        results = cached_upload_result["predictions"]
    else:
        try:
            model_input = preprocess_for_efficientnet(filepath, target_size=TARGET_SIZE, use_tta=True)
            model = _get_model()
            batch_predictions = model.predict(model_input, verbose=0)
            predictions = batch_predictions.mean(axis=0, keepdims=True)
            decoded = decode_predictions(predictions, top=3)
            results = [
                {"label": item[1], "confidence": float(item[2])}
                for item in decoded[0]
            ]
            if image_hash:
                _cache_set(
                    "upload_analysis",
                    {"image_hash": image_hash, "target_size": TARGET_SIZE, "tta": True},
                    {"predictions": results},
                    UPLOAD_RESULT_CACHE_SECONDS,
                )
        except Exception:
            return jsonify({"status": "error", "error": "Failed to process image"}), 500

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO uploads (image_id, user_id, filename, predictions_json)
            VALUES (%s, %s, %s, %s)
            """,
            (image_id, user_id, filename, json.dumps(results)),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        return jsonify({"status": "error", "error": "Failed to save upload metadata"}), 500

    asset_urls = _build_upload_asset_urls(filename)

    return jsonify({
        "status": "success",
        "image_id": image_id,
        "image_url": asset_urls["image_url"],
        "thumbnail_url": asset_urls["thumbnail_url"],
        "predictions": results
    }), 201


@app.route("/api/compare-prices", methods=["GET"])
def compare_prices_api():
    query = _sanitize_query_param(request.args.get("product"), max_len=255)
    if not query:
        return jsonify({
            "status": "error",
            "error": "Missing required query param: product"
        }), 400

    page, per_page, page_err = _parse_page_per_page(default_per_page=20, max_per_page=50)
    if page_err:
        return jsonify({"status": "error", "error": page_err}), 400

    filters, filters_error = _build_comparison_filters()
    if filters_error:
        return jsonify({"status": "error", "error": filters_error}), 400

    cache_key = {
        "query": query.lower(),
        "page": page,
        "per_page": per_page,
        "filters": filters or {},
        "scrape_cache_seconds": SCRAPE_CACHE_SECONDS,
    }
    cached_summary = _cache_get("compare_prices", cache_key)
    if cached_summary:
        user_id = get_user_id_from_request()
        if user_id:
            _save_search_history(user_id, query)
        persisted_rows = _persist_search_products(cached_summary.get("all_results") or [])
        response_payload = dict(cached_summary)
        response_payload["stored_rows"] = max(int(response_payload.get("stored_rows") or 0), persisted_rows)
        response_payload["response_cache_hit"] = True
        return jsonify(response_payload), 200

    user_id = get_user_id_from_request()
    if user_id:
        _save_search_history(user_id, query)

    scraped_results, providers_used, cache_hit, providers_health = _scrape_price_sources(query, limit=SCRAPE_RESULT_LIMIT)
    source_mode = "scrapers_only"
    if not scraped_results:
        scraped_results = search_ebay_products_mock(query)
        providers_used = ["ebay_mock"]
        source_mode = "fallback_mock"
        cache_hit = False
        providers_health = providers_health or []

    scraped_results = _convert_results_to_inr(scraped_results)
    summary = compare_prices(scraped_results, filters=filters)
    persisted_rows = _persist_search_products(scraped_results)
    all_results = summary.get("all_results", [])
    paged_results, pagination = _paginate_rows(all_results, page, per_page)
    summary["all_results"] = paged_results
    summary["pagination"] = pagination
    summary["query"] = query
    summary["source_mode"] = source_mode
    summary["providers_used"] = providers_used
    summary["providers_health"] = providers_health
    summary["cache_hit"] = cache_hit
    summary["cache_ttl_seconds"] = SCRAPE_CACHE_SECONDS
    summary["result_count"] = pagination["total_items"]
    summary["page_result_count"] = len(paged_results)
    summary["stored_rows"] = persisted_rows
    summary["response_cache_hit"] = False
    if persisted_rows:
        conn = get_db()
        try:
            _evaluate_price_alerts(conn)
            conn.commit()
        finally:
            conn.close()
    _cache_set("compare_prices", cache_key, summary, API_RESPONSE_CACHE_SECONDS)
    return jsonify(summary), 200


@app.route("/api/search-products", methods=["GET"])
@auth_required
def search_products_api():
    user_id = g.user_id

    product = _sanitize_query_param(request.args.get("product"), max_len=255)
    identifier = _sanitize_query_param(request.args.get("identifier"), max_len=120)
    image_id = _sanitize_query_param(request.args.get("image_id"), max_len=120)
    try:
        limit = min(max(int(request.args.get("limit", 5)), 1), 10)
    except ValueError:
        limit = 5
    try:
        max_terms = min(max(int(request.args.get("max_terms", 2)), 1), 4)
    except ValueError:
        max_terms = 2
    filters, filters_error = _build_comparison_filters()
    if filters_error:
        return jsonify({"status": "error", "error": filters_error}), 400

    response_cache_key = {
        "user_id": user_id,
        "product": product.lower(),
        "identifier": identifier.lower(),
        "image_id": image_id,
        "limit": limit,
        "max_terms": max_terms,
        "filters": filters or {},
    }
    cached_payload = _cache_get("search_products", response_cache_key)
    if cached_payload:
        _save_search_history(user_id, _canonical_search_query((cached_payload.get("search_terms") or [None])[0]))
        persisted_rows = _persist_search_products(cached_payload.get("products") or [])
        response_payload = dict(cached_payload)
        response_payload["stored_rows"] = max(int(response_payload.get("stored_rows") or 0), persisted_rows)
        response_payload["response_cache_hit"] = True
        return jsonify(response_payload), 200

    predictions = _get_predictions_from_upload(user_id, image_id=image_id if image_id else None)
    terms = _build_search_terms(product, identifier, predictions, max_terms=max_terms)
    if not terms:
        return jsonify({
            "status": "error",
            "error": "Provide product/identifier or upload an image first for recognition-based search.",
        }), 400

    all_results = []
    providers_used = []
    tasks = []

    for term in terms:
        if ENABLE_EBAY_OFFICIAL:
            tasks.append({"provider": "ebay_official_api", "fn": search_ebay_products, "args": (term,)})
        tasks.append({"provider": "platzi_api", "fn": search_platzi_products, "args": (term,)})
        tasks.append({"provider": "amazon_scraper", "fn": search_amazon_products, "args": (term,), "kwargs": {"limit": limit}})
        if ENABLE_EBAY_SCRAPER:
            tasks.append({"provider": "ebay_scraper", "fn": search_ebay_products_scrape, "args": (term,), "kwargs": {"limit": limit}})
        tasks.append({"provider": "walmart_scraper", "fn": search_walmart_products, "args": (term,), "kwargs": {"limit": limit}})

    results, health = _run_scrape_tasks(tasks)
    for result in results:
        all_results.extend(result.get("rows") or [])
        providers_used.append(result["provider"])

    if not all_results:
        for term in terms:
            fallback_rows = search_dummyjson_products(term)
            if not fallback_rows:
                continue
            all_results.extend(fallback_rows)
            providers_used.append("dummyjson_api")
        if all_results:
            providers_used = sorted(set(providers_used))

    deduped = []
    seen_keys = set()
    for item in all_results:
        key = (
            (item.get("store") or item.get("store_name") or "").strip().lower(),
            (item.get("name") or item.get("title") or "").strip().lower(),
            (item.get("url") or item.get("product_url") or "").strip(),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)
    all_results = deduped
    providers_used = sorted(set(providers_used))
    all_results = _convert_results_to_inr(all_results)

    _save_search_history(user_id, _canonical_search_query(terms[0]))
    persisted_rows = _persist_search_products(all_results)
    summary = compare_prices(all_results, filters=filters)
    payload = {
        "status": "success",
        "search_terms": terms,
        "providers_used": providers_used,
        "providers_health": health,
        "result_count": len(all_results),
        "stored_rows": persisted_rows,
        "summary": summary,
        "products": all_results,
        "response_cache_hit": False,
    }
    _cache_set("search_products", response_cache_key, payload, API_RESPONSE_CACHE_SECONDS)
    return jsonify(payload), 200


@app.route("/api/price-alerts", methods=["GET"])
@auth_required
def list_price_alerts():
    user_id = g.user_id

    include_inactive = str(request.args.get("include_inactive") or "").strip().lower() in {"1", "true", "yes"}
    page, per_page, page_err = _parse_page_per_page(default_per_page=20, max_per_page=50)
    if page_err:
        return jsonify({"status": "error", "error": page_err}), 400
    offset = (page - 1) * per_page
    conn = get_db()
    cursor = conn.cursor()
    try:
        clauses = ["user_id = %s"]
        params = [user_id]
        if not include_inactive:
            clauses.append("is_active = TRUE")
        where_sql = f"WHERE {' AND '.join(clauses)}"
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total_items
            FROM price_alerts
            {where_sql}
            """,
            tuple(params),
        )
        total_items = int((cursor.fetchone() or {}).get("total_items") or 0)
        sql = f"""
            SELECT alert_id, user_id, query_text, target_price, notification_channel, contact_email,
                   is_active, is_triggered, last_checked_at, triggered_at, last_triggered_price,
                   created_at, updated_at
            FROM price_alerts
            {where_sql}
            ORDER BY created_at DESC, alert_id DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(sql, tuple(params + [per_page, offset]))
        rows = cursor.fetchall()
        total_pages = (total_items + per_page - 1) // per_page if total_items else 0
        return jsonify({
            "status": "success",
            "count": len(rows),
            "alerts": [_serialize_price_alert(row) for row in rows],
            "email_enabled": bool(SMTP_HOST and SMTP_FROM_EMAIL),
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1 and total_pages > 0,
            },
        }), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/price-alerts", methods=["POST"])
@auth_required
def create_price_alert():
    user_id = g.user_id

    data = request.get_json(silent=True) or {}
    query_text, err = _validate_non_empty_text(
        data.get("query_text") or data.get("product_query") or data.get("product"),
        "query_text",
        max_len=255,
    )
    if err:
        return jsonify({"status": "error", "error": err}), 400

    target_price, err = _validate_non_negative_price(data.get("target_price"))
    if err:
        return jsonify({"status": "error", "error": "target_price must be a number >= 0"}), 400

    notification_channel = _normalize_notification_channel(data.get("notification_channel"))
    if not notification_channel:
        return jsonify({"status": "error", "error": "notification_channel must be one of: in_app, email"}), 400

    contact_email, err = _validate_optional_email(data.get("contact_email"))
    if err:
        return jsonify({"status": "error", "error": err}), 400
    if notification_channel == "email" and not contact_email:
        return jsonify({"status": "error", "error": "contact_email is required when notification_channel is email"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO price_alerts (user_id, query_text, target_price, notification_channel, contact_email)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING alert_id, user_id, query_text, target_price, notification_channel, contact_email,
                      is_active, is_triggered, last_checked_at, triggered_at, last_triggered_price,
                      created_at, updated_at
            """,
            (user_id, query_text, target_price, notification_channel, contact_email),
        )
        alert_row = cursor.fetchone()
        alert_id = alert_row["alert_id"]
        notifications = _evaluate_price_alerts(conn, alert_ids=[alert_id])
        cursor.execute(
            """
            SELECT alert_id, user_id, query_text, target_price, notification_channel, contact_email,
                   is_active, is_triggered, last_checked_at, triggered_at, last_triggered_price,
                   created_at, updated_at
            FROM price_alerts
            WHERE alert_id = %s
            """,
            (alert_id,),
        )
        alert_row = cursor.fetchone()
        conn.commit()
        _bump_cache_version(_user_cache_scope(user_id))
        return jsonify({
            "status": "success",
            "alert": _serialize_price_alert(alert_row),
            "notifications_created": len(notifications),
            "notifications": [_serialize_notification(row) for row in notifications],
            "email_enabled": bool(SMTP_HOST and SMTP_FROM_EMAIL),
        }), 201
    finally:
        cursor.close()
        conn.close()


@app.route("/api/price-alerts/<int:alert_id>", methods=["PUT"])
@auth_required
def update_price_alert(alert_id):
    user_id = g.user_id

    data = request.get_json(silent=True) or {}
    updates = []
    params = []

    if "query_text" in data or "product_query" in data or "product" in data:
        query_text, err = _validate_non_empty_text(
            data.get("query_text") or data.get("product_query") or data.get("product"),
            "query_text",
            max_len=255,
        )
        if err:
            return jsonify({"status": "error", "error": err}), 400
        updates.append("query_text = %s")
        params.append(query_text)

    if "target_price" in data:
        target_price, err = _validate_non_negative_price(data.get("target_price"))
        if err:
            return jsonify({"status": "error", "error": "target_price must be a number >= 0"}), 400
        updates.append("target_price = %s")
        params.append(target_price)

    if "notification_channel" in data:
        channel = _normalize_notification_channel(data.get("notification_channel"))
        if not channel:
            return jsonify({"status": "error", "error": "notification_channel must be one of: in_app, email"}), 400
        updates.append("notification_channel = %s")
        params.append(channel)

    if "contact_email" in data:
        contact_email, err = _validate_optional_email(data.get("contact_email"))
        if err:
            return jsonify({"status": "error", "error": err}), 400
        updates.append("contact_email = %s")
        params.append(contact_email)

    if "is_active" in data:
        if not isinstance(data.get("is_active"), bool):
            return jsonify({"status": "error", "error": "is_active must be boolean"}), 400
        updates.append("is_active = %s")
        params.append(data.get("is_active"))

    if not updates:
        return jsonify({"status": "error", "error": "No valid fields provided to update"}), 400

    updates.extend(["is_triggered = FALSE", "updated_at = %s"])
    params.append(datetime.utcnow())
    params.extend([alert_id, user_id])

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            UPDATE price_alerts
            SET {", ".join(updates)}
            WHERE alert_id = %s AND user_id = %s
            RETURNING alert_id, user_id, query_text, target_price, notification_channel, contact_email,
                      is_active, is_triggered, last_checked_at, triggered_at, last_triggered_price,
                      created_at, updated_at
            """,
            tuple(params),
        )
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return jsonify({"status": "error", "error": "Price alert not found"}), 404
        notifications = _evaluate_price_alerts(conn, alert_ids=[alert_id]) if row["is_active"] else []
        cursor.execute(
            """
            SELECT alert_id, user_id, query_text, target_price, notification_channel, contact_email,
                   is_active, is_triggered, last_checked_at, triggered_at, last_triggered_price,
                   created_at, updated_at
            FROM price_alerts
            WHERE alert_id = %s
            """,
            (alert_id,),
        )
        row = cursor.fetchone()
        conn.commit()
        _bump_cache_version(_user_cache_scope(user_id))
        return jsonify({
            "status": "success",
            "alert": _serialize_price_alert(row),
            "notifications_created": len(notifications),
            "notifications": [_serialize_notification(item) for item in notifications],
        }), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/price-alerts/<int:alert_id>", methods=["DELETE"])
@auth_required
def delete_price_alert(alert_id):
    user_id = g.user_id

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM price_alerts
            WHERE alert_id = %s AND user_id = %s
            RETURNING alert_id
            """,
            (alert_id, user_id),
        )
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({"status": "error", "error": "Price alert not found"}), 404
        conn.commit()
        _bump_cache_version(_user_cache_scope(user_id))
        return jsonify({"status": "success", "deleted_alert_id": deleted["alert_id"]}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/alert-notifications", methods=["GET"])
@auth_required
def list_alert_notifications():
    user_id = g.user_id

    unread_only = str(request.args.get("unread_only") or "").strip().lower() in {"1", "true", "yes"}
    limit, offset = _parse_limit_offset()
    conn = get_db()
    cursor = conn.cursor()
    try:
        sql = """
            SELECT notification_id, alert_id, user_id, message, matched_price, matched_product_name,
                   matched_store_name, matched_product_url, delivery_channel, delivery_status,
                   is_read, created_at
            FROM alert_notifications
            WHERE user_id = %s
        """
        params = [user_id]
        if unread_only:
            sql += " AND is_read = FALSE"
        sql += " ORDER BY created_at DESC, notification_id DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        return jsonify({
            "status": "success",
            "count": len(rows),
            "notifications": [_serialize_notification(row) for row in rows],
        }), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/alert-notifications/<int:notification_id>/read", methods=["PUT"])
@auth_required
def mark_alert_notification_read(notification_id):
    user_id = g.user_id

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE alert_notifications
            SET is_read = TRUE
            WHERE notification_id = %s AND user_id = %s
            RETURNING notification_id, alert_id, user_id, message, matched_price, matched_product_name,
                      matched_store_name, matched_product_url, delivery_channel, delivery_status,
                      is_read, created_at
            """,
            (notification_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return jsonify({"status": "error", "error": "Alert notification not found"}), 404
        conn.commit()
        return jsonify({"status": "success", "notification": _serialize_notification(row)}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/me/search-history", methods=["GET"])
@auth_required
def my_search_history():
    user_id = g.user_id

    limit, offset = _parse_limit_offset()
    query_filter = _sanitize_query_param(request.args.get("query"), max_len=255)
    sql = """
        SELECT search_id, user_id, query, timestamp
        FROM search_history
        WHERE user_id = %s
    """
    params = [user_id]
    if query_filter:
        sql += " AND query ILIKE %s"
        params.append(f"%{query_filter}%")
    sql += " ORDER BY timestamp DESC, search_id DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        normalized_rows = []
        for row in rows:
            item = dict(row)
            item["query"] = _canonical_search_query(item.get("query"))
            normalized_rows.append(item)
        return jsonify(_convert_datetimes_to_ist({
            "status": "success",
            "count": len(normalized_rows),
            "search_history": normalized_rows,
        })), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/credentials", methods=["GET"])
@auth_required
def list_credentials():
    user_id = g.user_id
    include_secret = str(request.args.get("include_secret") or "").strip().lower() in {"1", "true", "yes"}
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT credential_id, provider, label, encrypted_value, created_at, updated_at
            FROM third_party_credentials
            WHERE user_id = %s
            ORDER BY updated_at DESC, credential_id DESC
            """,
            (user_id,),
        )
        rows = []
        for row in cursor.fetchall():
            secret_value = _decrypt_secret(row.get("encrypted_value")) if include_secret else None
            rows.append({
                "credential_id": row["credential_id"],
                "provider": row["provider"],
                "label": row["label"],
                "masked_value": _mask_secret(secret_value) if include_secret else None,
                "secret_value": secret_value if include_secret else None,
                "created_at": _convert_datetimes_to_ist(row.get("created_at")),
                "updated_at": _convert_datetimes_to_ist(row.get("updated_at")),
            })
        return jsonify({"status": "success", "count": len(rows), "credentials": rows}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/credentials", methods=["POST"])
@auth_required
def upsert_credential():
    user_id = g.user_id
    payload = request.get_json(silent=True) or {}
    provider, err = _validate_non_empty_text(payload.get("provider"), "provider", max_len=120)
    if err:
        return jsonify({"status": "error", "error": err}), 400
    label, err = _validate_non_empty_text(payload.get("label") or "default", "label", max_len=120)
    if err:
        return jsonify({"status": "error", "error": err}), 400
    secret_value, err = _validate_non_empty_text(payload.get("api_key"), "api_key", max_len=2048)
    if err:
        return jsonify({"status": "error", "error": err}), 400
    encrypted = _encrypt_secret(secret_value)
    if not encrypted:
        return jsonify({"status": "error", "error": "Encryption key is not configured"}), 500

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO third_party_credentials (user_id, provider, label, encrypted_value)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, provider, label)
            DO UPDATE SET
                encrypted_value = EXCLUDED.encrypted_value,
                updated_at = CURRENT_TIMESTAMP
            RETURNING credential_id, provider, label, created_at, updated_at
            """,
            (user_id, provider, label, encrypted),
        )
        row = cursor.fetchone()
        conn.commit()
        return jsonify({
            "status": "success",
            "credential": {
                "credential_id": row["credential_id"],
                "provider": row["provider"],
                "label": row["label"],
                "masked_value": _mask_secret(secret_value),
                "created_at": _convert_datetimes_to_ist(row.get("created_at")),
                "updated_at": _convert_datetimes_to_ist(row.get("updated_at")),
            },
        }), 201
    finally:
        cursor.close()
        conn.close()


@app.route("/api/credentials/<int:credential_id>", methods=["DELETE"])
@auth_required
def delete_credential(credential_id):
    user_id = g.user_id
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM third_party_credentials
            WHERE credential_id = %s AND user_id = %s
            RETURNING credential_id
            """,
            (credential_id, user_id),
        )
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({"status": "error", "error": "Credential not found"}), 404
        conn.commit()
        return jsonify({"status": "success", "deleted_credential_id": deleted["credential_id"]}), 200
    finally:
        cursor.close()
        conn.close()
    params = [user_id]
    if query_filter:
        sql += " AND query ILIKE %s"
        params.append(f"%{query_filter}%")
    sql += " ORDER BY timestamp DESC, search_id DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        normalized_rows = []
        for row in rows:
            item = dict(row)
            item["query"] = _canonical_search_query(item.get("query"))
            normalized_rows.append(item)
        return jsonify(_convert_datetimes_to_ist({
            "status": "success",
            "count": len(normalized_rows),
            "search_history": normalized_rows,
        })), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/me/search-history/<int:search_id>", methods=["DELETE"])
@auth_required
def delete_my_search_history(search_id):
    user_id = g.user_id

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM search_history
            WHERE search_id = %s AND user_id = %s
            RETURNING search_id
            """,
            (search_id, user_id),
        )
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({"status": "error", "error": "Search history entry not found"}), 404
        conn.commit()
        _bump_cache_version(_user_cache_scope(user_id))
        _bump_cache_version("popular_searches")
        return jsonify({"status": "success", "deleted_search_id": deleted["search_id"]}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/recommendations", methods=["GET"])
@auth_required
def list_recommendations():
    user_id = g.user_id

    limit, _ = _parse_limit_offset()
    limit = min(limit, 12)
    user_cache_version = _get_cache_version(_user_cache_scope(user_id))
    cache_key = {"user_id": user_id, "limit": limit, "version": user_cache_version}
    cached = _cache_get("recommendations", cache_key)
    if cached:
        cached["response_cache_hit"] = True
        return jsonify(cached), 200
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT query
            FROM search_history
            WHERE user_id = %s
            ORDER BY timestamp DESC, search_id DESC
            LIMIT 12
            """,
            (user_id,),
        )
        recent_queries = [
            _canonical_search_query(row.get("query"))
            for row in cursor.fetchall()
            if _canonical_search_query(row.get("query"))
        ]

        cursor.execute(
            """
            SELECT product_name
            FROM wishlist_items
            WHERE user_id = %s
            ORDER BY created_at DESC, wishlist_id DESC
            LIMIT 12
            """,
            (user_id,),
        )
        wishlist_names = []
        for row in cursor.fetchall():
            wishlist_names.extend(_query_tokens(row.get("product_name")))

        if not recent_queries and not wishlist_names:
            payload = {"status": "success", "count": 0, "recommendations": [], "response_cache_hit": False}
            _cache_set("recommendations", cache_key, payload, USER_DASHBOARD_CACHE_SECONDS)
            return jsonify(payload), 200

        cursor.execute(
            """
            SELECT
                p.product_id,
                p.name,
                p.category,
                p.image_url,
                COUNT(pr.price_id) AS price_count,
                MIN(pr.price) AS lowest_price,
                MAX(pr.price) AS highest_price,
                AVG(pr.price) AS average_price,
                MAX(pr.timestamp) AS last_seen_at,
                MIN(pr.product_url) AS product_url
            FROM products p
            LEFT JOIN prices pr ON pr.product_id = p.product_id
            GROUP BY p.product_id, p.name, p.category, p.image_url
            ORDER BY MAX(pr.timestamp) DESC NULLS LAST, p.product_id DESC
            LIMIT 300
            """
        )
        candidates = []
        for row in cursor.fetchall():
            score, matched_terms = _recommendation_score(row, recent_queries, wishlist_names)
            if score <= 0:
                continue
            candidate = dict(row)
            candidate["score"] = score
            candidate["matched_terms"] = matched_terms
            candidate["average_price"] = round(float(row["average_price"]), 2) if row.get("average_price") is not None else None
            candidate["lowest_price"] = round(float(row["lowest_price"]), 2) if row.get("lowest_price") is not None else None
            candidate["highest_price"] = round(float(row["highest_price"]), 2) if row.get("highest_price") is not None else None
            candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                -int(item["score"]),
                float(item["lowest_price"]) if item.get("lowest_price") is not None else float("inf"),
                str(item.get("name") or "").lower(),
            )
        )
        deduped_candidates = []
        seen_recommendations = set()
        for item in candidates:
            identity = (
                str(item.get("name") or "").strip().lower(),
                str(item.get("product_url") or "").strip().lower(),
            )
            if identity in seen_recommendations:
                continue
            seen_recommendations.add(identity)
            deduped_candidates.append(item)
            if len(deduped_candidates) >= limit:
                break

        trimmed = deduped_candidates
        payload = _convert_datetimes_to_ist({
            "status": "success",
            "count": len(trimmed),
            "recommendations": trimmed,
            "based_on_queries": recent_queries[:5],
            "response_cache_hit": False,
        })
        _cache_set("recommendations", cache_key, payload, USER_DASHBOARD_CACHE_SECONDS)
        return jsonify(payload), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/dashboard-summary", methods=["GET"])
@auth_required
def dashboard_summary():
    user_id = g.user_id
    user_cache_version = _get_cache_version(_user_cache_scope(user_id))
    cache_key = {"user_id": user_id, "version": user_cache_version}
    cached = _cache_get("dashboard_summary", cache_key)
    if cached:
        cached["response_cache_hit"] = True
        return jsonify(cached), 200
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM uploads WHERE user_id = %s", (user_id,))
        upload_total = int((cursor.fetchone() or {}).get("total") or 0)

        cursor.execute("SELECT COUNT(*) AS total FROM wishlist_items WHERE user_id = %s", (user_id,))
        wishlist_total = int((cursor.fetchone() or {}).get("total") or 0)

        cursor.execute(
            "SELECT COUNT(*) AS total FROM price_alerts WHERE user_id = %s AND is_active = TRUE",
            (user_id,),
        )
        active_alerts = int((cursor.fetchone() or {}).get("total") or 0)

        cursor.execute(
            """
            SELECT search_id, user_id, query, timestamp
            FROM search_history
            WHERE user_id = %s
            ORDER BY timestamp DESC, search_id DESC
            LIMIT 5
            """,
            (user_id,),
        )
        recent_searches = cursor.fetchall()

        cursor.execute(
            """
            SELECT wishlist_id, user_id, product_name, category, store_name, current_price,
                   product_url, image_url, source_query, created_at
            FROM wishlist_items
            WHERE user_id = %s
            ORDER BY created_at DESC, wishlist_id DESC
            LIMIT 6
            """,
            (user_id,),
        )
        saved_products = cursor.fetchall()

        cursor.execute(
            """
            SELECT alert_id, user_id, query_text, target_price, notification_channel, contact_email,
                   is_active, is_triggered, last_checked_at, triggered_at, last_triggered_price,
                   created_at, updated_at
            FROM price_alerts
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY created_at DESC, alert_id DESC
            LIMIT 6
            """,
            (user_id,),
        )
        alerts = cursor.fetchall()
        payload = _convert_datetimes_to_ist({
            "status": "success",
            "metrics": {
                "total_uploads": upload_total,
                "saved_products": wishlist_total,
                "active_alerts": active_alerts,
                "recent_searches": len(recent_searches),
            },
            "saved_products": saved_products,
            "active_price_alerts": alerts,
            "recent_searches": recent_searches,
            "response_cache_hit": False,
        })
        _cache_set("dashboard_summary", cache_key, payload, USER_DASHBOARD_CACHE_SECONDS)
        return jsonify(payload), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/popular-searches", methods=["GET"])
def popular_searches():
    limit, _ = _parse_limit_offset()
    limit = min(limit, 12)
    version = _get_cache_version("popular_searches")
    cache_key = {"limit": limit, "version": version}
    cached = _cache_get("popular_searches", cache_key)
    if cached:
        cached["response_cache_hit"] = True
        return jsonify(cached), 200

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT query, COUNT(*) AS search_count, MAX(timestamp) AS last_seen_at
            FROM search_history
            GROUP BY query
            ORDER BY COUNT(*) DESC, MAX(timestamp) DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        payload = _convert_datetimes_to_ist({
            "status": "success",
            "count": len(rows),
            "popular_searches": rows,
            "response_cache_hit": False,
        })
        _cache_set("popular_searches", cache_key, payload, POPULAR_SEARCH_CACHE_SECONDS)
        return jsonify(payload), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/query-analysis", methods=["GET"])
@auth_required
def query_analysis():
    conn = get_db()
    cursor = conn.cursor()
    try:
        analysis = {
            "dashboard_summary_recent_searches": _explain_query(
                cursor,
                """
                SELECT search_id, user_id, query, timestamp
                FROM search_history
                WHERE user_id = %s
                ORDER BY timestamp DESC, search_id DESC
                LIMIT 5
                """,
                (g.user_id,),
            ),
            "dashboard_summary_saved_products": _explain_query(
                cursor,
                """
                SELECT wishlist_id, user_id, product_name, created_at
                FROM wishlist_items
                WHERE user_id = %s
                ORDER BY created_at DESC, wishlist_id DESC
                LIMIT 6
                """,
                (g.user_id,),
            ),
            "price_history_lookup": _explain_query(
                cursor,
                """
                SELECT price_id, product_id, store_name, price, timestamp, product_url
                FROM prices
                WHERE product_id = %s
                ORDER BY timestamp DESC, price_id DESC
                LIMIT %s OFFSET %s
                """,
                (1, 20, 0),
            ),
        }
        return jsonify({"status": "success", "analysis": analysis}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/account/export", methods=["GET"])
@auth_required
def export_account_data():
    user_id = g.user_id
    include_credentials = str(request.args.get("include_credentials") or "").strip().lower() in {"1", "true", "yes"}
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, username, email, phone, postal_code, created_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        user_row = cursor.fetchone()
        if not user_row:
            return jsonify({"status": "error", "error": "User not found"}), 404

        cursor.execute(
            """
            SELECT image_id, filename, predictions_json, uploaded_at
            FROM uploads
            WHERE user_id = %s
            ORDER BY uploaded_at DESC, id DESC
            """,
            (user_id,),
        )
        uploads = []
        for row in cursor.fetchall():
            asset_urls = _build_upload_asset_urls(row.get("filename"))
            uploads.append({
                "image_id": row.get("image_id"),
                "filename": row.get("filename"),
                "image_url": asset_urls.get("image_url"),
                "thumbnail_url": asset_urls.get("thumbnail_url"),
                "predictions_json": row.get("predictions_json"),
                "uploaded_at": _convert_datetimes_to_ist(row.get("uploaded_at")),
            })

        cursor.execute(
            """
            SELECT search_id, query, timestamp
            FROM search_history
            WHERE user_id = %s
            ORDER BY timestamp DESC, search_id DESC
            """,
            (user_id,),
        )
        search_history = [_convert_datetimes_to_ist(dict(row)) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT wishlist_id, product_name, category, store_name, current_price,
                   product_url, image_url, source_query, created_at
            FROM wishlist_items
            WHERE user_id = %s
            ORDER BY created_at DESC, wishlist_id DESC
            """,
            (user_id,),
        )
        wishlist = [_convert_datetimes_to_ist(dict(row)) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT alert_id, query_text, target_price, notification_channel, contact_email,
                   is_active, is_triggered, last_checked_at, triggered_at,
                   last_triggered_price, created_at, updated_at
            FROM price_alerts
            WHERE user_id = %s
            ORDER BY created_at DESC, alert_id DESC
            """,
            (user_id,),
        )
        alerts = [_convert_datetimes_to_ist(dict(row)) for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT notification_id, alert_id, message, matched_price, matched_product_name,
                   matched_store_name, matched_product_url, delivery_channel, delivery_status,
                   is_read, created_at
            FROM alert_notifications
            WHERE user_id = %s
            ORDER BY created_at DESC, notification_id DESC
            """,
            (user_id,),
        )
        notifications = [_convert_datetimes_to_ist(dict(row)) for row in cursor.fetchall()]

        credentials = []
        if include_credentials:
            cursor.execute(
                """
                SELECT credential_id, provider, label, encrypted_value, created_at, updated_at
                FROM third_party_credentials
                WHERE user_id = %s
                ORDER BY updated_at DESC, credential_id DESC
                """,
                (user_id,),
            )
            for row in cursor.fetchall():
                secret_value = _decrypt_secret(row.get("encrypted_value"))
                credentials.append({
                    "credential_id": row.get("credential_id"),
                    "provider": row.get("provider"),
                    "label": row.get("label"),
                    "secret_value": secret_value,
                    "created_at": _convert_datetimes_to_ist(row.get("created_at")),
                    "updated_at": _convert_datetimes_to_ist(row.get("updated_at")),
                })

        export_payload = {
            "status": "success",
            "user": _convert_datetimes_to_ist(dict(user_row)),
            "uploads": uploads,
            "search_history": search_history,
            "wishlist": wishlist,
            "price_alerts": alerts,
            "alert_notifications": notifications,
            "third_party_credentials": credentials if include_credentials else [],
        }
        return jsonify(export_payload), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/account/delete", methods=["DELETE"])
@auth_required
def delete_account():
    user_id = g.user_id
    confirm = str(request.args.get("confirm") or "").strip().lower() in {"1", "true", "yes"}
    if not confirm:
        return jsonify({"status": "error", "error": "Confirm deletion with ?confirm=true"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT filename
            FROM uploads
            WHERE user_id = %s
            """,
            (user_id,),
        )
        filenames = [row.get("filename") for row in cursor.fetchall()]

        cursor.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({"status": "error", "error": "User not found"}), 404
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    deleted_files = 0
    for name in filenames:
        if not name:
            continue
        for candidate in (name, _build_thumbnail_filename(name)):
            if not candidate:
                continue
            path = os.path.join(UPLOAD_FOLDER, candidate)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    deleted_files += 1
            except Exception:
                pass

    return jsonify({
        "status": "success",
        "deleted_user_id": user_id,
        "deleted_files": deleted_files,
    }), 200


@app.route("/api/wishlist", methods=["GET"])
@auth_required
def list_wishlist_items():
    user_id = g.user_id

    limit, offset = _parse_limit_offset()
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT wishlist_id, user_id, product_name, category, store_name, current_price,
                   product_url, image_url, source_query, created_at
            FROM wishlist_items
            WHERE user_id = %s
            ORDER BY created_at DESC, wishlist_id DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, limit, offset),
        )
        rows = cursor.fetchall()
        return jsonify(_convert_datetimes_to_ist({
            "status": "success",
            "count": len(rows),
            "wishlist": rows,
        })), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/wishlist", methods=["POST"])
@auth_required
def create_wishlist_item():
    user_id = g.user_id

    payload, err = _normalize_wishlist_item(request.get_json(silent=True) or {})
    if err:
        return jsonify({"status": "error", "error": err}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO wishlist_items (
                user_id, product_name, category, store_name, current_price, product_url, image_url, source_query
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, product_url)
            DO UPDATE SET
                product_name = EXCLUDED.product_name,
                category = EXCLUDED.category,
                store_name = EXCLUDED.store_name,
                current_price = EXCLUDED.current_price,
                image_url = EXCLUDED.image_url,
                source_query = EXCLUDED.source_query
            RETURNING wishlist_id, user_id, product_name, category, store_name, current_price,
                      product_url, image_url, source_query, created_at
            """,
            (
                user_id,
                payload["product_name"],
                payload["category"],
                payload["store_name"],
                payload["current_price"],
                payload["product_url"],
                payload["image_url"],
                payload["source_query"],
            ),
        )
        row = cursor.fetchone()
        conn.commit()
        _bump_cache_version(_user_cache_scope(user_id))
        return jsonify(_convert_datetimes_to_ist({"status": "success", "wishlist_item": row})), 201
    finally:
        cursor.close()
        conn.close()


@app.route("/api/wishlist/<int:wishlist_id>", methods=["DELETE"])
@auth_required
def delete_wishlist_item(wishlist_id):
    user_id = g.user_id

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM wishlist_items
            WHERE wishlist_id = %s AND user_id = %s
            RETURNING wishlist_id
            """,
            (wishlist_id, user_id),
        )
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({"status": "error", "error": "Wishlist item not found"}), 404
        conn.commit()
        _bump_cache_version(_user_cache_scope(user_id))
        return jsonify({"status": "success", "deleted_wishlist_id": deleted["wishlist_id"]}), 200
    finally:
        cursor.close()
        conn.close()


register_catalog_routes(app, {
    "get_db": lambda: get_db(),
    "_validate_non_empty_text": lambda *args, **kwargs: _validate_non_empty_text(*args, **kwargs),
    "_validate_optional_text": lambda *args, **kwargs: _validate_optional_text(*args, **kwargs),
    "_validate_optional_url": lambda *args, **kwargs: _validate_optional_url(*args, **kwargs),
    "_validate_required_url": lambda *args, **kwargs: _validate_required_url(*args, **kwargs),
    "_validate_positive_int": lambda *args, **kwargs: _validate_positive_int(*args, **kwargs),
    "_validate_non_negative_price": lambda *args, **kwargs: _validate_non_negative_price(*args, **kwargs),
    "_parse_timestamp": lambda *args, **kwargs: _parse_timestamp(*args, **kwargs),
    "_convert_datetimes_to_ist": lambda *args, **kwargs: _convert_datetimes_to_ist(*args, **kwargs),
    "_parse_limit_offset": lambda *args, **kwargs: _parse_limit_offset(*args, **kwargs),
    "_parse_page_per_page": lambda *args, **kwargs: _parse_page_per_page(*args, **kwargs),
    "_build_trend_points": lambda *args, **kwargs: _build_trend_points(*args, **kwargs),
    "_is_relevant_result": lambda *args, **kwargs: _is_relevant_result(*args, **kwargs),
    "_evaluate_price_alerts": lambda *args, **kwargs: _evaluate_price_alerts(*args, **kwargs),
    "_bump_cache_version": lambda *args, **kwargs: _bump_cache_version(*args, **kwargs),
    "_user_cache_scope": lambda *args, **kwargs: _user_cache_scope(*args, **kwargs),
    "_sanitize_query_param": lambda *args, **kwargs: _sanitize_query_param(*args, **kwargs),
})
register_auth_routes(app, {
    "get_db": lambda: get_db(),
    "auth_required": auth_required,
    "_validate_required_email": lambda *args, **kwargs: _validate_required_email(*args, **kwargs),
    "_validate_optional_text": lambda *args, **kwargs: _validate_optional_text(*args, **kwargs),
    "_hash_password": lambda *args, **kwargs: _hash_password(*args, **kwargs),
    "_build_public_user_payload": lambda *args, **kwargs: _build_public_user_payload(*args, **kwargs),
    "create_token": lambda *args, **kwargs: create_token(*args, **kwargs),
    "_check_password": lambda *args, **kwargs: _check_password(*args, **kwargs),
    "_is_bcrypt_hash": lambda *args, **kwargs: _is_bcrypt_hash(*args, **kwargs),
    "_create_password_reset_token": lambda *args, **kwargs: _create_password_reset_token(*args, **kwargs),
    "_send_password_reset_email": lambda *args, **kwargs: _send_password_reset_email(*args, **kwargs),
    "_decode_password_reset_token": lambda *args, **kwargs: _decode_password_reset_token(*args, **kwargs),
    "_sanitize_text": lambda *args, **kwargs: _sanitize_text(*args, **kwargs),
    "USERNAME_PATTERN": USERNAME_PATTERN,
    "JWT_EXPIRY_SECONDS": JWT_EXPIRY_SECONDS,
})



init_db()


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5050")))
