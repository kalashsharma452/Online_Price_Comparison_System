import requests


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def search_dummyjson_products(query, limit=8):
    """
    Fetch products from DummyJSON and map into internal schema:
    {store, name, price, currency, url}
    """
    try:
        response = requests.get(
            "https://dummyjson.com/products/search",
            params={"q": query, "limit": limit},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    items = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []

    products = []
    for item in items:
        price = _safe_float(item.get("price"))
        title = (item.get("title") or "").strip()
        product_id = item.get("id")
        if price is None or not title:
            continue

        products.append(
            {
                "store": "DummyJSON",
                "name": title,
                "price": price,
                "currency": "USD",
                "url": f"https://dummyjson.com/products/{product_id}" if product_id is not None else "",
            }
        )

    return products
