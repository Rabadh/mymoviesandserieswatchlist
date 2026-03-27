import os
import requests
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
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

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

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({"error": "Unauthorized"}), 401

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

    user = User.query.filter_by(username=username).first()
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
        return jsonify(parse_omdb(d, title))
    except Exception as e:
        return jsonify({"title": title, "found": False, "error": str(e)})

@app.route("/api/search", methods=["POST"])
def search_omdb():
    if not OMDB_API_KEY:
        return jsonify([])
    data = request.get_json(force=True, silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify([])
    try:
        sd = omdb_get({"s": query})
        if sd.get("Response") != "True":
            return jsonify([])
        results = []
        for item in sd.get("Search", [])[:6]:
            poster = item.get("Poster", "")
            if poster == "N/A": poster = ""
            results.append({
                "title":  item.get("Title", ""),
                "year":   item.get("Year", ""),
                "type":   item.get("Type", "").capitalize(),
                "poster": poster,
            })
        return jsonify(results)
    except Exception:
        return jsonify([])

# ── Static pages ──────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return send_from_directory(app.static_folder, "auth.html")

@app.route("/app")
def main_app():
    return send_from_directory(app.static_folder, "index.html")

# ── Bootstrap DB & run ────────────────────────────────────────────────────────

with app.app_context():
    db.create_all()

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
