import os
import re
import time
import random
import difflib
import requests
from collections import Counter
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__, static_folder="static")

# ── Config ──────────────────────────────────────────────────────────────────

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

db_url = os.environ.get("DATABASE_URL", "sqlite:///watchlist.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
# Remove sslmode from URL if present — we set it via connect_args instead
if "?sslmode=" in db_url:
    db_url = db_url.split("?sslmode=")[0]

app.config["SQLALCHEMY_DATABASE_URI"] = db_url

if "postgresql" in db_url:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": {"sslmode": "require"}
    }
else:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

# Detect production (Render sets the RENDER env var automatically)
IS_PROD = bool(os.environ.get("RENDER"))

app.config["SESSION_COOKIE_NAME"]     = "wl_session"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"]   = IS_PROD   # True on Render (HTTPS), False locally
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SECURE"]   = IS_PROD
app.config["REMEMBER_COOKIE_DURATION"] = 60 * 60 * 24 * 30  # 30 days

CORS(app, supports_credentials=True, origins="*")

db           = SQLAlchemy(app)
bcrypt       = Bcrypt(app)
login_manager = LoginManager(app)

OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_BASE    = "https://api.themoviedb.org/3"
TMDB_IMG     = "https://image.tmdb.org/t/p/w342"

# ── Models ───────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    profiles = db.relationship("Profile", backref="user", cascade="all, delete-orphan")
    created  = db.Column(db.DateTime, default=datetime.utcnow)

class Profile(db.Model):
    __tablename__ = "profiles"
    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name    = db.Column(db.String(80), nullable=False)
    entries = db.relationship("Entry", backref="profile", cascade="all, delete-orphan")
    created = db.Column(db.DateTime, default=datetime.utcnow)

class Entry(db.Model):
    __tablename__ = "entries"
    id          = db.Column(db.Integer, primary_key=True)
    profile_id  = db.Column(db.Integer, db.ForeignKey("profiles.id"), nullable=False)
    title       = db.Column(db.String(200), nullable=False)
    watched     = db.Column(db.Boolean, default=False)
    media_type  = db.Column(db.String(30))
    genres      = db.Column(db.String(200))
    runtime     = db.Column(db.String(50))
    rating      = db.Column(db.Float)
    year        = db.Column(db.String(10))
    poster      = db.Column(db.String(500))
    plot        = db.Column(db.Text)
    custom_desc = db.Column(db.Text)
    added       = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":          self.id,
            "title":       self.title,
            "watched":     self.watched,
            "type":        self.media_type,
            "genres":      self.genres.split(",") if self.genres else [],
            "runtime":     self.runtime,
            "rating":      self.rating,
            "year":        self.year,
            "poster":      self.poster or "",
            "plot":        self.plot or "",
            "custom_desc": self.custom_desc or "",
        }

class TitleCache(db.Model):
    """Every title OMDb has ever returned to this app, across all users.
    Grows organically with usage. Powers typo-correction and doubles as the
    genre-tagged pool that recommendations are drawn from."""
    __tablename__ = "title_cache"
    id         = db.Column(db.Integer, primary_key=True)
    imdb_id    = db.Column(db.String(20), unique=True)
    title      = db.Column(db.String(200), nullable=False)
    year       = db.Column(db.String(10))
    media_type = db.Column(db.String(30))
    genres     = db.Column(db.String(200))
    rating     = db.Column(db.Float)
    runtime    = db.Column(db.String(50))
    poster     = db.Column(db.String(500))
    plot       = db.Column(db.Text)
    source     = db.Column(db.String(20), default="omdb")   # omdb | seed | reddit
    updated    = db.Column(db.DateTime, default=datetime.utcnow)

def cache_title(parsed, imdb_id=None, source="omdb"):
    """Upsert a parsed OMDb result into the shared TitleCache."""
    if not parsed or not parsed.get("title"):
        return
    row = None
    if imdb_id:
        row = TitleCache.query.filter_by(imdb_id=imdb_id).first()
    if not row:
        row = TitleCache.query.filter_by(
            title=parsed["title"], year=parsed.get("year", "")
        ).first()
    if not row:
        row = TitleCache(imdb_id=imdb_id, source=source)
        db.session.add(row)
    row.title      = parsed.get("title", row.title if row.title else "")
    row.year       = parsed.get("year", row.year)
    row.media_type = parsed.get("type", row.media_type)
    row.genres     = ",".join(parsed.get("genres") or []) if isinstance(parsed.get("genres"), list) else (parsed.get("genres") or row.genres)
    row.rating     = parsed.get("rating", row.rating)
    row.runtime    = parsed.get("runtime", row.runtime)
    row.poster     = parsed.get("poster") or row.poster
    row.plot       = parsed.get("plot") or row.plot
    row.updated    = datetime.utcnow()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

def fuzzy_correct(query, cutoff=0.72):
    """Look for a close-spelling match against every title we've ever seen."""
    all_titles = [t[0] for t in db.session.query(TitleCache.title).distinct()]
    if not all_titles:
        return None
    matches = difflib.get_close_matches(query, all_titles, n=1, cutoff=cutoff)
    return matches[0] if matches else None

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({"error": "Unauthorized"}), 401

@app.errorhandler(Exception)
def handle_any_error(e):
    # Make sure the client always gets JSON back, even on unexpected crashes,
    # and log the real traceback so we can see what actually failed.
    import traceback
    traceback.print_exc()
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    return jsonify({"error": str(e) or "Internal server error"}), code

# ── Debug ─────────────────────────────────────────────────────────────────────

@app.route("/api/ping")
def ping():
    """Health check — visit /api/ping to confirm the server is running."""
    return jsonify({"ok": True, "db": db_url.split("://")[0], "prod": IS_PROD})

# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/api/register", methods=["POST"])
def register():
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        return jsonify({"error": "Invalid request body"}), 400

    username = (data.get("username") or "").strip().lower()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters"}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already taken"}), 409

    try:
        hashed = bcrypt.generate_password_hash(password).decode("utf-8")
        user = User(username=username, password=hashed)
        db.session.add(user)
        db.session.flush()

        default_profile = Profile(user_id=user.id, name=username.capitalize() + "'s List")
        db.session.add(default_profile)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    login_user(user, remember=True)
    return jsonify({
        "ok": True,
        "username": user.username,
        "profiles": [{"id": default_profile.id, "name": default_profile.name}]
    })

@app.route("/api/login", methods=["POST"])
def login():
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        return jsonify({"error": "Invalid request body"}), 400

    username = (data.get("username") or "").strip().lower()
    password = data.get("password", "")

    try:
        user = User.query.filter_by(username=username).first()
    except Exception as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    if not user or not bcrypt.check_password_hash(user.password, password):
        return jsonify({"error": "Invalid username or password"}), 401

    login_user(user, remember=True)
    profiles = [{"id": p.id, "name": p.name} for p in user.profiles]
    return jsonify({"ok": True, "username": user.username, "profiles": profiles})

@app.route("/api/logout", methods=["POST"])
def logout():
    logout_user()
    return jsonify({"ok": True})

@app.route("/api/me")
def me():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False})
    profiles = [{"id": p.id, "name": p.name} for p in current_user.profiles]
    return jsonify({"authenticated": True, "username": current_user.username, "profiles": profiles})

# ── Profiles ──────────────────────────────────────────────────────────────────

@app.route("/api/profiles", methods=["GET"])
@login_required
def get_profiles():
    return jsonify([{"id": p.id, "name": p.name} for p in current_user.profiles])

@app.route("/api/profiles", methods=["POST"])
@login_required
def create_profile():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Profile name required"}), 400
    profile = Profile(user_id=current_user.id, name=name)
    db.session.add(profile)
    db.session.commit()
    return jsonify({"id": profile.id, "name": profile.name})

@app.route("/api/profiles/<int:pid>", methods=["DELETE"])
@login_required
def delete_profile(pid):
    profile = Profile.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    db.session.delete(profile)
    db.session.commit()
    return jsonify({"ok": True})

# ── Entries ───────────────────────────────────────────────────────────────────

@app.route("/api/profiles/<int:pid>/entries", methods=["GET"])
@login_required
def get_entries(pid):
    profile = Profile.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    return jsonify([e.to_dict() for e in profile.entries])

@app.route("/api/profiles/<int:pid>/entries", methods=["POST"])
@login_required
def add_entry(pid):
    profile = Profile.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title required"}), 400
    existing = Entry.query.filter_by(profile_id=pid, title=title).first()
    if existing:
        return jsonify({"error": "already_exists", "entry": existing.to_dict()}), 409
    entry = Entry(
        profile_id=pid, title=title,
        media_type=data.get("type"),
        genres=",".join(data.get("genres") or []),
        runtime=data.get("runtime"),
        rating=data.get("rating"),
        year=data.get("year"),
        poster=data.get("poster"),
        plot=data.get("plot"),
        custom_desc=data.get("custom_desc"),
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201

@app.route("/api/entries/<int:eid>", methods=["PATCH"])
@login_required
def update_entry(eid):
    entry = db.session.get(Entry, eid)
    if not entry:
        return jsonify({"error": "Not found"}), 404
    if entry.profile.user_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(force=True, silent=True) or {}
    if "watched"     in data: entry.watched     = data["watched"]
    if "title"       in data: entry.title       = data["title"]
    if "type"        in data: entry.media_type  = data["type"]
    if "genres"      in data: entry.genres      = ",".join(data["genres"] or [])
    if "runtime"     in data: entry.runtime     = data["runtime"]
    if "rating"      in data: entry.rating      = data["rating"]
    if "year"        in data: entry.year        = data["year"]
    if "poster"      in data: entry.poster      = data["poster"]
    if "plot"        in data: entry.plot        = data["plot"]
    if "custom_desc" in data: entry.custom_desc = data["custom_desc"]
    db.session.commit()
    return jsonify(entry.to_dict())

@app.route("/api/entries/<int:eid>", methods=["DELETE"])
@login_required
def delete_entry(eid):
    entry = db.session.get(Entry, eid)
    if not entry:
        return jsonify({"error": "Not found"}), 404
    if entry.profile.user_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    db.session.delete(entry)
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/entries/bulk-delete", methods=["POST"])
@login_required
def bulk_delete():
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids", [])
    deleted = 0
    for eid in ids:
        entry = db.session.get(Entry, eid)
        if entry and entry.profile.user_id == current_user.id:
            db.session.delete(entry)
            deleted += 1
    db.session.commit()
    return jsonify({"ok": True, "deleted": deleted})

# ── OMDB ──────────────────────────────────────────────────────────────────────

def omdb_get(params):
    params["apikey"] = OMDB_API_KEY
    r = requests.get("http://www.omdbapi.com/", params=params, timeout=10)
    r.raise_for_status()
    return r.json()

# ── TMDB ──────────────────────────────────────────────────────────────────────

_tmdb_genre_map = {}  # id -> name, movie + tv combined, loaded once and cached

def tmdb_get(path, params=None):
    params = params or {}
    params["api_key"] = TMDB_API_KEY
    r = requests.get(f"{TMDB_BASE}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()

def _load_tmdb_genres():
    if _tmdb_genre_map or not TMDB_API_KEY:
        return
    try:
        for kind in ("movie", "tv"):
            data = tmdb_get(f"/genre/{kind}/list")
            for g in data.get("genres", []):
                _tmdb_genre_map[g["id"]] = g["name"]
    except Exception:
        pass

def _tmdb_poster(path):
    return f"{TMDB_IMG}{path}" if path else ""

def tmdb_result_to_dict(item, media_type_hint=None):
    _load_tmdb_genres()
    mtype = media_type_hint or item.get("media_type")
    if mtype == "tv":
        media_type = "Series"
    elif mtype == "movie":
        media_type = "Movie"
    else:
        media_type = "Movie" if item.get("title") else "Series"
    title = item.get("title") or item.get("name") or ""
    date = item.get("release_date") or item.get("first_air_date") or ""
    year = date[:4] if date else ""
    genre_ids = item.get("genre_ids") or [g["id"] for g in item.get("genres", [])]
    genres = [_tmdb_genre_map.get(g) for g in genre_ids if _tmdb_genre_map.get(g)]
    return {
        "title": title,
        "year": year,
        "type": media_type,
        "tmdb_id": item.get("id"),
        "poster": _tmdb_poster(item.get("poster_path")),
        "plot": item.get("overview", ""),
        "rating": round(item.get("vote_average", 0), 1) if item.get("vote_average") else None,
        "genres": genres,
    }

def tmdb_search(query):
    """Typo-tolerant multi-search (movies + tv). This is what actually fixes
    'I have to Google the spelling first' — TMDb's search handles fuzziness
    far better than OMDb's substring match."""
    data = tmdb_get("/search/multi", {"query": query, "include_adult": "false"})
    out = []
    for item in data.get("results", []):
        if item.get("media_type") not in ("movie", "tv"):
            continue
        d = tmdb_result_to_dict(item)
        if d["title"]:
            out.append(d)
    return out

def parse_omdb(d, original_title=None):
    rating = None
    raw = d.get("imdbRating", "N/A")
    if raw and raw != "N/A":
        try: rating = float(raw)
        except ValueError: pass

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
            except ValueError: pass
    else:
        media_type = "Series"

    if "Animation" in genres and omdb_type == "series":
        media_type = "Anime"
    if "Documentary" in genres:
        media_type = "Documentary"

    plot   = d.get("Plot",   ""); plot   = "" if plot   == "N/A" else plot
    poster = d.get("Poster", ""); poster = "" if poster == "N/A" else poster

    return {
        "title":   d.get("Title", original_title or ""),
        "found":   True,
        "rating":  rating,
        "genres":  genres,
        "runtime": runtime,
        "type":    media_type,
        "year":    d.get("Year", ""),
        "poster":  poster,
        "plot":    plot,
    }

@app.route("/api/fetch-info", methods=["POST"])
def fetch_info():
    if not OMDB_API_KEY:
        return jsonify({"error": "OMDB_API_KEY not set"}), 500
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "No title"}), 400
    try:
        d = omdb_get({"t": title, "plot": "short"})
        if d.get("Response") == "False":
            sd = omdb_get({"s": title})
            if sd.get("Response") == "True" and sd.get("Search"):
                d = omdb_get({"i": sd["Search"][0]["imdbID"], "plot": "short"})
            else:
                return jsonify({"title": title, "found": False})
        parsed = parse_omdb(d, title)
        cache_title(parsed, imdb_id=d.get("imdbID"))
        return jsonify(parsed)
    except Exception as e:
        return jsonify({"title": title, "found": False, "error": str(e)})

def _omdb_search_raw(query):
    sd = omdb_get({"s": query})
    if sd.get("Response") != "True":
        return []
    out = []
    for item in sd.get("Search", []):
        poster = item.get("Poster", "")
        if poster == "N/A":
            poster = ""
        out.append({
            "title":   item.get("Title", ""),
            "year":    item.get("Year", ""),
            "type":    item.get("Type", "").capitalize(),
            "poster":  poster,
            "imdb_id": item.get("imdbID", ""),
        })
    return out

@app.route("/api/search", methods=["POST"])
def search_omdb():
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query or len(query) < 2:
        return jsonify([])

    # Primary: TMDb, which tolerates typos/partial spelling much better than
    # OMDb's substring match — this is what fixes "wrong spelling = no results".
    if TMDB_API_KEY:
        try:
            results = tmdb_search(query)[:8]
            for r in results:
                cache_title(r, imdb_id=None)
            if results:
                return jsonify(results)
        except Exception:
            pass  # fall through to OMDb path below

    if not OMDB_API_KEY:
        return jsonify([])

    try:
        results = _omdb_search_raw(query)

        # If the raw query found nothing (or very little), try a spelling
        # correction against every title this app has ever seen.
        if len(results) < 2:
            guess = fuzzy_correct(query)
            if guess and guess.lower() != query.lower():
                guess_results = _omdb_search_raw(guess)
                if guess_results:
                    seen = {(r["title"].lower(), r["year"]) for r in guess_results}
                    for r in results:
                        key = (r["title"].lower(), r["year"])
                        if key not in seen:
                            guess_results.append(r)
                            seen.add(key)
                    results = guess_results

        if not results and " " in query:
            trimmed = query.rsplit(" ", 1)[0]
            results = _omdb_search_raw(trimmed)

        results = results[:8]
        for r in results:
            cache_title(
                {"title": r["title"], "year": r["year"], "type": r["type"], "poster": r["poster"]},
                imdb_id=r.get("imdb_id"),
            )

        return jsonify(results)
    except Exception:
        return jsonify([])

# ── Recommendations ─────────────────────────────────────────────────────────
# Live TMDb data: trending (naturally refreshes as TMDb's own charts move) +
# discover-by-genre (built from each profile's watched-genre affinity). No
# static pool to maintain — this reflects what's actually out right now.

TMDB_GENRE_NAME_TO_ID = {}  # populated lazily, reverse of _tmdb_genre_map

def _genre_ids_for_names(names):
    if not TMDB_GENRE_NAME_TO_ID:
        _load_tmdb_genres()
        for gid, name in _tmdb_genre_map.items():
            TMDB_GENRE_NAME_TO_ID[name] = gid
    return [TMDB_GENRE_NAME_TO_ID[n] for n in names if n in TMDB_GENRE_NAME_TO_ID]

def _profile_affinity(profile):
    watched = [e for e in profile.entries if e.watched]
    genre_counts = Counter()
    type_counts = Counter()
    for e in watched:
        for g in (e.genres or "").split(","):
            g = g.strip()
            if g:
                genre_counts[g] += 1
        if e.media_type:
            type_counts[e.media_type] += 1
    return genre_counts, type_counts

def _tmdb_candidates(genre_counts, type_counts):
    """Pull a mixed bag from TMDb: trending (always fresh) + discover filtered
    to the profile's top genres (personalized), for both movies and tv."""
    candidates = {}

    def add_all(items, media_type_hint=None):
        for item in items:
            d = tmdb_result_to_dict(item, media_type_hint)
            if d["title"] and d.get("tmdb_id"):
                candidates.setdefault((d["type"], d["tmdb_id"]), d)

    try:
        trending = tmdb_get("/trending/all/week")
        add_all(trending.get("results", []))
    except Exception:
        pass

    top_genres = [g for g, _ in genre_counts.most_common(3)]
    genre_ids = _genre_ids_for_names(top_genres)
    wants_movies = type_counts.get("Movie", 0) >= type_counts.get("Series", 0)
    wants_series = type_counts.get("Series", 0) > 0

    if genre_ids:
        try:
            movie_disc = tmdb_get("/discover/movie", {
                "with_genres": ",".join(str(g) for g in genre_ids),
                "sort_by": "popularity.desc",
            })
            add_all(movie_disc.get("results", []), "movie")
        except Exception:
            pass
        if wants_series:
            try:
                tv_disc = tmdb_get("/discover/tv", {
                    "with_genres": ",".join(str(g) for g in genre_ids),
                    "sort_by": "popularity.desc",
                })
                add_all(tv_disc.get("results", []), "tv")
            except Exception:
                pass

    return list(candidates.values())

@app.route("/api/profiles/<int:pid>/recommendations", methods=["GET"])
@login_required
def get_recommendations(pid):
    profile = Profile.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    existing_titles = {e.title.strip().lower() for e in profile.entries}

    if not TMDB_API_KEY:
        return jsonify({"error": "TMDB_API_KEY not set"}), 500

    genre_counts, type_counts = _profile_affinity(profile)
    candidates = _tmdb_candidates(genre_counts, type_counts)

    day_seed = int(time.time() // 86400)  # stable within a day, shifts daily
    rng = random.Random(day_seed)

    scored = []
    for c in candidates:
        if c["title"].strip().lower() in existing_titles:
            continue
        score = sum(genre_counts.get(g, 0) for g in c["genres"])
        if type_counts.get(c["type"]):
            score += 1
        score += rng.random()
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [c for _, c in scored[:25]]

    def brief(plot):
        plot = plot or ""
        return plot if len(plot) <= 140 else plot[:137].rsplit(" ", 1)[0] + "…"

    return jsonify([{
        "title":  c["title"], "year": c["year"], "type": c["type"],
        "genres": c["genres"], "rating": c["rating"], "poster": c["poster"],
        "plot":   brief(c["plot"]), "tmdb_id": c["tmdb_id"],
    } for c in top])


# ── Reddit picks ──────────────────────────────────────────────────────────────

DEFAULT_SUBREDDITS = ["MovieSuggestions", "televisionsuggestions"]
_reddit_cache = {}  # subreddit key -> (timestamp, data)
REDDIT_CACHE_TTL = 3600

TITLE_PATTERNS = [
    re.compile(r'\*\*([A-Z][A-Za-z0-9:,\'\.\-\s]{2,60}?)\*\*'),       # **Bold Title**
    re.compile(r'"([A-Z][A-Za-z0-9:,\'\.\-\s]{2,60}?)"'),              # "Quoted Title"
    re.compile(r'\b([A-Z][A-Za-z0-9:,\'\.\-\s]{2,50}?)\s*\((19|20)\d{2}\)'),  # Title (Year)
]

def _extract_candidate_titles(text):
    found = set()
    for pat in TITLE_PATTERNS:
        for m in pat.finditer(text or ""):
            candidate = m.group(1).strip(" -:,'\".")
            if 2 <= len(candidate) <= 60:
                found.add(candidate)
    return found

def _fetch_reddit_json(url):
    headers = {"User-Agent": "watchlist-app/1.0 (recommendation feature)"}
    r = requests.get(url, headers=headers, timeout=8)
    r.raise_for_status()
    return r.json()

@app.route("/api/reddit-picks", methods=["GET"])
@login_required
def reddit_picks():
    subs = request.args.get("subreddits", "")
    subreddit_list = [s.strip() for s in subs.split(",") if s.strip()] or DEFAULT_SUBREDDITS
    cache_key = ",".join(sorted(subreddit_list)).lower()

    cached = _reddit_cache.get(cache_key)
    if cached and time.time() - cached[0] < REDDIT_CACHE_TTL:
        return jsonify(cached[1])

    candidates = {}  # title -> {source_sub, permalink}
    try:
        for sub in subreddit_list[:5]:
            listing = _fetch_reddit_json(f"https://www.reddit.com/r/{sub}/hot.json?limit=8")
            posts = listing.get("data", {}).get("children", [])
            for post in posts[:6]:
                pdata = post.get("data", {})
                permalink = "https://www.reddit.com" + pdata.get("permalink", "")
                # candidates from the post title itself
                for t in _extract_candidate_titles(pdata.get("title", "")):
                    candidates.setdefault(t, {"sub": sub, "permalink": permalink})
                # candidates from top comments
                try:
                    thread = _fetch_reddit_json(f"https://www.reddit.com{pdata.get('permalink','')}.json?limit=15")
                    comments = thread[1]["data"]["children"] if len(thread) > 1 else []
                    for c in comments[:15]:
                        body = c.get("data", {}).get("body", "")
                        for t in _extract_candidate_titles(body):
                            candidates.setdefault(t, {"sub": sub, "permalink": permalink})
                except Exception:
                    pass
    except Exception:
        pass

    # Verify each candidate is a real title before showing it — prefer TMDb
    # (better fuzzy match on the messy titles Reddit posts contain).
    verified = []
    for title, meta in list(candidates.items())[:20]:
        try:
            match = None
            if TMDB_API_KEY:
                hits = tmdb_search(title)
                if hits:
                    match = hits[0]
            if not match and OMDB_API_KEY:
                d = omdb_get({"t": title, "plot": "short"})
                if d.get("Response") != "False":
                    match = parse_omdb(d, title)
                    cache_title(match, imdb_id=d.get("imdbID"), source="reddit")
            if not match:
                continue
            if TMDB_API_KEY and match.get("tmdb_id"):
                cache_title(match, source="reddit")
            verified.append({
                "title":     match["title"],
                "year":      match["year"],
                "type":      match["type"],
                "poster":    match["poster"],
                "plot":      (match.get("plot") or "")[:140],
                "rating":    match.get("rating"),
                "subreddit": meta["sub"],
                "permalink": meta["permalink"],
            })
        except Exception:
            continue

    _reddit_cache[cache_key] = (time.time(), verified)
    return jsonify(verified)

# ── Static pages ──────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return send_from_directory(app.static_folder, "auth.html")

@app.route("/app")
def main_app():
    return send_from_directory(app.static_folder, "index.html")

# ── Bootstrap DB & run ────────────────────────────────────────────────────────
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        import traceback
        print("DB init warning:", e)
        traceback.print_exc()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
# ── Seed endpoint ─────────────────────────────────────────────────────────────

SEED_TITLES = [
    "100 Years of Solitude", "A House of Dynamite", "Amazon Jail",
    "Ascendence of a Bookworm", "Atlanta", "Band of Brothers",
    "Better Call Saul", "Black Mirror", "Caligula", "Castlevania",
    "Centerfold Girls", "Civil War", "Clarkson's Farm", "Dark Matter",
    "Deep Cover", "Demon Slayer", "Detectorists", "Devil May Cry", "Devs",
    "Dragon Keeper", "Extrapolations", "For All Mankind", "Frieren",
    "Full Metal Alchemist", "Gangubhai Kathiawadi", "Green Eggs and Ham",
    "Heeramandi", "He-Man", "Inu Yasha",
    "It's Always Sunny in Philadelphia", "Jujutsu Kaisen", "Justified",
    "Knight of the Seven Kingdoms", "Landman", "Lifeforce", "Mad Men",
    "Maid", "Masters of the Air", "Mindhunter", "MobLand", "Murderbot",
    "My Hero Academia", "Nobody Wants This", "Ozark",
    "Pride and Prejudice (1995 BBC)", "Re:Zero", "Rutherford Falls",
    "SAO (Sword Art Online)", "Shameless", "Shogun", "Slam Dunk",
    "Slow Horses", "Sons of Anarchy", "Spy x Family", "Squid Game",
    "Star Trek: The Next Generation", "Succession", "Supernatural",
    "The Bear", "The Day of the Jackal", "The Diplomat", "The Gentleman",
    "The Good Place", "The Night Off", "The Penguin", "The Sopranos",
    "The Traitors", "The Unbreakable Boy", "The West Wing",
    "The White Lotus", "The Wire", "Time Bandits",
    "True Detective (Season 1)", "Tulsa King", "Turn: Washington's Spies",
    "U Forgotten", "Under the Skin", "Until I Kill You", "Veep",
    "War on Rohirrim",
]

@app.route("/api/seed-my-list", methods=["GET", "POST"])
@login_required
def seed_my_list():
    profile = current_user.profiles[0] if current_user.profiles else None
    if not profile:
        profile = Profile(user_id=current_user.id, name=current_user.username.capitalize() + "'s List")
        db.session.add(profile)
        db.session.flush()

    added, skipped = [], []
    for title in SEED_TITLES:
        exists = Entry.query.filter_by(profile_id=profile.id, title=title).first()
        if exists:
            skipped.append(title)
        else:
            entry = Entry(profile_id=profile.id, title=title)
            db.session.add(entry)
            added.append(title)

    db.session.commit()

    rows = "".join(f"<li>{t}</li>" for t in added)
    return f"""<!DOCTYPE html>
<html><head><style>
  body{{font-family:sans-serif;background:#0d0d14;color:#e0ddd6;padding:40px;max-width:600px;}}
  h2{{color:#f5c518;margin-bottom:16px;}} .ok{{color:#4caf50;}} .sk{{color:#666;}}
  a{{color:#f5c518;font-weight:500;}} ul{{margin:10px 0 0;padding-left:20px;line-height:1.9;}}
  details{{margin-top:20px;}} summary{{cursor:pointer;color:#666;}}
</style></head>
<body>
  <h2>Import complete!</h2>
  <p class="ok">&#10003; {len(added)} titles added to <strong>{profile.name}</strong></p>
  <p class="sk">&#8212; {len(skipped)} already existed, skipped</p>
  <br><a href="/app">Go to my watchlist &rarr;</a>
  <details><summary>Show added titles ({len(added)})</summary><ul>{rows}</ul></details>
</body></html>""", 200
