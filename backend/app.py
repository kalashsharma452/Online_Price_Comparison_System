from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
import tensorflow as tf
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from werkzeug.exceptions import RequestEntityTooLarge
from itsdangerous import URLSafeSerializer, BadSignature
from flask import send_from_directory
from tensorflow.keras.applications.imagenet_utils import decode_predictions
from dotenv import load_dotenv
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

load_dotenv()

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB
app.config["SECRET_KEY"] = "price-intelligence-secret"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._]+$")


def _env_flag(name, default=True):
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


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
API_RATE_LIMIT = int(os.getenv("API_RATE_LIMIT", "120"))
API_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("API_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_STORE = {}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
TARGET_SIZE = (224, 224)
model = tf.keras.applications.EfficientNetB0(weights="imagenet")
token_serializer = URLSafeSerializer(app.config["SECRET_KEY"], salt="auth-token")
IST_TZ = timezone(timedelta(hours=5, minutes=30))


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
            image_url TEXT
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
    conn.commit()
    cursor.close()
    conn.close()


def allowed_image_file(file):
    _, ext = os.path.splitext(file.filename.lower())
    return ext in ALLOWED_EXTENSIONS and file.mimetype in ALLOWED_MIME_TYPES


def create_token(user_id):
    return token_serializer.dumps({"user_id": user_id})


def get_user_id_from_request():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    try:
        payload = token_serializer.loads(token)
    except BadSignature:
        return None
    return payload.get("user_id")


def require_user():
    user_id = get_user_id_from_request()
    if not user_id:
        return None, (jsonify({"status": "error", "error": "Unauthorized"}), 401)
    return user_id, None


def _rate_limit_key():
    forwarded_for = (request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    return (request.remote_addr or "unknown").strip()


def _consume_rate_limit_bucket(identity):
    now = time.time()
    key = str(identity or "unknown").strip() or "unknown"
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


def _validate_non_empty_text(value, field_name, max_len=255):
    if not isinstance(value, str):
        return None, f"{field_name} must be a string"
    cleaned = value.strip()
    if not cleaned:
        return None, f"{field_name} is required"
    if len(cleaned) > max_len:
        return None, f"{field_name} must be <= {max_len} characters"
    return cleaned, None


def _validate_optional_text(value, field_name, max_len=255):
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{field_name} must be a string"
    cleaned = value.strip()
    if len(cleaned) > max_len:
        return None, f"{field_name} must be <= {max_len} characters"
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
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        limit = 50
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        offset = 0
    return limit, offset


def _parse_page_per_page(default_per_page=10, max_per_page=50):
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
        terms.append(identifier.strip())
    if product:
        terms.append(product.strip())

    for pred in predictions or []:
        label = (pred.get("label") or "").replace("_", " ").strip()
        if label:
            terms.append(label)

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
        return None

    image_url = (
        raw_product.get("image_url")
        or raw_product.get("image")
        or raw_product.get("thumbnail")
        or None
    )

    category = (raw_product.get("category") or "general").strip() or "general"

    return {
        "name": name,
        "category": category,
        "image_url": image_url,
        "store_name": store_name,
        "price": price_value,
        "product_url": product_url,
    }


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
            cursor.execute(
                """
                INSERT INTO products (name, category, image_url)
                VALUES (%s, %s, %s)
                RETURNING product_id
                """,
                (row["name"], row["category"], row["image_url"]),
            )
            product_id = cursor.fetchone()["product_id"]
            cursor.execute(
                """
                INSERT INTO prices (product_id, store_name, price, product_url)
                VALUES (%s, %s, %s, %s)
                """,
                (product_id, row["store_name"], row["price"], row["product_url"]),
            )
            inserted_count += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    return inserted_count


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
        return matches >= 2
    return matches >= max(2, len(tokens) // 2)


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


def _scrape_price_sources(query, limit=6):
    cache_key = _scrape_cache_key(query, limit)
    cached = _read_scrape_cache(cache_key)
    if cached:
        cached_rows = [dict(item) for item in cached.get("rows", [])]
        cached_providers = list(cached.get("providers_used", []))
        return cached_rows, cached_providers, True

    scraped = []
    providers_used = []

    if ENABLE_EBAY_OFFICIAL:
        try:
            ebay_official_rows = search_ebay_products(query)
            if ebay_official_rows:
                scraped.extend(ebay_official_rows[:limit])
                providers_used.append("ebay_official_api")
        except Exception as e:
            print("eBay official API failed:", e)

    try:
        amazon_rows = search_amazon_products(query, limit=limit)
        if amazon_rows:
            scraped.extend(amazon_rows)
            providers_used.append("amazon_scraper")
    except Exception as e:
        print("Amazon scraper failed:", e)

    if ENABLE_EBAY_SCRAPER:
        try:
            ebay_rows = search_ebay_products_scrape(query, limit=limit)
            if ebay_rows:
                scraped.extend(ebay_rows)
                providers_used.append("ebay_scraper")
        except Exception as e:
            print("eBay scraper failed:", e)

    try:
        walmart_rows = search_walmart_products(query, limit=limit)
        if walmart_rows:
            scraped.extend(walmart_rows)
            providers_used.append("walmart_scraper")
    except Exception as e:
        print("Walmart scraper failed:", e)

    deduped = _dedupe_scraped_products(scraped)
    relevant_rows = [item for item in deduped if _is_relevant_result(item, query)]
    _write_scrape_cache(cache_key, relevant_rows, providers_used)
    return relevant_rows, providers_used, False


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(_err):
    return jsonify({"status": "error", "error": "File too large. Max size is 10MB."}), 413


@app.before_request
def enforce_api_rate_limit():
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


@app.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""
    phone = (data.get("phone") or "").strip()
    postal_code = (data.get("postal_code") or "").strip()

    if len(username) < 3 or len(password) < 6:
        return jsonify({
            "status": "error",
            "error": "Username must be at least 3 chars and password at least 6 chars"
        }), 400
    if not USERNAME_PATTERN.fullmatch(username):
        return jsonify({
            "status": "error",
            "error": "Username can only contain letters, numbers, underscores (_) and dots (.), with no spaces."
        }), 400
    if password != confirm_password:
        return jsonify({
            "status": "error",
            "error": "Password and confirm password do not match"
        }), 400
    phone_digits = "".join(ch for ch in phone if ch.isdigit())
    if len(phone_digits) < 7 or len(phone_digits) > 15:
        return jsonify({
            "status": "error",
            "error": "Phone number must contain 7 to 15 digits"
        }), 400
    if len(postal_code) < 3 or len(postal_code) > 12:
        return jsonify({
            "status": "error",
            "error": "Postal code must be between 3 and 12 characters"
        }), 400

    from werkzeug.security import generate_password_hash

    password_hash = generate_password_hash(password)

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (username, phone, postal_code, password_hash)
            VALUES (%s, %s, %s, %s)
            RETURNING id, username, phone, postal_code
            """,
            (username, phone, postal_code, password_hash),
        )
        created_user = cursor.fetchone()
        conn.commit()
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        return jsonify({"status": "error", "error": "Username already exists"}), 409
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return jsonify({
        "status": "success",
        "user": {
            "id": created_user["id"],
            "username": created_user["username"],
            "phone": created_user["phone"],
            "postal_code": created_user["postal_code"],
        },
        "token": create_token(created_user["id"]),
    }), 201


@app.route("/api/auth/signin", methods=["POST"])
def signin():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, phone, postal_code, password_hash FROM users WHERE username = %s",
        (username,),
    )
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    from werkzeug.security import check_password_hash

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"status": "error", "error": "Invalid username or password"}), 401

    return jsonify({
        "status": "success",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "phone": user.get("phone"),
            "postal_code": user.get("postal_code"),
        },
        "token": create_token(user["id"]),
    }), 200


@app.route("/api/my-images", methods=["GET"])
def my_images():
    user_id, error_response = require_user()
    if error_response:
        return error_response

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT image_id, filename, predictions_json, uploaded_at
        FROM uploads
        WHERE user_id = %s
        ORDER BY uploaded_at DESC, id DESC
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    images = []
    base_url = request.host_url.rstrip("/")
    for row in rows:
        images.append({
            "image_id": row["image_id"],
            "filename": row["filename"],
            "image_url": f"{base_url}/api/uploads/{row['filename']}",
            "predictions": json.loads(row["predictions_json"]),
            "uploaded_at": row["uploaded_at"],
        })

    return jsonify(_convert_datetimes_to_ist({"status": "success", "images": images})), 200


@app.route("/api/my-images/<image_id>", methods=["DELETE"])
def delete_my_image(image_id):
    user_id, error_response = require_user()
    if error_response:
        return error_response

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
                filepath = os.path.join(UPLOAD_FOLDER, filename)
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
def upload_image():
    user_id, error_response = require_user()
    if error_response:
        return error_response

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

    try:
        image_id = str(uuid.uuid4())
        _, original_ext = os.path.splitext(file.filename.lower())
        filename = f"{image_id}{original_ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
    except Exception:
        return jsonify({"status": "error", "error": "Failed to save uploaded image"}), 500

    try:
        model_input = preprocess_for_efficientnet(filepath, target_size=TARGET_SIZE, use_tta=True)
        batch_predictions = model.predict(model_input, verbose=0)
        predictions = batch_predictions.mean(axis=0, keepdims=True)
        decoded = decode_predictions(predictions, top=3)
        results = [
            {"label": item[1], "confidence": float(item[2])}
            for item in decoded[0]
        ]
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

    return jsonify({
        "status": "success",
        "image_id": image_id,
        "image_url": f"{request.host_url.rstrip('/')}/api/uploads/{filename}",
        "predictions": results
    }), 201


@app.route("/api/compare-prices", methods=["GET"])
def compare_prices_api():
    query = (request.args.get("product") or "").strip()
    if not query:
        return jsonify({
            "status": "error",
            "error": "Missing required query param: product"
        }), 400

    page, per_page, page_err = _parse_page_per_page(default_per_page=10, max_per_page=50)
    if page_err:
        return jsonify({"status": "error", "error": page_err}), 400

    filters, filters_error = _build_comparison_filters()
    if filters_error:
        return jsonify({"status": "error", "error": filters_error}), 400

    scraped_results, providers_used, cache_hit = _scrape_price_sources(query, limit=6)
    source_mode = "scrapers_only"
    if not scraped_results:
        scraped_results = search_ebay_products_mock(query)
        providers_used = ["ebay_mock"]
        source_mode = "fallback_mock"
        cache_hit = False

    scraped_results = _convert_results_to_inr(scraped_results)
    summary = compare_prices(scraped_results, filters=filters)
    persisted_rows = 0 if cache_hit else _persist_search_products(scraped_results)
    all_results = summary.get("all_results", [])
    paged_results, pagination = _paginate_rows(all_results, page, per_page)
    summary["all_results"] = paged_results
    summary["pagination"] = pagination
    summary["query"] = query
    summary["source_mode"] = source_mode
    summary["providers_used"] = providers_used
    summary["cache_hit"] = cache_hit
    summary["cache_ttl_seconds"] = SCRAPE_CACHE_SECONDS
    summary["result_count"] = pagination["total_items"]
    summary["page_result_count"] = len(paged_results)
    summary["stored_rows"] = persisted_rows
    return jsonify(summary), 200


@app.route("/api/search-products", methods=["GET"])
def search_products_api():
    user_id, error_response = require_user()
    if error_response:
        return error_response

    product = (request.args.get("product") or "").strip()
    identifier = (request.args.get("identifier") or "").strip()
    image_id = (request.args.get("image_id") or "").strip()
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

    predictions = _get_predictions_from_upload(user_id, image_id=image_id if image_id else None)
    terms = _build_search_terms(product, identifier, predictions, max_terms=max_terms)
    if not terms:
        return jsonify({
            "status": "error",
            "error": "Provide product/identifier or upload an image first for recognition-based search.",
        }), 400

    all_results = []
    providers_used = []

    for term in terms:
        if ENABLE_EBAY_OFFICIAL:
            try:
                all_results.extend(search_ebay_products(term))
                providers_used.append("ebay_official_api")
            except Exception:
                pass
        try:
            all_results.extend(search_platzi_products(term))
            providers_used.append("platzi_api")
        except Exception:
            pass
        try:
            all_results.extend(search_dummyjson_products(term))
            providers_used.append("dummyjson_api")
        except Exception:
            pass
        try:
            all_results.extend(search_amazon_products(term, limit=limit))
            providers_used.append("amazon_scraper")
        except Exception:
            pass
        if ENABLE_EBAY_SCRAPER:
            try:
                all_results.extend(search_ebay_products_scrape(term, limit=limit))
                providers_used.append("ebay_scraper")
            except Exception:
                pass
        try:
            all_results.extend(search_walmart_products(term, limit=limit))
            providers_used.append("walmart_scraper")
        except Exception:
            pass

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

    _save_search_history(user_id, " | ".join(terms))
    persisted_rows = _persist_search_products(all_results)
    summary = compare_prices(all_results, filters=filters)
    return jsonify({
        "status": "success",
        "search_terms": terms,
        "providers_used": providers_used,
        "result_count": len(all_results),
        "stored_rows": persisted_rows,
        "summary": summary,
        "products": all_results,
    }), 200
@app.route("/api/products", methods=["POST"])
def create_product():
    data = request.get_json(silent=True) or {}
    name, err = _validate_non_empty_text(data.get("name"), "name", max_len=255)
    if err:
        return jsonify({"status": "error", "error": err}), 400

    category, err = _validate_optional_text(data.get("category"), "category", max_len=120)
    if err:
        return jsonify({"status": "error", "error": err}), 400
    category = category or "general"

    image_url, err = _validate_optional_url(data.get("image_url"), "image_url")
    if err:
        return jsonify({"status": "error", "error": err}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO products (name, category, image_url)
            VALUES (%s, %s, %s)
            RETURNING product_id, name, category, image_url
            """,
            (name, category, image_url),
        )
        row = cursor.fetchone()
        conn.commit()
        return jsonify({"status": "success", "product": row}), 201
    finally:
        cursor.close()
        conn.close()


@app.route("/api/products", methods=["GET"])
def list_products():
    name = (request.args.get("name") or "").strip()
    category = (request.args.get("category") or "").strip()
    limit, offset = _parse_limit_offset()

    clauses = []
    params = []
    if name:
        clauses.append("name ILIKE %s")
        params.append(f"%{name}%")
    if category:
        clauses.append("category = %s")
        params.append(category)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT product_id, name, category, image_url
        FROM products
        {where_sql}
        ORDER BY product_id DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        return jsonify({"status": "success", "count": len(rows), "products": rows}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT product_id, name, category, image_url
            FROM products
            WHERE product_id = %s
            """,
            (product_id,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"status": "error", "error": "Product not found"}), 404
        return jsonify({"status": "success", "product": row}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    data = request.get_json(silent=True) or {}
    updates = []
    params = []

    if "name" in data:
        name, err = _validate_non_empty_text(data.get("name"), "name", max_len=255)
        if err:
            return jsonify({"status": "error", "error": err}), 400
        updates.append("name = %s")
        params.append(name)

    if "category" in data:
        category, err = _validate_non_empty_text(data.get("category"), "category", max_len=120)
        if err:
            return jsonify({"status": "error", "error": err}), 400
        updates.append("category = %s")
        params.append(category)

    if "image_url" in data:
        image_url, err = _validate_optional_url(data.get("image_url"), "image_url")
        if err:
            return jsonify({"status": "error", "error": err}), 400
        updates.append("image_url = %s")
        params.append(image_url)

    if not updates:
        return jsonify({"status": "error", "error": "No valid fields provided to update"}), 400

    params.append(product_id)
    sql = f"""
        UPDATE products
        SET {", ".join(updates)}
        WHERE product_id = %s
        RETURNING product_id, name, category, image_url
    """

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return jsonify({"status": "error", "error": "Product not found"}), 404
        conn.commit()
        return jsonify({"status": "success", "product": row}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM products WHERE product_id = %s RETURNING product_id",
            (product_id,),
        )
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({"status": "error", "error": "Product not found"}), 404
        conn.commit()
        return jsonify({"status": "success", "deleted_product_id": deleted["product_id"]}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/prices", methods=["POST"])
def create_price():
    data = request.get_json(silent=True) or {}

    product_id, err = _validate_positive_int(data.get("product_id"), "product_id")
    if err:
        return jsonify({"status": "error", "error": err}), 400

    store_name, err = _validate_non_empty_text(data.get("store_name"), "store_name", max_len=120)
    if err:
        return jsonify({"status": "error", "error": err}), 400

    price_value, err = _validate_non_negative_price(data.get("price"))
    if err:
        return jsonify({"status": "error", "error": err}), 400

    product_url, err = _validate_required_url(data.get("product_url"), "product_url")
    if err:
        return jsonify({"status": "error", "error": err}), 400

    timestamp_value, err = _parse_timestamp(data.get("timestamp"))
    if err:
        return jsonify({"status": "error", "error": err}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM products WHERE product_id = %s", (product_id,))
        if not cursor.fetchone():
            return jsonify({"status": "error", "error": "product_id does not exist"}), 400

        if timestamp_value is None:
            cursor.execute(
                """
                INSERT INTO prices (product_id, store_name, price, product_url)
                VALUES (%s, %s, %s, %s)
                RETURNING price_id, product_id, store_name, price, timestamp, product_url
                """,
                (product_id, store_name, price_value, product_url),
            )
        else:
            cursor.execute(
                """
                INSERT INTO prices (product_id, store_name, price, timestamp, product_url)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING price_id, product_id, store_name, price, timestamp, product_url
                """,
                (product_id, store_name, price_value, timestamp_value, product_url),
            )
        row = cursor.fetchone()
        conn.commit()
        return jsonify(_convert_datetimes_to_ist({"status": "success", "price": row})), 201
    finally:
        cursor.close()
        conn.close()


@app.route("/api/prices", methods=["GET"])
def list_prices():
    limit, offset = _parse_limit_offset()
    store_name = (request.args.get("store_name") or "").strip()
    product_id_raw = (request.args.get("product_id") or "").strip()

    clauses = []
    params = []

    if store_name:
        clauses.append("store_name = %s")
        params.append(store_name)

    if product_id_raw:
        product_id, err = _validate_positive_int(product_id_raw, "product_id")
        if err:
            return jsonify({"status": "error", "error": err}), 400
        clauses.append("product_id = %s")
        params.append(product_id)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT price_id, product_id, store_name, price, timestamp, product_url
        FROM prices
        {where_sql}
        ORDER BY timestamp DESC, price_id DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        return jsonify(_convert_datetimes_to_ist({"status": "success", "count": len(rows), "prices": rows})), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/price-history", methods=["GET"])
def price_history_api():
    product_id_raw = (request.args.get("product_id") or "").strip()
    if not product_id_raw:
        return jsonify({"status": "error", "error": "Missing required query param: product_id"}), 400

    product_id, err = _validate_positive_int(product_id_raw, "product_id")
    if err:
        return jsonify({"status": "error", "error": err}), 400

    page, per_page, page_err = _parse_page_per_page(default_per_page=20, max_per_page=100)
    if page_err:
        return jsonify({"status": "error", "error": page_err}), 400
    offset = (page - 1) * per_page

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT product_id, name, category, image_url
            FROM products
            WHERE product_id = %s
            """,
            (product_id,),
        )
        product_row = cursor.fetchone()
        if not product_row:
            return jsonify({"status": "error", "error": "Product not found"}), 404

        cursor.execute(
            """
            SELECT COUNT(*) AS total_count
            FROM prices
            WHERE product_id = %s
            """,
            (product_id,),
        )
        total_history_count = int(cursor.fetchone()["total_count"])

        cursor.execute(
            """
            SELECT
                MIN(price) AS min_price,
                MAX(price) AS max_price,
                AVG(price) AS average_price
            FROM prices
            WHERE product_id = %s
            """,
            (product_id,),
        )
        stats_row = cursor.fetchone() or {}

        cursor.execute(
            """
            SELECT price
            FROM prices
            WHERE product_id = %s
            ORDER BY timestamp DESC, price_id DESC
            LIMIT 1
            """,
            (product_id,),
        )
        latest_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT price
            FROM prices
            WHERE product_id = %s
            ORDER BY timestamp ASC, price_id ASC
            LIMIT 1
            """,
            (product_id,),
        )
        oldest_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT price_id, product_id, store_name, price, timestamp, product_url
            FROM prices
            WHERE product_id = %s
            ORDER BY timestamp DESC, price_id DESC
            LIMIT %s OFFSET %s
            """,
            (product_id, per_page, offset),
        )
        history_rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    latest_price = float(latest_row["price"]) if latest_row and latest_row.get("price") is not None else None
    oldest_price = float(oldest_row["price"]) if oldest_row and oldest_row.get("price") is not None else None
    min_price = float(stats_row["min_price"]) if stats_row and stats_row.get("min_price") is not None else None
    max_price = float(stats_row["max_price"]) if stats_row and stats_row.get("max_price") is not None else None
    avg_price = float(stats_row["average_price"]) if stats_row and stats_row.get("average_price") is not None else None
    price_change = None
    if latest_price is not None and oldest_price is not None:
        price_change = round(latest_price - oldest_price, 2)
    total_pages = (total_history_count + per_page - 1) // per_page if total_history_count else 0

    return jsonify(_convert_datetimes_to_ist({
        "status": "success",
        "product": product_row,
        "count": len(history_rows),
        "total_count": total_history_count,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_items": total_history_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1 and total_pages > 0,
        },
        "latest_price": latest_price,
        "oldest_price": oldest_price,
        "min_price": min_price,
        "max_price": max_price,
        "average_price": round(avg_price, 2) if avg_price is not None else None,
        "price_change": price_change,
        "history": history_rows,
    })), 200


@app.route("/api/prices/<int:price_id>", methods=["GET"])
def get_price(price_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT price_id, product_id, store_name, price, timestamp, product_url
            FROM prices
            WHERE price_id = %s
            """,
            (price_id,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"status": "error", "error": "Price not found"}), 404
        return jsonify(_convert_datetimes_to_ist({"status": "success", "price": row})), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/prices/<int:price_id>", methods=["PUT"])
def update_price(price_id):
    data = request.get_json(silent=True) or {}
    updates = []
    params = []

    conn = get_db()
    cursor = conn.cursor()
    try:
        if "product_id" in data:
            product_id, err = _validate_positive_int(data.get("product_id"), "product_id")
            if err:
                return jsonify({"status": "error", "error": err}), 400
            cursor.execute("SELECT 1 FROM products WHERE product_id = %s", (product_id,))
            if not cursor.fetchone():
                return jsonify({"status": "error", "error": "product_id does not exist"}), 400
            updates.append("product_id = %s")
            params.append(product_id)

        if "store_name" in data:
            store_name, err = _validate_non_empty_text(data.get("store_name"), "store_name", max_len=120)
            if err:
                return jsonify({"status": "error", "error": err}), 400
            updates.append("store_name = %s")
            params.append(store_name)

        if "price" in data:
            price_value, err = _validate_non_negative_price(data.get("price"))
            if err:
                return jsonify({"status": "error", "error": err}), 400
            updates.append("price = %s")
            params.append(price_value)

        if "product_url" in data:
            product_url, err = _validate_required_url(data.get("product_url"), "product_url")
            if err:
                return jsonify({"status": "error", "error": err}), 400
            updates.append("product_url = %s")
            params.append(product_url)

        if "timestamp" in data:
            timestamp_value, err = _parse_timestamp(data.get("timestamp"))
            if err:
                return jsonify({"status": "error", "error": err}), 400
            if timestamp_value is None:
                return jsonify({"status": "error", "error": "timestamp cannot be empty"}), 400
            updates.append("timestamp = %s")
            params.append(timestamp_value)

        if not updates:
            return jsonify({"status": "error", "error": "No valid fields provided to update"}), 400

        params.append(price_id)
        sql = f"""
            UPDATE prices
            SET {", ".join(updates)}
            WHERE price_id = %s
            RETURNING price_id, product_id, store_name, price, timestamp, product_url
        """
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return jsonify({"status": "error", "error": "Price not found"}), 404
        conn.commit()
        return jsonify(_convert_datetimes_to_ist({"status": "success", "price": row})), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/prices/<int:price_id>", methods=["DELETE"])
def delete_price(price_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM prices WHERE price_id = %s RETURNING price_id",
            (price_id,),
        )
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({"status": "error", "error": "Price not found"}), 404
        conn.commit()
        return jsonify({"status": "success", "deleted_price_id": deleted["price_id"]}), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/search-history", methods=["POST"])
def create_search_history():
    data = request.get_json(silent=True) or {}

    user_id, err = _validate_positive_int(data.get("user_id"), "user_id")
    if err:
        return jsonify({"status": "error", "error": err}), 400

    query_text, err = _validate_non_empty_text(data.get("query"), "query", max_len=500)
    if err:
        return jsonify({"status": "error", "error": err}), 400

    timestamp_value, err = _parse_timestamp(data.get("timestamp"))
    if err:
        return jsonify({"status": "error", "error": err}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            return jsonify({"status": "error", "error": "user_id does not exist"}), 400

        if timestamp_value is None:
            cursor.execute(
                """
                INSERT INTO search_history (user_id, query)
                VALUES (%s, %s)
                RETURNING search_id, user_id, query, timestamp
                """,
                (user_id, query_text),
            )
        else:
            cursor.execute(
                """
                INSERT INTO search_history (user_id, query, timestamp)
                VALUES (%s, %s, %s)
                RETURNING search_id, user_id, query, timestamp
                """,
                (user_id, query_text, timestamp_value),
            )
        row = cursor.fetchone()
        conn.commit()
        return jsonify(_convert_datetimes_to_ist({"status": "success", "search_history": row})), 201
    finally:
        cursor.close()
        conn.close()


@app.route("/api/search-history", methods=["GET"])
def list_search_history():
    limit, offset = _parse_limit_offset()
    user_id_raw = (request.args.get("user_id") or "").strip()
    query_filter = (request.args.get("query") or "").strip()

    clauses = []
    params = []

    if user_id_raw:
        user_id, err = _validate_positive_int(user_id_raw, "user_id")
        if err:
            return jsonify({"status": "error", "error": err}), 400
        clauses.append("user_id = %s")
        params.append(user_id)

    if query_filter:
        clauses.append("query ILIKE %s")
        params.append(f"%{query_filter}%")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT search_id, user_id, query, timestamp
        FROM search_history
        {where_sql}
        ORDER BY timestamp DESC, search_id DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
        return jsonify(_convert_datetimes_to_ist({"status": "success", "count": len(rows), "search_history": rows})), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/search-history/<int:search_id>", methods=["GET"])
def get_search_history(search_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT search_id, user_id, query, timestamp
            FROM search_history
            WHERE search_id = %s
            """,
            (search_id,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"status": "error", "error": "Search history entry not found"}), 404
        return jsonify(_convert_datetimes_to_ist({"status": "success", "search_history": row})), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/search-history/<int:search_id>", methods=["PUT"])
def update_search_history(search_id):
    data = request.get_json(silent=True) or {}
    updates = []
    params = []

    conn = get_db()
    cursor = conn.cursor()
    try:
        if "user_id" in data:
            user_id, err = _validate_positive_int(data.get("user_id"), "user_id")
            if err:
                return jsonify({"status": "error", "error": err}), 400
            cursor.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
            if not cursor.fetchone():
                return jsonify({"status": "error", "error": "user_id does not exist"}), 400
            updates.append("user_id = %s")
            params.append(user_id)

        if "query" in data:
            query_text, err = _validate_non_empty_text(data.get("query"), "query", max_len=500)
            if err:
                return jsonify({"status": "error", "error": err}), 400
            updates.append("query = %s")
            params.append(query_text)

        if "timestamp" in data:
            timestamp_value, err = _parse_timestamp(data.get("timestamp"))
            if err:
                return jsonify({"status": "error", "error": err}), 400
            if timestamp_value is None:
                return jsonify({"status": "error", "error": "timestamp cannot be empty"}), 400
            updates.append("timestamp = %s")
            params.append(timestamp_value)

        if not updates:
            return jsonify({"status": "error", "error": "No valid fields provided to update"}), 400

        params.append(search_id)
        sql = f"""
            UPDATE search_history
            SET {", ".join(updates)}
            WHERE search_id = %s
            RETURNING search_id, user_id, query, timestamp
        """
        cursor.execute(sql, tuple(params))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return jsonify({"status": "error", "error": "Search history entry not found"}), 404
        conn.commit()
        return jsonify(_convert_datetimes_to_ist({"status": "success", "search_history": row})), 200
    finally:
        cursor.close()
        conn.close()


@app.route("/api/search-history/<int:search_id>", methods=["DELETE"])
def delete_search_history(search_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM search_history WHERE search_id = %s RETURNING search_id",
            (search_id,),
        )
        deleted = cursor.fetchone()
        if not deleted:
            conn.rollback()
            return jsonify({"status": "error", "error": "Search history entry not found"}), 404
        conn.commit()
        return jsonify({"status": "success", "deleted_search_id": deleted["search_id"]}), 200
    finally:
        cursor.close()
        conn.close()



init_db()


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5050")))


