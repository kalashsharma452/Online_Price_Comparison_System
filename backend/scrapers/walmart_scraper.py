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
    cleaned = price_text.replace(",", "")
    # Prefer explicit currency amounts so model numbers like "iPhone 13"
    # are not misread as prices.
    match = re.search(r"\$\s*([0-9]+(?:\.[0-9]{1,2})?)", cleaned)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def search_walmart_products(query, limit=10):
    """
    Scrape Walmart search results and return normalized rows:
    {store, name, price, currency, url}
    """
    if not query or not query.strip():
        return []

    search_url = f"https://www.walmart.com/search?q={quote_plus(query.strip())}"
    try:
        headers = build_browser_headers(urlparse(search_url).netloc, referer="https://www.walmart.com/")
        response = throttled_get(search_url, headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text
    except Exception:
        html = None

    rows = _parse_walmart_html(html, limit=limit, query=query)
    if rows:
        return rows

    selenium_html = fetch_page_with_selenium(search_url, wait_seconds=4)
    if not selenium_html:
        return []
    return _parse_walmart_html(selenium_html, limit=limit, query=query)


def _parse_walmart_html(html, limit, query):
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    rows = []
    seen_urls = set()
    product_links = soup.select('a[href*="/ip/"]')

    for link_el in product_links:
        try:
            href = link_el.get("href", "").strip()
            if not href:
                continue

            absolute_url = urljoin("https://www.walmart.com", href)
            if absolute_url in seen_urls:
                continue

            title_el = link_el.select_one('[data-automation-id="product-title"]') or link_el.select_one("span")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            if not title:
                continue
            image_el = link_el.select_one("img")
            image_url = _extract_image_url(image_el)
            if not image_url and link_el.parent:
                image_url = _extract_image_url(link_el.parent.select_one("img"))
            if not image_url:
                ancestor = link_el.parent
                hop = 0
                while ancestor is not None and hop < 4 and not image_url:
                    image_url = _extract_image_url(ancestor.select_one("img"))
                    ancestor = ancestor.parent
                    hop += 1

            card_text = " ".join(link_el.parent.get_text(" ", strip=True).split()) if link_el.parent else ""
            price = _parse_price(card_text)
            if price is None:
                continue

            lower_text = card_text.lower()
            availability = "Unknown"
            if "out of stock" in lower_text:
                availability = "Out of stock"
            elif "in stock" in lower_text:
                availability = "In stock"

            shipping_info = None
            shipping_match = re.search(
                r"(free shipping|shipping.*?|delivery.*?)(?:\s{2,}|$)",
                card_text,
                re.IGNORECASE,
            )
            if shipping_match:
                shipping_info = shipping_match.group(1).strip()

            rating_match = re.search(r"([0-5](?:\.[0-9])?)\s*(?:out of 5|stars?)", card_text, re.IGNORECASE)
            seller_rating = rating_match.group(1) if rating_match else None

            seen_urls.add(absolute_url)
            rows.append(
                {
                    "store": "Walmart",
                    "name": title,
                    "price": price,
                    "currency": "USD",
                    "url": absolute_url,
                    "availability": availability,
                    "seller_rating": seller_rating,
                    "shipping_info": shipping_info,
                    "image_url": image_url,
                    "source_query": query.strip(),
                }
            )

            if len(rows) >= limit:
                break
        except Exception:
            continue

    return rows
