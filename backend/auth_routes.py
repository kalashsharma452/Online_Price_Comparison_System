import jwt
import psycopg2
from flask import g, jsonify, request


def register_auth_routes(app, deps):
    get_db = lambda: deps["get_db"]()
    auth_required = deps["auth_required"]
    _validate_required_email = lambda *args, **kwargs: deps["_validate_required_email"](*args, **kwargs)
    _validate_optional_text = lambda *args, **kwargs: deps["_validate_optional_text"](*args, **kwargs)
    _hash_password = lambda *args, **kwargs: deps["_hash_password"](*args, **kwargs)
    _build_public_user_payload = lambda *args, **kwargs: deps["_build_public_user_payload"](*args, **kwargs)
    create_token = lambda *args, **kwargs: deps["create_token"](*args, **kwargs)
    _check_password = lambda *args, **kwargs: deps["_check_password"](*args, **kwargs)
    _is_bcrypt_hash = lambda *args, **kwargs: deps["_is_bcrypt_hash"](*args, **kwargs)
    _create_password_reset_token = lambda *args, **kwargs: deps["_create_password_reset_token"](*args, **kwargs)
    _send_password_reset_email = lambda *args, **kwargs: deps["_send_password_reset_email"](*args, **kwargs)
    _decode_password_reset_token = lambda *args, **kwargs: deps["_decode_password_reset_token"](*args, **kwargs)
    _sanitize_text = lambda *args, **kwargs: deps["_sanitize_text"](*args, **kwargs)
    USERNAME_PATTERN = deps["USERNAME_PATTERN"]
    JWT_EXPIRY_SECONDS = deps["JWT_EXPIRY_SECONDS"]

    @app.route("/api/auth/signup", methods=["POST"])
    def signup():
        data = request.get_json(silent=True) or {}
        username = _sanitize_text(data.get("username"), max_len=64)
        email = _sanitize_text(data.get("email"), max_len=320).lower()
        password = data.get("password") or ""
        confirm_password = data.get("confirm_password") or ""
        phone = _sanitize_text(data.get("phone"), max_len=30)
        postal_code = _sanitize_text(data.get("postal_code"), max_len=12)

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
        email, email_err = _validate_required_email(email, "email")
        if email_err:
            return jsonify({"status": "error", "error": email_err}), 400
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

        password_hash = _hash_password(password)

        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (username, email, phone, postal_code, password_hash)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, username, email, phone, postal_code, created_at
                """,
                (username, email, phone, postal_code, password_hash),
            )
            created_user = cursor.fetchone()
            conn.commit()
        except psycopg2.IntegrityError:
            if conn:
                conn.rollback()
            return jsonify({"status": "error", "error": "Username or email already exists"}), 409
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

        return jsonify({
            "status": "success",
            "user": _build_public_user_payload(created_user),
            "token": create_token(created_user["id"]),
            "token_type": "Bearer",
            "expires_in": JWT_EXPIRY_SECONDS,
        }), 201

    @app.route("/api/auth/signin", methods=["POST"])
    def signin():
        data = request.get_json(silent=True) or {}
        username = _sanitize_text(data.get("username"), max_len=320)
        password = data.get("password") or ""

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, email, phone, postal_code, password_hash, created_at
            FROM users
            WHERE username = %s OR LOWER(email) = LOWER(%s)
            """,
            (username, username),
        )
        user = cursor.fetchone()
        password_matches = bool(user and _check_password(password, user["password_hash"]))
        if not password_matches:
            cursor.close()
            conn.close()
            return jsonify({"status": "error", "error": "Invalid username or password"}), 401

        if user and not _is_bcrypt_hash(user["password_hash"]):
            try:
                cursor.execute(
                    """
                    UPDATE users
                    SET password_hash = %s
                    WHERE id = %s
                    """,
                    (_hash_password(password), user["id"]),
                )
                conn.commit()
                user["password_hash"] = "[bcrypt-upgraded]"
            except Exception:
                conn.rollback()

        cursor.close()
        conn.close()

        return jsonify({
            "status": "success",
            "user": _build_public_user_payload(user),
            "token": create_token(user["id"]),
            "token_type": "Bearer",
            "expires_in": JWT_EXPIRY_SECONDS,
        }), 200

    @app.route("/api/auth/me", methods=["GET"])
    @auth_required
    def auth_me():
        user_id = g.user_id

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
            row = cursor.fetchone()
            if not row:
                return jsonify({"status": "error", "error": "User not found"}), 404
            return jsonify({"status": "success", "user": _build_public_user_payload(row)}), 200
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/profile", methods=["PUT"])
    @auth_required
    def update_profile():
        user_id = g.user_id

        data = request.get_json(silent=True) or {}
        updates = []
        params = []

        if "phone" in data:
            phone, err = _validate_optional_text(data.get("phone"), "phone", max_len=30)
            if err:
                return jsonify({"status": "error", "error": err}), 400
            phone_digits = "".join(ch for ch in (phone or "") if ch.isdigit())
            if phone is not None and phone_digits and (len(phone_digits) < 7 or len(phone_digits) > 15):
                return jsonify({"status": "error", "error": "Phone number must contain 7 to 15 digits"}), 400
            updates.append("phone = %s")
            params.append(phone)

        if "email" in data:
            email, err = _validate_required_email((data.get("email") or "").strip().lower(), "email")
            if err:
                return jsonify({"status": "error", "error": err}), 400
            updates.append("email = %s")
            params.append(email)

        if "postal_code" in data:
            postal_code, err = _validate_optional_text(data.get("postal_code"), "postal_code", max_len=12)
            if err:
                return jsonify({"status": "error", "error": err}), 400
            if postal_code is not None and postal_code and (len(postal_code) < 3 or len(postal_code) > 12):
                return jsonify({"status": "error", "error": "Postal code must be between 3 and 12 characters"}), 400
            updates.append("postal_code = %s")
            params.append(postal_code)

        if not updates:
            return jsonify({"status": "error", "error": "No valid fields provided to update"}), 400

        params.append(user_id)
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"""
                UPDATE users
                SET {", ".join(updates)}
                WHERE id = %s
                RETURNING id, username, email, phone, postal_code, created_at
                """,
                tuple(params),
            )
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return jsonify({"status": "error", "error": "User not found"}), 404
            conn.commit()
            return jsonify({"status": "success", "user": _build_public_user_payload(row)}), 200
        except psycopg2.IntegrityError:
            conn.rollback()
            return jsonify({"status": "error", "error": "Email already exists"}), 409
        finally:
            cursor.close()
            conn.close()

    @app.route("/api/auth/forgot-password", methods=["POST"])
    def forgot_password():
        data = request.get_json(silent=True) or {}
        email, err = _validate_required_email(_sanitize_text(data.get("email"), max_len=320).lower(), "email")
        if err:
            return jsonify({"status": "error", "error": err}), 400

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, username, email
                FROM users
                WHERE LOWER(email) = LOWER(%s)
                """,
                (email,),
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

        if not row:
            return jsonify({
                "status": "success",
                "message": "If an account exists for that email, a reset link has been sent.",
                "email_delivery": "not_applicable",
            }), 200

        token = _create_password_reset_token(row["id"], row["email"])
        delivery_status = _send_password_reset_email(row["email"], token)
        return jsonify({
            "status": "success",
            "message": "If an account exists for that email, a reset link has been sent.",
            "email_delivery": delivery_status,
            "reset_token_preview": token if delivery_status in {"email_not_configured", "email_failed"} else None,
        }), 200

    @app.route("/api/auth/reset-password", methods=["POST"])
    def reset_password():
        data = request.get_json(silent=True) or {}
        token = (data.get("token") or "").strip()
        password = data.get("password") or ""
        confirm_password = data.get("confirm_password") or ""

        if not token:
            return jsonify({"status": "error", "error": "token is required"}), 400
        if len(password) < 6:
            return jsonify({"status": "error", "error": "Password must be at least 6 characters"}), 400
        if password != confirm_password:
            return jsonify({"status": "error", "error": "Password and confirm password do not match"}), 400

        try:
            payload = _decode_password_reset_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"status": "error", "error": "Reset token has expired"}), 400
        except jwt.InvalidTokenError:
            return jsonify({"status": "error", "error": "Invalid reset token"}), 400

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE users
                SET password_hash = %s
                WHERE id = %s AND LOWER(email) = LOWER(%s)
                RETURNING id
                """,
                (_hash_password(password), int(payload["user_id"]), payload.get("email")),
            )
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return jsonify({"status": "error", "error": "User not found"}), 404
            conn.commit()
            return jsonify({"status": "success", "message": "Password reset successful"}), 200
        finally:
            cursor.close()
            conn.close()
