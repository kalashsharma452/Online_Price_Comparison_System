import re
from urllib.parse import quote_plus
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
    # eBay often shows ranges like "$12.00 to $15.00"; use first number.
    match = re.search(r"([0-9][0-9,]*\.?[0-9]*)", price_text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def search_ebay_products(query, limit=10, site="www.ebay.com"):
    """
    Scrape eBay search results and return normalized rows:
    {store, name, price, currency, url}
    """
    if not query or not query.strip():
        return []

    search_url = f"https://{site}/sch/i.html?_nkw={quote_plus(query.strip())}"
    try:
        headers = build_browser_headers(urlparse(search_url).netloc, referer=f"https://{site}/")
        response = throttled_get(search_url, headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text
    except Exception:
        html = None

    rows = _parse_ebay_html(html, limit=limit, query=query)
    if rows:
        return rows

    selenium_html = fetch_page_with_selenium(search_url, wait_seconds=3)
    if not selenium_html:
        return []
    return _parse_ebay_html(selenium_html, limit=limit, query=query)


def _parse_ebay_html(html, limit, query):
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    rows = []
    for card in soup.select("li.s-item"):
        try:
            title_el = card.select_one(".s-item__title")
            price_el = card.select_one(".s-item__price")
            link_el = card.select_one(".s-item__link")

            if not title_el or not price_el or not link_el:
                continue

            title = title_el.get_text(" ", strip=True)
            if not title or title.lower() == "shop on ebay":
                continue

            price = _parse_price(price_el.get_text(" ", strip=True))
            if price is None:
                continue

            href = link_el.get("href", "").strip()
            if not href:
                continue

            shipping_el = card.select_one(".s-item__shipping")
            condition_el = card.select_one(".SECONDARY_INFO")
            seller_el = card.select_one(".s-item__seller-info-text")
            rating_el = card.select_one(".x-star-rating span.clipped") or card.select_one(".b-starrating__stars")
            image_el = card.select_one(".s-item__image-img")
            image_url = _extract_image_url(image_el)

            rows.append(
                {
                    "store": "eBay",
                    "name": title,
                    "price": price,
                    "currency": "USD",
                    "url": href,
                    "availability": condition_el.get_text(" ", strip=True) if condition_el else "Unknown",
                    "seller_rating": (
                        rating_el.get_text(" ", strip=True)
                        if rating_el
                        else (seller_el.get_text(" ", strip=True) if seller_el else None)
                    ),
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
