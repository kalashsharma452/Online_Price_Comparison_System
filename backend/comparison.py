import re
from statistics import median


STOP_WORDS = {
    "a", "an", "and", "or", "for", "the", "with", "new", "latest", "edition",
    "pack", "set", "inch", "inches", "cm", "mm", "gb", "tb", "model", "version",
}


DEFAULT_SCORING_WEIGHTS = {
    "price": 0.6,
    "shipping": 0.2,
    "reputation": 0.2,
}


def _safe_price(value):
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price >= 0 else None


def _normalize_store(value):
    cleaned = (value or "Unknown").strip()
    return cleaned or "Unknown"


def _normalize_name(value):
    return " ".join((value or "").strip().split())


def _name_tokens(name):
    base = _normalize_name(name).lower()
    parts = re.findall(r"[a-z0-9]+", base)
    tokens = set()
    for part in parts:
        if not part or part in STOP_WORDS:
            continue
        tokens.add(part)
        # Expand mixed model tokens to improve cross-source matching:
        # e.g., "wh1000xm5" -> {"wh", "1000", "xm", "5"}
        sub_parts = re.findall(r"[a-z]+|[0-9]+", part)
        for sub in sub_parts:
            if sub and sub not in STOP_WORDS:
                tokens.add(sub)
    return tokens


def _parse_seller_rating(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        rating = float(value)
        if 0 <= rating <= 5:
            return round(rating, 2)
        if 0 <= rating <= 100:
            return round(rating / 20.0, 2)
        return None

    text = str(value).strip().lower()
    if not text:
        return None

    out_of_five = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:/|out of)\s*5", text)
    if out_of_five:
        return round(float(out_of_five.group(1)), 2)

    percent = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", text)
    if percent:
        return round(float(percent.group(1)) / 20.0, 2)

    generic = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    if not generic:
        return None
    value_num = float(generic.group(1))
    if 0 <= value_num <= 5:
        return round(value_num, 2)
    if 0 <= value_num <= 100:
        return round(value_num / 20.0, 2)
    return None


def _parse_shipping_cost(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        cost = float(value)
        return cost if cost >= 0 else None

    text = str(value).strip().lower()
    if not text:
        return None
    if "free" in text:
        return 0.0
    money = re.search(r"([0-9]+(?:\.[0-9]+)?)", text.replace(",", ""))
    if not money:
        return None
    cost = float(money.group(1))
    return cost if cost >= 0 else None


def _normalize_availability(value):
    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    if "out of stock" in text or "unavailable" in text or "sold out" in text:
        return "out_of_stock"
    if "in stock" in text or "available" in text or "ships" in text:
        return "in_stock"
    return "unknown"


def _parse_tax_amount(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        tax = float(value)
        return tax if tax >= 0 else None

    text = str(value).strip().lower()
    if not text:
        return None
    money = re.search(r"([0-9]+(?:\.[0-9]+)?)", text.replace(",", ""))
    if not money:
        return None
    tax = float(money.group(1))
    return tax if tax >= 0 else None


def _normalize_weights(weights):
    w = dict(DEFAULT_SCORING_WEIGHTS)
    if isinstance(weights, dict):
        for key in ("price", "shipping", "reputation"):
            if key in weights:
                try:
                    w[key] = max(0.0, float(weights[key]))
                except (TypeError, ValueError):
                    pass

    total = w["price"] + w["shipping"] + w["reputation"]
    if total <= 0:
        return dict(DEFAULT_SCORING_WEIGHTS)

    return {
        "price": w["price"] / total,
        "shipping": w["shipping"] / total,
        "reputation": w["reputation"] / total,
    }


def _jaccard_similarity(tokens_a, tokens_b):
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return (intersection / union) if union else 0.0


def _to_normalized_rows(products, filters=None):
    filters = filters or {}
    global_tax_rate = filters.get("tax_rate")

    rows = []
    for raw in products or []:
        if not isinstance(raw, dict):
            continue
        price = _safe_price(raw.get("price"))
        if price is None:
            continue

        name = _normalize_name(
            raw.get("name") or raw.get("title") or raw.get("product_name") or ""
        )
        if not name:
            continue

        row = dict(raw)
        row["price"] = price
        row["name"] = name
        row["store"] = _normalize_store(raw.get("store") or raw.get("store_name"))
        row["_tokens"] = _name_tokens(name)
        row["_seller_rating"] = _parse_seller_rating(raw.get("seller_rating"))
        row["_shipping_cost"] = _parse_shipping_cost(
            raw.get("shipping_cost") if "shipping_cost" in raw else raw.get("shipping_info")
        )
        row["_availability"] = _normalize_availability(raw.get("availability"))
        row["_tax_amount"] = _parse_tax_amount(
            raw.get("tax_amount") if "tax_amount" in raw else raw.get("tax") or raw.get("estimated_tax")
        )
        if row["_tax_amount"] is None:
            raw_tax_rate = raw.get("tax_rate")
            if raw_tax_rate is not None:
                try:
                    parsed_rate = float(raw_tax_rate)
                    row["_tax_amount"] = price * parsed_rate if parsed_rate >= 0 else None
                except (TypeError, ValueError):
                    row["_tax_amount"] = None
            elif global_tax_rate is not None:
                row["_tax_amount"] = price * global_tax_rate

        shipping_cost = row["_shipping_cost"] if row["_shipping_cost"] is not None else 0.0
        tax_amount = row["_tax_amount"] if row["_tax_amount"] is not None else 0.0
        row["_total_cost"] = round(price + shipping_cost + tax_amount, 2)
        rows.append(row)
    return rows


def _cluster_by_name_similarity(rows, min_similarity=0.45):
    clusters = []
    for row in rows:
        best_idx = None
        best_score = 0.0
        for idx, cluster in enumerate(clusters):
            score = _jaccard_similarity(row["_tokens"], cluster["centroid_tokens"])
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx is not None and best_score >= min_similarity:
            cluster = clusters[best_idx]
            cluster["items"].append(row)
            # keep centroid stable using the longest-name item in cluster
            cluster["items"].sort(key=lambda x: len(x["name"]), reverse=True)
            cluster["centroid_tokens"] = cluster["items"][0]["_tokens"]
        else:
            clusters.append({
                "items": [row],
                "centroid_tokens": row["_tokens"],
            })
    return clusters


def _cluster_score(cluster):
    items = cluster["items"]
    stores = {item["store"].lower() for item in items}
    # prioritize multi-source agreement, then cluster size
    return (len(stores), len(items))


def _apply_filters(rows, filters=None):
    filters = filters or {}
    min_seller_rating = filters.get("min_seller_rating")
    max_shipping_cost = filters.get("max_shipping_cost")
    availability = (filters.get("availability") or "any").strip().lower()

    filtered = []
    for row in rows:
        if min_seller_rating is not None:
            if row.get("_seller_rating") is None or row["_seller_rating"] < min_seller_rating:
                continue
        if max_shipping_cost is not None:
            if row.get("_shipping_cost") is None or row["_shipping_cost"] > max_shipping_cost:
                continue
        if availability in {"in_stock", "out_of_stock"}:
            if row.get("_availability") != availability:
                continue
        filtered.append(row)
    return filtered


def _normalize_linear(value, min_value, max_value, reverse=False):
    if max_value <= min_value:
        return 1.0
    ratio = (value - min_value) / (max_value - min_value)
    ratio = min(1.0, max(0.0, ratio))
    return 1.0 - ratio if reverse else ratio


def _attach_scoring(rows, weights=None):
    if not rows:
        return rows, _normalize_weights(weights)

    normalized_weights = _normalize_weights(weights)
    totals = [row["_total_cost"] for row in rows]
    shipping_values = [
        row["_shipping_cost"] if row["_shipping_cost"] is not None else max(
            (r["_shipping_cost"] for r in rows if r["_shipping_cost"] is not None),
            default=0.0
        )
        for row in rows
    ]

    min_total, max_total = min(totals), max(totals)
    min_shipping, max_shipping = min(shipping_values), max(shipping_values)

    scored_rows = []
    for idx, row in enumerate(rows):
        price_component = _normalize_linear(row["_total_cost"], min_total, max_total, reverse=True)
        shipping_val = shipping_values[idx]
        shipping_component = _normalize_linear(shipping_val, min_shipping, max_shipping, reverse=True)
        reputation_component = (row["_seller_rating"] / 5.0) if row["_seller_rating"] is not None else 0.0

        score = 100.0 * (
            normalized_weights["price"] * price_component
            + normalized_weights["shipping"] * shipping_component
            + normalized_weights["reputation"] * reputation_component
        )

        enriched = dict(row)
        enriched["_score"] = round(score, 2)
        enriched["_score_breakdown"] = {
            "price_component": round(price_component, 4),
            "shipping_component": round(shipping_component, 4),
            "reputation_component": round(reputation_component, 4),
        }
        scored_rows.append(enriched)

    scored_rows.sort(key=lambda x: x["_score"], reverse=True)
    for rank, row in enumerate(scored_rows, start=1):
        row["_rank"] = rank
    return scored_rows, normalized_weights


def _to_public_row(row):
    return {
        k: v for k, v in row.items() if not k.startswith("_")
    } | {
        "seller_rating_normalized": row.get("_seller_rating"),
        "shipping_cost": row.get("_shipping_cost"),
        "tax_amount": row.get("_tax_amount"),
        "total_cost": row.get("_total_cost"),
        "score": row.get("_score"),
        "rank": row.get("_rank"),
        "score_breakdown": row.get("_score_breakdown"),
    }


def _summarize_rows(rows):
    prices = [row["price"] for row in rows]
    total_costs = [row["_total_cost"] for row in rows]
    lowest = min(rows, key=lambda x: x["price"])
    highest = max(rows, key=lambda x: x["price"])
    lowest_total = min(rows, key=lambda x: x["_total_cost"])
    highest_total = max(rows, key=lambda x: x["_total_cost"])

    by_store = {}
    for row in rows:
        store = row["store"]
        if store not in by_store:
            by_store[store] = []
        by_store[store].append(row)

    aggregated_by_store = []
    for store, store_rows in by_store.items():
        sorted_rows = sorted(store_rows, key=lambda x: x["price"])
        aggregated_by_store.append({
            "store": store,
            "listing_count": len(store_rows),
            "lowest_price": sorted_rows[0]["price"],
            "highest_price": sorted_rows[-1]["price"],
            "average_price": round(sum(item["price"] for item in store_rows) / len(store_rows), 2),
            "lowest_total_cost": round(min(item["_total_cost"] for item in store_rows), 2),
            "average_total_cost": round(sum(item["_total_cost"] for item in store_rows) / len(store_rows), 2),
            "best_listing": _to_public_row(sorted_rows[0]),
        })

    aggregated_by_store.sort(key=lambda x: x["lowest_price"])

    representative_name = max(rows, key=lambda x: len(x["name"]))["name"]
    return {
        "representative_product_name": representative_name,
        "source_count": len(by_store),
        "result_count": len(rows),
        "lowest_price": _to_public_row(lowest),
        "highest_price": _to_public_row(highest),
        "lowest_total_cost": _to_public_row(lowest_total),
        "highest_total_cost": _to_public_row(highest_total),
        "average_price": round(sum(prices) / len(prices), 2),
        "average_total_cost": round(sum(total_costs) / len(total_costs), 2),
        "median_price": round(median(prices), 2),
        "median_total_cost": round(median(total_costs), 2),
        "price_range": round(max(prices) - min(prices), 2),
        "total_cost_range": round(max(total_costs) - min(total_costs), 2),
        "aggregated_by_store": aggregated_by_store,
        "best_value_listing": _to_public_row(rows[0]),
        "all_results": [_to_public_row(row) for row in rows],
    }


def compare_prices(products, filters=None):
    normalized_rows = _to_normalized_rows(products, filters=filters)
    if not normalized_rows:
        return {"message": "No products found", "all_results": []}

    clusters = _cluster_by_name_similarity(normalized_rows)
    best_cluster = max(clusters, key=_cluster_score)
    best_rows = best_cluster["items"]
    ignored_count = max(0, len(normalized_rows) - len(best_rows))

    # If matching is too strict and collapses to one row, keep broader results
    # so the UI can still show multiple store offers.
    if len(best_rows) <= 1 and len(normalized_rows) > 1:
        best_rows = normalized_rows
        ignored_count = 0

    filtered_rows = _apply_filters(best_rows, filters=filters)
    if not filtered_rows:
        return {
            "message": "No products found after applying filters",
            "all_results": [],
            "cluster_count": len(clusters),
            "ignored_outlier_count": ignored_count,
            "pre_filter_result_count": len(best_rows),
            "filtered_out_count": len(best_rows),
            "applied_filters": filters or {},
        }

    scored_rows, normalized_weights = _attach_scoring(
        filtered_rows,
        weights=(filters or {}).get("weights"),
    )
    summary = _summarize_rows(scored_rows)
    summary["cluster_count"] = len(clusters)
    summary["ignored_outlier_count"] = ignored_count
    summary["pre_filter_result_count"] = len(best_rows)
    summary["filtered_out_count"] = max(0, len(best_rows) - len(scored_rows))
    summary["scoring_weights"] = normalized_weights
    summary["applied_filters"] = filters or {}
    return summary
