from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid
import json
import sqlite3
import tensorflow as tf
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeSerializer, BadSignature
from tensorflow.keras.applications.imagenet_utils import decode_predictions
from preprocessing import preprocess_for_efficientnet

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB
app.config["SECRET_KEY"] = "price-intelligence-secret"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
DB_PATH = "app.db"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
TARGET_SIZE = (224, 224)
model = tf.keras.applications.EfficientNetB0(weights="imagenet")
token_serializer = URLSafeSerializer(app.config["SECRET_KEY"], salt="auth-token")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            predictions_json TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.commit()
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


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(_err):
    return jsonify({"status": "error", "error": "File too large. Max size is 10MB."}), 413


@app.route("/")
def home():
    return "Backend Running"


@app.route("/api/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if len(username) < 3 or len(password) < 6:
        return jsonify({
            "status": "error",
            "error": "Username must be at least 3 chars and password at least 6 chars"
        }), 400

    password_hash = generate_password_hash(password)

    try:
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "error": "Username already exists"}), 409

    return jsonify({
        "status": "success",
        "user": {"id": user_id, "username": username},
        "token": create_token(user_id),
    }), 201


@app.route("/api/auth/signin", methods=["POST"])
def signin():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    conn = get_db()
    user = conn.execute(
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"status": "error", "error": "Invalid username or password"}), 401

    return jsonify({
        "status": "success",
        "user": {"id": user["id"], "username": user["username"]},
        "token": create_token(user["id"]),
    }), 200


@app.route("/api/my-images", methods=["GET"])
def my_images():
    user_id, error_response = require_user()
    if error_response:
        return error_response

    conn = get_db()
    rows = conn.execute(
        """
        SELECT image_id, filename, predictions_json, uploaded_at
        FROM uploads
        WHERE user_id = ?
        ORDER BY uploaded_at DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()

    images = []
    for row in rows:
        images.append({
            "image_id": row["image_id"],
            "filename": row["filename"],
            "image_url": f"http://127.0.0.1:5000/api/uploads/{row['filename']}",
            "predictions": json.loads(row["predictions_json"]),
            "uploaded_at": row["uploaded_at"],
        })

    return jsonify({"status": "success", "images": images}), 200


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
        conn.execute(
            """
            INSERT INTO uploads (image_id, user_id, filename, predictions_json)
            VALUES (?, ?, ?, ?)
            """,
            (image_id, user_id, filename, json.dumps(results)),
        )
        conn.commit()
        conn.close()
    except Exception:
        return jsonify({"status": "error", "error": "Failed to save upload metadata"}), 500

    return jsonify({
        "status": "success",
        "image_id": image_id,
        "image_url": f"http://127.0.0.1:5000/api/uploads/{filename}",
        "predictions": results
    }), 201



init_db()


if __name__ == "__main__":
    app.run(debug=True)
