import datetime
import json
import os

from flask import (
    Flask, flash, g, jsonify, redirect, render_template, request, url_for
)
from werkzeug.middleware.proxy_fix import ProxyFix
from firebase_admin import auth as fb_auth

import fitch_checker as checker
import fitch_generator as generator
import ch10_checker
import ch10_generator
import firestore_db as store

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


# --- chapters ---------------------------------------------------------------

# The chapters the site can generate for. Their rule sets, formula syntax and
# even their generators' call signatures differ, so everything chapter-specific
# is looked up here rather than branched on at each use.
CHAPTERS = {
    5: {
        "label": "Chapter 5 — propositional",
        "blurb": "Fitch proofs over the propositional connectives.",
        "checker": checker,
        "verify": lambda q: checker.check_proof(
            q["premises"], q["goal"], q["proof"]),
        # `saved` is a thunk: Chapter 5 dedupes within a single call and never
        # needs it, so asking for it would only cost a Firestore read.
        "make": lambda count, difficulty, saved: generator.generate(
            count=count, difficulty=difficulty),
    },
    10: {
        "label": "Chapter 10 — relational",
        "blurb": "The same eleven rules plus the quantifier rules: "
                 "Universal and Existential Introduction and Elimination, "
                 "and Domain Closure.",
        "checker": ch10_checker,
        "verify": lambda q: ch10_checker.check_proof(
            q["premises"], q["goal"], q["proof"], q.get("constants") or []),
        # Chapter 10 draws on a small stock of arguments, so it repeats itself
        # unless it is told what is already on file.
        "make": lambda count, difficulty, saved: ch10_generator.generate(
            count=count, difficulty=difficulty, existing=saved()),
    },
}

DEFAULT_CHAPTER = store.DEFAULT_CHAPTER

# The two generators raise their own error type for the same kinds of failure.
GENERATOR_ERRORS = (generator.GeneratorError, ch10_generator.GeneratorError)


def chapter_arg(value, default=DEFAULT_CHAPTER):
    """The chapter a request names, or None if it names one we do not have."""
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number in CHAPTERS else None


app = Flask(__name__)
# For production, set ILO_SECRET_KEY in the environment.
app.config["SECRET_KEY"] = os.environ.get("ILO_SECRET_KEY", "dev-secret-change-me")

# Railway (and most PaaS hosts) terminate TLS at a proxy and forward plain HTTP.
# Without this, request.is_secure is False and the session cookie would never
# get its Secure flag, so trust the forwarding headers when deployed.
if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("TRUST_PROXY"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Firebase session cookie. Named "__session" because that is the only cookie
# Firebase Hosting will forward if this is ever deployed there.
SESSION_COOKIE = "__session"
SESSION_DURATION = datetime.timedelta(days=5)

with open(os.path.join(BASE_DIR, "firebase_web_config.json")) as fh:
    # Public config: it identifies the project, it does not grant access.
    FIREBASE_WEB_CONFIG = json.load(fh)


# --- current user -----------------------------------------------------------

def current_user():
    """The signed-in user for this request, or None.

    Verifies the Firebase session cookie and pairs it with the Firestore
    profile. Cached on `g` so a request hits Firebase at most once.
    """
    if "user" in g:
        return g.user

    g.user = None
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        store.ensure_app()
        try:
            claims = fb_auth.verify_session_cookie(cookie, check_revoked=True)
        except store.ConfigError:
            raise
        except Exception:
            # Expired, revoked, or tampered with — treat as signed out.
            return None
        g.user = store.get_profile(claims["uid"])
    return g.user


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "firebase_config": FIREBASE_WEB_CONFIG,
    }


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.errorhandler(store.ConfigError)
def handle_config_error(exc):
    """Firebase isn't set up yet — say so clearly instead of a bare 500."""
    app.logger.error("Firebase configuration error: %s", exc)
    if request.path.startswith("/api/"):
        return jsonify(error=str(exc)), 500
    return render_template("config_error.html", message=str(exc)), 500


# --- pages ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login")
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/register")
def register():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/logout")
def logout():
    response = redirect(url_for("index"))
    response.delete_cookie(SESSION_COOKIE)
    flash("You have been logged out.", "success")
    return response


@app.route("/fitch")
def fitch():
    """Fitch proof practice. The checker runs entirely in the browser.

    With ?q=<id> the editor opens on a stored question instead of the built-in
    list, which is how the Generate page hands a problem over.
    """
    question = None
    qid = (request.args.get("q") or "").strip()
    if qid:
        question = store.get_question(qid)
        if question is None:
            flash("That question could not be found.", "error")
    return render_template("fitch.html", question=question)


@app.route("/generate")
@login_required
def generate_page():
    """Generate new exercises with the model, and browse the ones already saved."""
    chapter = chapter_arg(request.args.get("chapter"))
    if chapter is None:
        chapter = DEFAULT_CHAPTER
    return render_template(
        "generate.html",
        chapters=[dict(number=n, label=CHAPTERS[n]["label"],
                       blurb=CHAPTERS[n]["blurb"])
                  for n in sorted(CHAPTERS)],
        chapter=chapter,
        difficulties=CHAPTERS[chapter]["checker"].DIFFICULTIES,
        generator_ready=bool(os.environ.get("OPENAI_API_KEY")),
    )


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


# --- auth API (called by the Firebase JS SDK in the browser) ----------------

@app.post("/api/session")
def create_session():
    """Exchange a Firebase ID token for an HttpOnly session cookie.

    The client signs in with the Firebase JS SDK (email/password or Google),
    then posts the resulting ID token here. Passwords never reach this server.
    """
    payload = request.get_json(silent=True) or {}
    id_token = payload.get("idToken")
    desired_username = (payload.get("username") or "").strip() or None

    if not id_token:
        return jsonify(error="Missing ID token."), 400

    store.ensure_app()

    try:
        # A short max_age means a freshly-minted token, which is what we want
        # in exchange for a five-day cookie.
        decoded = fb_auth.verify_id_token(id_token, check_revoked=True)
    except store.ConfigError:
        raise
    except Exception as exc:
        app.logger.warning("Rejected ID token: %s", exc)
        return jsonify(error="Could not verify your sign-in. Please try again."), 401

    uid = decoded["uid"]
    provider = (decoded.get("firebase") or {}).get("sign_in_provider")

    # The token only names the method used right now. Ask Firebase for the
    # account's full provider list, which is also the only way to notice that
    # a provider was removed (e.g. linking Google drops an unverified password).
    try:
        providers = [p.provider_id for p in fb_auth.get_user(uid).provider_data]
    except Exception:
        providers = [provider] if provider else []

    profile, created = store.ensure_profile(
        uid,
        email=decoded.get("email"),
        display_name=decoded.get("name"),
        photo_url=decoded.get("picture"),
        provider=provider,
        providers=providers,
        desired_username=desired_username,
    )

    try:
        cookie = fb_auth.create_session_cookie(id_token, expires_in=SESSION_DURATION)
    except Exception as exc:
        app.logger.error("Could not mint session cookie: %s", exc)
        return jsonify(error="Could not start your session. Please try again."), 500

    response = jsonify(
        ok=True,
        created=created,
        username=profile.get("username"),
        redirect=url_for("dashboard"),
    )
    response.set_cookie(
        SESSION_COOKIE,
        cookie,
        max_age=int(SESSION_DURATION.total_seconds()),
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
    )
    return response


@app.post("/api/logout")
def api_logout():
    """Clear the session cookie and revoke refresh tokens for the user."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        store.ensure_app()
        try:
            claims = fb_auth.verify_session_cookie(cookie)
            fb_auth.revoke_refresh_tokens(claims["sub"])
        except Exception:
            pass  # Already invalid; clearing the cookie is enough.
    response = jsonify(ok=True, redirect=url_for("index"))
    response.delete_cookie(SESSION_COOKIE)
    return response


# --- questions API ----------------------------------------------------------

MAX_PER_REQUEST = 5


@app.post("/api/questions/generate")
@login_required
def api_generate_questions():
    """Generate exercises, verify them, save them, and return them.

    Generation is slow and costs money per call, so it is behind a login and
    capped. Nothing reaches Firestore until its proof has passed the same
    checker the browser editor runs.

    The generators are asked for more exercises than were wanted, because some
    candidates fail that checker. When the spares pass too they are banked in
    the waiting area, and the next request is served out of there before the
    model is called at all — so a request the pool can cover returns at once
    and costs nothing.
    """
    payload = request.get_json(silent=True) or {}
    chapter = chapter_arg(payload.get("chapter"))
    if chapter is None:
        return jsonify(error="Unknown chapter."), 400
    spec = CHAPTERS[chapter]

    difficulty = (payload.get("difficulty") or "").strip() or None
    try:
        count = int(payload.get("count") or 1)
    except (TypeError, ValueError):
        return jsonify(error="count must be a number."), 400

    if difficulty and difficulty not in spec["checker"].DIFFICULTIES:
        return jsonify(error="Unknown difficulty."), 400
    count = max(1, min(count, MAX_PER_REQUEST))
    uid = (current_user() or {}).get("uid")

    def verify(question):
        """Every complaint this server has about a candidate."""
        try:
            return spec["verify"](question)
        except Exception as exc:               # a malformed candidate
            return [str(exc)]

    # Spend the spares first. These were checked before they were banked; they
    # are checked again below, on the way out, like everything else.
    wanted = store.pool_take(chapter=chapter, difficulty=difficulty,
                             limit=count)
    from_pool = len(wanted)
    spare = []

    if len(wanted) < count:
        # What is on file for this chapter, so the model can be asked not to
        # write the same exercise again: what is public, what is still waiting,
        # and what this request has just claimed out of the pool and not yet
        # saved anywhere. Read only if the chapter's generator wants it.
        def on_file():
            return (store.list_questions(chapter=chapter, limit=200)
                    + store.list_pool(chapter=chapter)
                    + wanted)

        shortfall = count - len(wanted)
        try:
            fresh = spec["make"](shortfall, difficulty, on_file)
        except GENERATOR_ERRORS as exc:
            app.logger.warning("Chapter %s generation failed: %s", chapter, exc)
            if not wanted:
                return jsonify(error=str(exc)), 502
            fresh = []                 # the pool already covers part of this
        # The generators hand back everything that passed; the tail is surplus.
        wanted += fresh[:shortfall]
        spare = fresh[shortfall:]

    if not wanted:
        return jsonify(
            error="Nothing the model produced passed verification. Try again."
        ), 502

    def normalise(question):
        question["chapter"] = chapter
        # Chapter 10 names its prose "prompt" and leaves the length implicit.
        question["statement"] = (question.get("statement")
                                 or question.get("prompt") or "")
        question["line_count"] = len(question.get("proof") or [])
        return question

    saved, served_from_pool = [], 0
    for index, question in enumerate(wanted):
        # Belt and braces: never store an answer this server has not checked.
        problems = verify(normalise(question))
        if problems:
            app.logger.error("Unverified proof reached the route: %s", problems)
            continue
        question["id"] = store.save_question(question, created_by=uid)
        saved.append(question)
        if index < from_pool:
            served_from_pool += 1

    if not saved:
        return jsonify(error="The generated proofs did not verify."), 502

    # Bank whatever is left over, on the same terms: checked first, and only if
    # it is something nobody has been given yet. A spare is never worth failing
    # the request over.
    banked, waiting = [], 0
    try:
        banked = store.pool_add(
            (q for q in (normalise(s) for s in spare) if not verify(q)),
            created_by=uid)
        waiting = store.pool_counts(chapter=chapter)["total"]
    except Exception as exc:
        app.logger.warning("Could not bank the spare questions: %s", exc)

    return jsonify(questions=saved, from_pool=served_from_pool,
                   banked=len(banked), waiting=waiting)


@app.get("/api/questions")
@login_required
def api_list_questions():
    """Stored questions for one chapter, newest first, optionally filtered by
    difficulty."""
    chapter = chapter_arg(request.args.get("chapter"))
    if chapter is None:
        return jsonify(error="Unknown chapter."), 400
    difficulty = (request.args.get("difficulty") or "").strip() or None
    if difficulty and difficulty not in CHAPTERS[chapter]["checker"].DIFFICULTIES:
        return jsonify(error="Unknown difficulty."), 400
    questions = store.list_questions(difficulty=difficulty, chapter=chapter,
                                     limit=200)
    for question in questions:
        # created_at is a Firestore timestamp; the page only needs a date.
        stamp = question.pop("created_at", None)
        question["created"] = stamp.isoformat() if hasattr(stamp, "isoformat") else None
    return jsonify(questions=questions, chapter=chapter,
                   counts=store.question_counts(chapter=chapter))


@app.get("/api/username-available")
def username_available():
    """Live check for the signup form. Advisory only — the write is what counts."""
    username = (request.args.get("u") or "").strip()
    if not store.is_valid_username(username):
        return jsonify(valid=False, available=False)
    return jsonify(valid=True, available=not store.username_taken(username))


if __name__ == "__main__":
    # macOS uses port 5000 for AirPlay Receiver, so default to 5001.
    app.run(debug=True, port=int(os.environ.get("PORT", 5001)))
