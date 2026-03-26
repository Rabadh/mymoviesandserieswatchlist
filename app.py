import os
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "")

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/fetch-info", methods=["POST"])
def fetch_info():
    if not OMDB_API_KEY:
        return jsonify({"error": "OMDB_API_KEY not set"}), 500

    data = request.get_json()
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "No title provided"}), 400

    # Search OMDB by title
    resp = requests.get(
        "http://www.omdbapi.com/",
        params={"t": title, "apikey": OMDB_API_KEY},
        timeout=10,
    )

    if not resp.ok:
        return jsonify({"error": f"OMDB error {resp.status_code}"}), 502

    d = resp.json()

    if d.get("Response") == "False":
        # Try a search fallback (first result)
        search_resp = requests.get(
            "http://www.omdbapi.com/",
            params={"s": title, "apikey": OMDB_API_KEY},
            timeout=10,
        )
        search_data = search_resp.json()
        if search_data.get("Response") == "True" and search_data.get("Search"):
            imdb_id = search_data["Search"][0]["imdbID"]
            detail_resp = requests.get(
                "http://www.omdbapi.com/",
                params={"i": imdb_id, "apikey": OMDB_API_KEY},
                timeout=10,
            )
            d = detail_resp.json()
        else:
            return jsonify({"title": title, "found": False})

    # Parse rating
    rating = None
    raw_rating = d.get("imdbRating", "N/A")
    if raw_rating and raw_rating != "N/A":
        try:
            rating = float(raw_rating)
        except ValueError:
            pass

    # Parse runtime
    runtime = d.get("Runtime", "N/A")
    if runtime == "N/A":
        runtime = None

    # Parse genres
    genre_str = d.get("Genre", "")
    genres = [g.strip() for g in genre_str.split(",") if g.strip()][:2]

    # Determine type
    omdb_type = d.get("Type", "")
    total_seasons = d.get("totalSeasons")
    if omdb_type == "movie":
        media_type = "Movie"
    elif omdb_type == "series":
        media_type = "Series"
        if total_seasons and total_seasons != "N/A":
            runtime = f"{total_seasons} season{'s' if int(total_seasons) != 1 else ''}"
    elif omdb_type == "episode":
        media_type = "Series"
    else:
        media_type = "Series"

    # Anime / documentary override via genre
    if "Animation" in genres and omdb_type == "series":
        media_type = "Anime"
    if "Documentary" in genres:
        media_type = "Documentary"

    return jsonify({
        "title": title,
        "found": True,
        "rating": rating,
        "genres": genres,
        "runtime": runtime,
        "type": media_type,
        "year": d.get("Year", ""),
        "poster": d.get("Poster", "") if d.get("Poster") != "N/A" else "",
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
