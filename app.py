import os
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "")


def safe_request(params):
    try:
        resp = requests.get(
            "http://www.omdbapi.com/",
            params=params,
            timeout=10,
        )
        if not resp.ok:
            return None, f"OMDB error {resp.status_code}"
        return resp.json(), None
    except requests.exceptions.RequestException:
        return None, "OMDB request failed"

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/fetch-info", methods=["POST"])
def fetch_info():
    if not OMDB_API_KEY:
        return jsonify({"error": "OMDB_API_KEY not set"}), 500

    data = request.get_json() or {}
    title = data.get("title", "").strip()

    if not title:
        return jsonify({"error": "No title provided"}), 400

    # Primary lookup
    d, err = safe_request({"t": title, "apikey": OMDB_API_KEY})
    if err:
        return jsonify({"error": err}), 502

    # Fallback search
    if d.get("Response") == "False":
        search_data, err = safe_request({"s": title, "apikey": OMDB_API_KEY})
        if err:
            return jsonify({"error": err}), 502

        if search_data.get("Response") == "True" and search_data.get("Search"):
            imdb_id = search_data["Search"][0].get("imdbID")

            if imdb_id:
                d, err = safe_request({"i": imdb_id, "apikey": OMDB_API_KEY})
                if err:
                    return jsonify({"error": err}), 502
            else:
                return jsonify({"title": title, "found": False})
        else:
            return jsonify({"title": title, "found": False})

    # Rating
    rating = None
    raw_rating = d.get("imdbRating")
    if raw_rating and raw_rating != "N/A":
        try:
            rating = float(raw_rating)
        except (ValueError, TypeError):
            rating = None

    # Runtime
    runtime = d.get("Runtime")
    if not runtime or runtime == "N/A":
        runtime = None

    # Genres
    genre_str = d.get("Genre", "")
    all_genres = [g.strip() for g in genre_str.split(",") if g.strip()]
    genres = all_genres[:2]
    lower_genres = [g.lower() for g in all_genres]

    # Type
    omdb_type = d.get("Type", "")
    total_seasons = d.get("totalSeasons")

    if omdb_type == "movie":
        media_type = "Movie"

    elif omdb_type == "series":
        media_type = "Series"

        if total_seasons and total_seasons != "N/A":
            try:
                seasons = int(total_seasons)
                runtime = f"{seasons} season{'s' if seasons != 1 else ''}"
            except (ValueError, TypeError):
                pass

    elif omdb_type == "episode":
        media_type = "Series"

    else:
        media_type = "Series"

    # Overrides
    if "animation" in lower_genres and omdb_type == "series":
        media_type = "Anime"

    if "documentary" in lower_genres:
        media_type = "Documentary"

    # Poster
    poster = d.get("Poster")
    if not poster or poster == "N/A":
        poster = ""

    return jsonify({
        "title": d.get("Title", title),
        "found": True,
        "rating": rating,
        "genres": genres,
        "runtime": runtime,
        "type": media_type,
        "year": d.get("Year", ""),
        "poster": poster,
    })


# ❗ Do NOT run Flask server in production
# Gunicorn will handle it
