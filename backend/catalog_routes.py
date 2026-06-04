from flask import jsonify, request


def register_catalog_routes(app, deps):
    get_db = lambda: deps["get_db"]()
    _validate_non_empty_text = lambda *args, **kwargs: deps["_validate_non_empty_text"](*args, **kwargs)
    _validate_optional_text = lambda *args, **kwargs: deps["_validate_optional_text"](*args, **kwargs)
    _validate_optional_url = lambda *args, **kwargs: deps["_validate_optional_url"](*args, **kwargs)
    _validate_required_url = lambda *args, **kwargs: deps["_validate_required_url"](*args, **kwargs)
    _validate_positive_int = lambda *args, **kwargs: deps["_validate_positive_int"](*args, **kwargs)
    _validate_non_negative_price = lambda *args, **kwargs: deps["_validate_non_negative_price"](*args, **kwargs)
    _parse_timestamp = lambda *args, **kwargs: deps["_parse_timestamp"](*args, **kwargs)
    _convert_datetimes_to_ist = lambda *args, **kwargs: deps["_convert_datetimes_to_ist"](*args, **kwargs)
    _parse_limit_offset = lambda *args, **kwargs: deps["_parse_limit_offset"](*args, **kwargs)
    _parse_page_per_page = lambda *args, **kwargs: deps["_parse_page_per_page"](*args, **kwargs)
    _build_trend_points = lambda *args, **kwargs: deps["_build_trend_points"](*args, **kwargs)
    _is_relevant_result = lambda *args, **kwargs: deps["_is_relevant_result"](*args, **kwargs)
    _evaluate_price_alerts = lambda *args, **kwargs: deps["_evaluate_price_alerts"](*args, **kwargs)
    _bump_cache_version = lambda *args, **kwargs: deps["_bump_cache_version"](*args, **kwargs)
    _user_cache_scope = lambda *args, **kwargs: deps["_user_cache_scope"](*args, **kwargs)
    _sanitize_query_param = lambda *args, **kwargs: deps["_sanitize_query_param"](*args, **kwargs)

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
                INSERT INTO products (name, category, image_url, brand, source_query, details_json)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING product_id, name, category, image_url, brand, source_query, details_json
                """,
                (name, category, image_url, None, None, None),
            )
            row = cursor.fetchone()
            conn.commit()
            return jsonify({"status": "success", "product": row}), 201
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/products", methods=["GET"])
    def list_products():
        name = _sanitize_query_param(request.args.get("name"), max_len=255)
        category = _sanitize_query_param(request.args.get("category"), max_len=120)
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
            SELECT product_id, name, category, image_url, brand, source_query, details_json
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
                SELECT product_id, name, category, image_url, brand, source_query, details_json
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
            RETURNING product_id, name, category, image_url, brand, source_query, details_json
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
                    INSERT INTO prices (
                        product_id, store_name, price, product_url, availability, seller_rating,
                        currency, original_price, original_currency, source_query, details_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING
                        price_id, product_id, store_name, price, timestamp, product_url,
                        availability, seller_rating, currency, original_price, original_currency,
                        source_query, details_json
                    """,
                    (product_id, store_name, price_value, product_url, None, None, "INR", price_value, "INR", None, None),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO prices (
                        product_id, store_name, price, timestamp, product_url, availability, seller_rating,
                        currency, original_price, original_currency, source_query, details_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING
                        price_id, product_id, store_name, price, timestamp, product_url,
                        availability, seller_rating, currency, original_price, original_currency,
                        source_query, details_json
                    """,
                    (
                        product_id, store_name, price_value, timestamp_value, product_url,
                        None, None, "INR", price_value, "INR", None, None,
                    ),
                )
            row = cursor.fetchone()
            _evaluate_price_alerts(conn)
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
            SELECT
                price_id, product_id, store_name, price, timestamp, product_url,
                availability, seller_rating, currency, original_price, original_currency,
                source_query, details_json
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
                SELECT product_id, name, category, image_url, brand, source_query, details_json
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
                SELECT
                    price_id, product_id, store_name, price, timestamp, product_url,
                    availability, seller_rating, currency, original_price, original_currency,
                    source_query, details_json
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

    @app.route("/api/price-trends", methods=["GET"])
    def price_trends_api():
        query = _sanitize_query_param(request.args.get("query"), max_len=255)
        if not query:
            return jsonify({"status": "error", "error": "Missing required query param: query"}), 400

        limit_days_raw = (request.args.get("days") or "").strip()
        try:
            limit_days = min(max(int(limit_days_raw or 30), 1), 180)
        except ValueError:
            return jsonify({"status": "error", "error": "days must be an integer"}), 400

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    pr.price_id,
                    pr.product_id,
                    pr.store_name,
                    pr.price,
                    pr.timestamp,
                    pr.product_url,
                    pr.availability,
                    pr.seller_rating,
                    pr.currency,
                    pr.original_price,
                    pr.original_currency,
                    pr.source_query,
                    pr.details_json,
                    p.name,
                    p.category,
                    p.image_url,
                    p.brand,
                    p.details_json AS product_details_json
                FROM prices pr
                JOIN products p ON p.product_id = pr.product_id
                WHERE pr.timestamp >= (CURRENT_TIMESTAMP - (%s || ' days')::interval)
                ORDER BY pr.timestamp ASC, pr.price_id ASC
                """,
                (limit_days,),
            )
            matched_rows = [row for row in cursor.fetchall() if _is_relevant_result(row, query)]
        finally:
            cursor.close()
            conn.close()

        if not matched_rows:
            return jsonify({"status": "success", "query": query, "count": 0, "trend_points": [], "stores": []}), 200

        overall_points = _build_trend_points(matched_rows)
        store_map = {}
        for row in matched_rows:
            store_name = row.get("store_name") or "Store"
            store_map.setdefault(store_name, []).append(row)

        stores = []
        for store_name, rows in sorted(store_map.items(), key=lambda item: item[0].lower()):
            prices = [float(row["price"]) for row in rows if row.get("price") is not None]
            stores.append({
                "store_name": store_name,
                "count": len(rows),
                "min_price": round(min(prices), 2) if prices else None,
                "max_price": round(max(prices), 2) if prices else None,
                "points": _convert_datetimes_to_ist(_build_trend_points(rows)),
            })

        all_prices = [float(row["price"]) for row in matched_rows if row.get("price") is not None]
        return jsonify(_convert_datetimes_to_ist({
            "status": "success",
            "query": query,
            "count": len(matched_rows),
            "days": limit_days,
            "min_price": round(min(all_prices), 2) if all_prices else None,
            "max_price": round(max(all_prices), 2) if all_prices else None,
            "average_price": round(sum(all_prices) / len(all_prices), 2) if all_prices else None,
            "trend_points": overall_points,
            "stores": stores,
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
            _evaluate_price_alerts(conn)
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
            _bump_cache_version(_user_cache_scope(user_id))
            _bump_cache_version("popular_searches")
            return jsonify(_convert_datetimes_to_ist({"status": "success", "search_history": row})), 201
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/search-history", methods=["GET"])
    def list_search_history():
        limit, offset = _parse_limit_offset()
        user_id_raw = (request.args.get("user_id") or "").strip()
        query_filter = _sanitize_query_param(request.args.get("query"), max_len=255)

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
            _bump_cache_version(_user_cache_scope(row["user_id"]))
            _bump_cache_version("popular_searches")
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
                "DELETE FROM search_history WHERE search_id = %s RETURNING search_id, user_id",
                (search_id,),
            )
            deleted = cursor.fetchone()
            if not deleted:
                conn.rollback()
                return jsonify({"status": "error", "error": "Search history entry not found"}), 404
            conn.commit()
            if deleted.get("user_id"):
                _bump_cache_version(_user_cache_scope(deleted["user_id"]))
            _bump_cache_version("popular_searches")
            return jsonify({"status": "success", "deleted_search_id": deleted["search_id"]}), 200
        finally:
            cursor.close()
            conn.close()
