import re
from urllib.parse import quote_plus
from urllib.parse import urljoin
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from .http_client import build_browser_headers, fetch_page_with_selenium, throttled_get


def _extract_image_url(img_el):
    if not img_el:
        return None
    candidates = [
        img_el.get("src"),
        img_el.get("data-src"),
        img_el.get("data-image-src"),
        img_el.get("srcset"),
        img_el.get("data-srcset"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        token = str(candidate).split(",")[0].strip().split(" ")[0].strip()
        if token and not token.startswith("data:"):
            return token
    return None


def _parse_price(price_text):
    if not price_text:
        return None
    cleaned = re.sub(r"[^0-9.,]", "", price_text)
    cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def search_amazon_products(query, limit=10, domain="amazon.in"):
    """
    Scrape Amazon search results and return normalized rows:
    {store, name, price, currency, url}
    """
    if not query or not query.strip():
        return []

    search_url = f"https://{domain}/s?k={quote_plus(query.strip())}"
    try:
        headers = build_browser_headers(urlparse(search_url).netloc, referer=f"https://{domain}/")
        response = throttled_get(search_url, headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text
    except Exception:
        html = None

    rows = _parse_amazon_html(html, limit=limit, domain=domain, query=query)
    if rows:
        return rows

    selenium_html = fetch_page_with_selenium(search_url, wait_seconds=3)
    if not selenium_html:
        return []
    return _parse_amazon_html(selenium_html, limit=limit, domain=domain, query=query)


def _parse_amazon_html(html, limit, domain, query):
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    rows = []
    for card in soup.select('div.s-result-item[data-component-type="s-search-result"]'):
        try:
            title_el = card.select_one("h2 a span")
            link_el = card.select_one("h2 a")
            price_el = card.select_one(".a-price .a-offscreen") or card.select_one(".a-price-whole")

            if not title_el or not link_el or not price_el:
                continue

            price = _parse_price(price_el.get_text(" ", strip=True))
            if price is None:
                continue

            href = link_el.get("href", "").strip()
            if not href:
                continue

            rating_el = card.select_one(".a-icon-alt")
            availability_el = card.select_one(".a-color-price") or card.select_one(".a-color-state")
            shipping_el = card.select_one(
                '[aria-label*="delivery"], [aria-label*="shipping"], .a-color-base, .a-color-secondary'
            )
            image_el = card.select_one("img.s-image")
            image_url = _extract_image_url(image_el)

            rows.append(
                {
                    "store": "Amazon",
                    "name": title_el.get_text(" ", strip=True),
                    "price": price,
                    "currency": "INR",
                    "url": urljoin(f"https://{domain}", href),
                    "availability": (
                        availability_el.get_text(" ", strip=True) if availability_el else "Unknown"
                    ),
                    "seller_rating": rating_el.get_text(" ", strip=True) if rating_el else None,
                    "shipping_info": shipping_el.get_text(" ", strip=True) if shipping_el else None,
                    "image_url": image_url,
                    "source_query": query.strip(),
                }
            )
            if len(rows) >= limit:
                break
        except Exception:
            continue

    return rows
