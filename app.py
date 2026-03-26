import os
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "")


def omdb_get(params):
    params["apikey"] = OMDB_API_KEY
    r = requests.get("http://www.omdbapi.com/", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def parse_detail(d, original_title=None):
    rating = None
    raw = d.get("imdbRating", "N/A")
    if raw and raw != "N/A":
        try:
            rating = float(raw)
        except ValueError:
            pass

    runtime = d.get("Runtime", "N/A")
    runtime = None if runtime == "N/A" else runtime

    genres = [g.strip() for g in d.get("Genre", "").split(",") if g.strip()][:2]

    omdb_type = d.get("Type", "")
    total_seasons = d.get("totalSeasons")
    if omdb_type == "movie":
        media_type = "Movie"
    elif omdb_type in ("series", "episode"):
        media_type = "Series"
        if total_seasons and total_seasons != "N/A":
            try:
                n = int(total_seasons)
                runtime = f"{n} season{'s' if n != 1 else ''}"
            except ValueError:
                pass
    else:
        media_type = "Series"

    if "Animation" in genres and omdb_type == "series":
        media_type = "Anime"
    if "Documentary" in genres:
        media_type = "Documentary"

    plot = d.get("Plot", "")
    if plot == "N/A":
        plot = ""

    poster = d.get("Poster", "")
    if poster == "N/A":
        poster = ""

    return {
        "title": d.get("Title", original_title or ""),
        "found": True,
        "rating": rating,
        "genres": genres,
        "runtime": runtime,
        "type": media_type,
        "year": d.get("Year", ""),
        "poster": poster,
        "plot": plot,
    }


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

    d = omdb_get({"t": title, "plot": "short"})

    if d.get("Response") == "False":
        sd = omdb_get({"s": title})
        if sd.get("Response") == "True" and sd.get("Search"):
            imdb_id = sd["Search"][0]["imdbID"]
            d = omdb_get({"i": imdb_id, "plot": "short"})
        else:
            return jsonify({"title": title, "found": False})

    return jsonify(parse_detail(d, title))


@app.route("/api/search", methods=["POST"])
def search():
    if not OMDB_API_KEY:
        return jsonify([]), 500

    data = request.get_json()
    query = data.get("query", "").strip()
    if not query:
        return jsonify([])

    sd = omdb_get({"s": query})
    if sd.get("Response") != "True":
        return jsonify([])

    results = []
    for item in sd.get("Search", [])[:5]:
        poster = item.get("Poster", "")
        if poster == "N/A":
            poster = ""
        results.append({
            "title": item.get("Title", ""),
            "year": item.get("Year", ""),
            "type": item.get("Type", "").capitalize(),
            "poster": poster,
            "imdbID": item.get("imdbID", ""),
        })

    return jsonify(results)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
