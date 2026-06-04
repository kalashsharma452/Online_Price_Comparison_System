import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID", "").strip()
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET", "").strip()
EBAY_ACCESS_TOKEN = os.getenv("EBAY_ACCESS_TOKEN", "").strip()
EBAY_ENV = os.getenv("EBAY_ENV", "production").strip().lower()
EBAY_MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US").strip()
EBAY_TIMEOUT_SECONDS = int(os.getenv("EBAY_TIMEOUT_SECONDS", "12"))

TOKEN_CACHE = {"access_token": "", "expires_at": 0.0}


def _get_ebay_base_urls():
    if EBAY_ENV == "sandbox":
        return "https://api.sandbox.ebay.com", "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    return "https://api.ebay.com", "https://api.ebay.com/identity/v1/oauth2/token"


def _fetch_app_access_token():
    now = time.time()
    cached = TOKEN_CACHE.get("access_token", "")
    if cached and now < TOKEN_CACHE.get("expires_at", 0):
        return cached

    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        # Fallback for environments that still provide a manual token only.
        return EBAY_ACCESS_TOKEN

    _, token_url = _get_ebay_base_urls()
    payload = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }

    try:
        response = requests.post(
            token_url,
            auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET),
            data=payload,
            timeout=EBAY_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            print("eBay token error:", response.text)
            return ""
        token_data = response.json() if response.content else {}
        access_token = (token_data.get("access_token") or "").strip()
        expires_in = int(token_data.get("expires_in") or 7200)
        if not access_token:
            return ""
        TOKEN_CACHE["access_token"] = access_token
        # Refresh slightly early to avoid edge-expiry failures.
        TOKEN_CACHE["expires_at"] = now + max(60, expires_in - 60)
        return access_token
    except Exception as err:
        print("eBay token exception:", err)
        return ""


def search_ebay_products(query, limit=30):
    if not query or not query.strip():
        return []

    access_token = _fetch_app_access_token()
    if not access_token:
        return []

    api_base, _ = _get_ebay_base_urls()
    url = f"{api_base}/buy/browse/v1/item_summary/search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
    }
    params = {
        "q": query.strip(),
        "limit": max(1, min(int(limit or 20), 200)),
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=EBAY_TIMEOUT_SECONDS)
    except Exception as err:
        print("eBay request exception:", err)
        return []

    if response.status_code != 200:
        print("eBay API error:", response.text)
        return []

    data = response.json() if response.content else {}
    results = []
    for item in data.get("itemSummaries", []):
        price_obj = item.get("price") or {}
        value = price_obj.get("value")
        if value in (None, ""):
            continue
        try:
            price_value = float(value)
        except (TypeError, ValueError):
            continue

        image_obj = item.get("image") or {}
        image_url = image_obj.get("imageUrl")
        if not image_url:
            thumbnails = item.get("thumbnailImages") or []
            if thumbnails:
                image_url = (thumbnails[0] or {}).get("imageUrl")

        results.append(
            {
                "store": "eBay",
                "name": item.get("title"),
                "price": price_value,
                "currency": price_obj.get("currency", "USD"),
                "url": item.get("itemWebUrl"),
                "image_url": image_url,
                "availability": item.get("availabilityStatus"),
            }
        )
    return results
