import os
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/fetch-info", methods=["POST"])
def fetch_info():
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    data = request.get_json()
    titles = data.get("titles", [])
    if not titles:
        return jsonify({"error": "No titles provided"}), 400

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 2000,
        "system": (
            "You are a film and TV database. The user will send a list of titles. "
            "Return ONLY a raw JSON array — no markdown, no backticks, no commentary. "
            'Each element: {"title":<exact title string>,"rating":<number|null>,'
            '"genres":[<up to 2 strings>],"runtime":<string|null>,'
            '"type":<"Movie"|"Series"|"Mini-Series"|"Anime"|"Documentary"|"Reality">} '
            'runtime: "Xh Ym" for movies, "N seasons" for shows. '
            "Use your knowledge; if rating unknown use null."
        ),
        "messages": [{"role": "user", "content": "\n".join(titles)}],
    }

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        json=payload,
        timeout=60,
    )

    if not resp.ok:
        return jsonify({"error": resp.text}), resp.status_code

    result = resp.json()
    raw = "".join(c.get("text", "") for c in result.get("content", []))
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        import json
        parsed = json.loads(clean)
        return jsonify(parsed)
    except Exception as e:
        return jsonify({"error": f"JSON parse error: {e}", "raw": clean}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
