import requests


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def search_platzi_products(query, limit=8):
    """
    Fetch products from Platzi Fake Store API and map into internal schema:
    {store, name, price, currency, url}
    """
    try:
        response = requests.get(
            "https://api.escuelajs.co/api/v1/products/",
            params={"title": query},
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    products = []
    for item in data[:limit]:
        price = _safe_float(item.get("price"))
        title = (item.get("title") or "").strip()
        product_id = item.get("id")
        if price is None or not title:
            continue

        products.append(
            {
                "store": "Platzi Fake Store",
                "name": title,
                "price": price,
                "currency": "USD",
                "url": f"https://api.escuelajs.co/api/v1/products/{product_id}" if product_id is not None else "",
            }
        )

    return products
