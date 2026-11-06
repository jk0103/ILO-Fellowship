import collections
import datetime
import json
import os
import random
import re
import time

from flask import (
    Flask, flash, g, jsonify, redirect, render_template, request, url_for
)
from werkzeug.middleware.proxy_fix import ProxyFix
from firebase_admin import auth as fb_auth

import fitch_checker as checker
import fitch_generator as generator
import ch10_checker
import ch10_generator
import demographics
import firestore_db as store
import level_test
import progress

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

# Chapters on the dashboard's ladder that have a seeded bank but no generator
# yet, so they stay off the Generate page and its API.
LADDER_ONLY = {
    15: {"label": "Chapter 15 — induction and equality"},
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


def ladder_chapter(value):
    """The chapter a practice link names, or None if it is not on the ladder.

    Wider than chapter_arg: a LADDER_ONLY chapter can be practiced, just not
    generated for.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number in progress.CHAPTER_ORDER else None


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

# Firebase stamps tokens with Google's clock and rejects one "used too early"
# by this machine's. A local clock a couple of seconds slow would otherwise
# turn away every fresh sign-in, so allow a few seconds either way.
CLOCK_SKEW_SECONDS = 5

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
            claims = fb_auth.verify_session_cookie(
                cookie, check_revoked=True,
                clock_skew_seconds=CLOCK_SKEW_SECONDS)
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


def standing(user):
    """What the ladder is worked out from: the user's solve counts, and the
    start level their level test earned (None if they skipped it)."""
    return store.progress_counts(user["uid"]), level_test.start_of(user)


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

# Where the landing page's Contact section points, besides its form. Both are
# optional; whichever is unset is simply not shown.
CONTACT = {
    "email": os.environ.get("ILO_CONTACT_EMAIL"),
    "community": os.environ.get("ILO_COMMUNITY_URL"),
}


@app.route("/")
def index():
    return render_template("index.html", contact=CONTACT)


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


def about_choices():
    """What the "about you" fields are drawn from, for _about_fields.html."""
    return {
        "genders": demographics.GENDERS,
        "countries": demographics.COUNTRIES,
        "age_min": demographics.AGE_MIN,
        "age_max": demographics.AGE_MAX,
        "school_max": demographics.SCHOOL_MAX,
    }


def after_about(user):
    """Where someone goes once their "about you" answers are in."""
    if (user.get("level_test") or {}).get("status") not in ("done", "skipped"):
        return url_for("level_test_page")
    return url_for("dashboard")


@app.route("/welcome")
@login_required
def about_page():
    """The "about you" questions, asked once, straight after sign-up.

    Asked here rather than on the sign-up form so creating an account stays
    short, and so everyone is asked — including someone whose first sign-in
    was with Google from the login page, and accounts made before the
    questions existed. Answered already, it is the profile's job instead.
    """
    user = current_user()
    if user.get("demographics"):
        return redirect(url_for("profile_page"))
    return render_template("about.html", about={}, **about_choices())


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
    list, which is how the Dashboard and the Generate page hand a problem over.
    A stored question belongs to a level, so for a signed-in user this is also
    where the ladder is enforced and where the opening is recorded. Signed-out
    visitors keep the built-in problems and are not gated: there is no progress
    to gate them against.
    """
    question = None
    qid = (request.args.get("q") or "").strip()
    if qid:
        question = store.get_question(qid)
        if question is None:
            flash("That question could not be found.", "error")
        else:
            user = current_user()
            band = question.get("difficulty")
            if user and band in progress.BANDS:
                counts, start = standing(user)
                if not progress.is_unlocked(counts, question["chapter"], band,
                                            start):
                    flash(progress.locked_message(
                        counts, question["chapter"], band, start), "error")
                    return redirect(url_for("dashboard"))
                store.record_attempt(user["uid"], qid, question["chapter"], band)
    return render_template("fitch.html", question=question)


@app.route("/practice")
@login_required
def practice():
    """Open a question at one level of the ladder.

    This is what the Dashboard's level cards link to: it picks the exercise
    rather than making the user pick, preferring one they have not solved so
    that clicking twice does not hand back the same proof. Everything already
    solved is only reached once the level has nothing new left.
    """
    chapter = ladder_chapter(request.args.get("chapter"))
    band = (request.args.get("difficulty") or "").strip()
    if chapter is None or band not in progress.BANDS:
        flash("That is not a level you can practice.", "error")
        return redirect(url_for("dashboard"))

    uid = current_user()["uid"]
    counts, start = standing(current_user())
    if not progress.is_unlocked(counts, chapter, band, start):
        flash(progress.locked_message(counts, chapter, band, start), "error")
        return redirect(url_for("dashboard"))

    questions = store.list_questions(chapter=chapter, difficulty=band, limit=200)
    if not questions:
        if chapter not in CHAPTERS:
            flash("No %s questions for Chapter %d yet." % (band, chapter),
                  "error")
            return redirect(url_for("dashboard"))
        flash("No %s questions for Chapter %d yet — generate some first."
              % (band, chapter), "error")
        return redirect(url_for("generate_page", chapter=chapter))

    done = {r["id"] for r in store.list_progress(uid, chapter=chapter)
            if r["solved"]}
    fresh = [q for q in questions if q["id"] not in done]
    return redirect(url_for("fitch", q=random.choice(fresh or questions)["id"]))


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
    """The level map: what is open, what is cleared, what is still shut."""
    user = current_user()
    counts, start = standing(user)
    labels = {n: spec["label"]
              for n, spec in list(CHAPTERS.items()) + list(LADDER_ONLY.items())}
    return render_template(
        "dashboard.html",
        ladder=progress.ladder(counts, labels, start),
        to_clear=progress.TO_CLEAR,
        level_test=user.get("level_test") or {},
    )


@app.route("/profile")
@login_required
def profile_page():
    """Your details, editable, and two charts of how the practice is going."""
    user = current_user()
    records = store.list_progress(user["uid"])
    by_level = progress.solved_by_level(records)
    labels = {n: spec["label"]
              for n, spec in list(CHAPTERS.items()) + list(LADDER_ONLY.items())}
    return render_template(
        "profile.html",
        about=user.get("demographics") or {},
        **about_choices(),
        charts={
            "byLevel": [
                {"chapter": n, "label": "Ch. %d" % n,
                 "title": labels.get(n, "Chapter %d" % n),
                 "bands": by_level[n]}
                for n in progress.CHAPTER_ORDER
            ],
            "byDay": progress.solves_by_day(
                records, datetime.datetime.now(datetime.timezone.utc).date()),
            "bands": list(progress.BANDS),
        },
        to_clear=progress.TO_CLEAR,
        level_test=user.get("level_test") or {},
    )


@app.route("/level-test")
@login_required
def level_test_page():
    """The level test: intro, one question at a time, then the result.

    New accounts are sent here straight from sign-up. The questions are dealt
    once and kept on the profile, so reloading the page, or skipping and coming
    back, hands back the same test rather than a fresh draw. Only the prompts
    and choices reach the browser; the answers stay here until it is submitted.
    """
    user = current_user()
    test = user.get("level_test") or {}
    if test.get("status") == "done":
        flash("You have already taken the level test: %s." % test.get("level"),
              "success")
        return redirect(url_for("dashboard"))

    dealt = test.get("questions") or []
    questions = store.get_level_test_questions(dealt) if dealt else []
    def has_proofs(qs):
        return any(level_test.kind(q) == level_test.FITCH for q in qs)

    if len(questions) != len(dealt) or not questions:
        # Never dealt, or a question has since been deleted: deal afresh.
        questions = level_test.select(store.list_level_test_questions())
        if questions:
            store.deal_level_test(user["uid"], [q["id"] for q in questions])
    elif not has_proofs(questions):
        # Dealt before the bank had proofs. Deal again so it ends on proofs
        # like everyone else's, if the bank has them now.
        fresh = level_test.select(store.list_level_test_questions())
        if has_proofs(fresh):
            questions = fresh
            store.deal_level_test(user["uid"], [q["id"] for q in questions])

    return render_template(
        "level_test.html",
        questions=[level_test.public(q) for q in questions],
    )


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
        decoded = fb_auth.verify_id_token(
            id_token, check_revoked=True,
            clock_skew_seconds=CLOCK_SKEW_SECONDS)
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
        # Anyone without "about you" answers is asked for them first; a new
        # account then takes the level test, which it can skip from there.
        redirect=(url_for("about_page") if not profile.get("demographics")
                  else url_for("level_test_page") if created
                  else url_for("dashboard")),
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
            claims = fb_auth.verify_session_cookie(
                cookie, clock_skew_seconds=CLOCK_SKEW_SECONDS)
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


# --- progress API -----------------------------------------------------------

@app.post("/api/progress/solved")
@login_required
def api_record_solved():
    """The editor reports a finished proof; the ladder moves.

    Only the question id is taken. Which chapter and band it counts for is read
    from Firestore, so the browser cannot claim a hard Chapter 10 solve for an
    easy Chapter 5 one, and the proof itself is not sent: it was checked line
    by line in the editor by the same rules this server would apply, and the
    worked answer is on file here anyway.
    """
    payload = request.get_json(silent=True) or {}
    qid = (payload.get("question_id") or "").strip()
    question = store.get_question(qid)
    if question is None:
        return jsonify(error="Unknown question."), 404

    band = question.get("difficulty")
    if band not in progress.BANDS:
        return jsonify(error="That question is not on the ladder."), 400

    uid = current_user()["uid"]
    before, start = standing(current_user())
    first = store.record_solved(uid, qid, question["chapter"], band)
    after = store.progress_counts(uid) if first else before

    # What this proof just opened, if anything, so the editor can say so.
    opened = [
        {"chapter": level["chapter"], "band": level["band"]}
        for entry in progress.ladder(after, start=start)
        for level in entry["levels"]
        if level["unlocked"]
        and not progress.is_unlocked(before, level["chapter"], level["band"],
                                     start)
    ]

    return jsonify(
        ok=True,
        first_solve=first,
        solved=progress.solved(after, question["chapter"], band),
        need=progress.TO_CLEAR,
        unlocked=opened,
    )


# --- level test API ---------------------------------------------------------

@app.post("/api/level-test/skip")
@login_required
def api_skip_level_test():
    """Put the level test off. The dashboard keeps offering it."""
    user = current_user()
    if (user.get("level_test") or {}).get("status") != "done":
        store.skip_level_test(user["uid"])
    return jsonify(ok=True, redirect=url_for("dashboard"))


@app.post("/api/level-test/submit")
@login_required
def api_submit_level_test():
    """Mark the level test and set the level it earns.

    Only the answers are taken. Which questions they answer is read from the
    profile, where they were stored when the test was dealt, so the browser
    cannot swap in questions of its own choosing. A test is marked once.
    """
    user = current_user()
    test = user.get("level_test") or {}
    if test.get("status") == "done":
        return jsonify(error="You have already taken the level test."), 409

    questions = store.get_level_test_questions(test.get("questions") or [])
    if not questions:
        return jsonify(error="There is no level test to submit. "
                             "Reload the page to start one."), 400

    payload = request.get_json(silent=True) or {}
    answers = payload.get("answers")
    marking = level_test.score(questions,
                               answers if isinstance(answers, dict) else {})
    name, start = level_test.place(marking["earned"], marking["possible"])

    finished = store.finish_level_test(user["uid"], {
        "answers": {m["id"]: m["chosen"] for m in marking["marked"]
                    if m["chosen"] is not None},
        "earned": marking["earned"],
        "possible": marking["possible"],
        "right": marking["right"],
        "total": marking["total"],
        "level": name,
        "placement": {"chapter": start[0], "band": start[1]},
    })
    if not finished:
        return jsonify(error="You have already taken the level test."), 409

    # The test is over, so the answers can go to the browser now.
    by_id = {q["id"]: q for q in questions}
    review = []
    for m in marking["marked"]:
        question = by_id[m["id"]]
        entry = {"id": m["id"], "correct": m["correct"],
                 "explanation": question.get("explanation", "")}
        if level_test.kind(question) == level_test.FITCH:
            # The steps are the browser's own; send back what was wrong with
            # them and a worked proof, not the steps again.
            entry["problems"] = m.get("problems") or []
            entry["proof"] = level_test.worked_rows(question)
        else:
            entry.update(chosen=m["chosen"], answer=question["answer"])
        review.append(entry)

    return jsonify(
        ok=True,
        level=name,
        earned=marking["earned"],
        possible=marking["possible"],
        right=marking["right"],
        total=marking["total"],
        unlocked=[{"chapter": c, "band": b}
                  for c, b in level_test.opened_by(start)],
        review=review,
        redirect=url_for("dashboard"),
    )


# --- contact API ------------------------------------------------------------

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
CONTACT_LIMITS = {"name": 100, "email": 200, "message": 5000}

# At most this many messages per address per window. Kept in memory, so it
# resets on restart and is per process: enough to stop a form being hammered,
# not a substitute for real rate limiting.
CONTACT_PER_WINDOW = 5
CONTACT_WINDOW = 60 * 60
_contact_sent = collections.defaultdict(collections.deque)


@app.post("/api/contact")
def api_contact():
    """The landing page's contact form. No account needed.

    The message is stored in Firestore for the team to read. A filled-in
    `website` field is the honeypot: people never see it, bots fill it, and
    they are told it worked so they do not try again.
    """
    payload = request.get_json(silent=True) or {}
    fields = {key: str(payload.get(key) or "").strip() for key in CONTACT_LIMITS}

    if payload.get("website"):
        return jsonify(ok=True)
    if not all(fields.values()):
        return jsonify(error="Please fill in your name, email and message."), 400
    if not EMAIL_RE.fullmatch(fields["email"]):
        return jsonify(error="That doesn't look like a valid email address."), 400
    for key, limit in CONTACT_LIMITS.items():
        if len(fields[key]) > limit:
            return jsonify(error="Your %s is too long (%d characters at most)."
                           % (key, limit)), 400

    now = time.time()
    sent = _contact_sent[request.remote_addr]
    while sent and now - sent[0] > CONTACT_WINDOW:
        sent.popleft()
    if len(sent) >= CONTACT_PER_WINDOW:
        return jsonify(error="You've sent several messages already. "
                             "Please try again later."), 429

    store.save_contact_message(uid=(current_user() or {}).get("uid"), **fields)
    sent.append(now)
    return jsonify(ok=True)


@app.get("/api/username-available")
def username_available():
    """Live check for the signup form. Advisory only — the write is what counts."""
    username = (request.args.get("u") or "").strip()
    if not store.is_valid_username(username):
        return jsonify(valid=False, available=False)
    return jsonify(valid=True, available=not store.username_taken(username))


@app.post("/api/about")
def api_save_about():
    """Save the welcome page's "about you" answers, all four required."""
    user = current_user()
    if user is None:
        return jsonify(error="Please log in again."), 401
    about = demographics.clean((request.get_json(silent=True) or {}).get("about"))
    for field in ("gender", "age", "school", "nationality"):
        if field not in about:
            return jsonify(error="Please check your %s." % field, field=field), 400
    store.update_profile(user["uid"], demographics=about)
    return jsonify(ok=True, redirect=after_about(user))


@app.post("/api/profile")
def api_update_profile():
    """Save the profile page's form: the username and the "about you" answers.

    Unlike sign-up, nothing here is half-done if a value is bad, so a missing
    or malformed answer is refused outright rather than dropped.
    """
    user = current_user()
    if user is None:
        return jsonify(error="Please log in again."), 401

    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    if not store.is_valid_username(username):
        return jsonify(error="Username must be 3-20 characters: letters, "
                             "numbers, underscores.", field="username"), 400

    raw = payload.get("about") or {}
    about = demographics.clean(raw)
    for field in ("gender", "age", "school", "nationality"):
        if field not in about:
            return jsonify(error="Please check your %s." % field, field=field), 400

    try:
        profile = store.update_profile(user["uid"], username=username,
                                       demographics=about)
    except store.UsernameTaken:
        return jsonify(error="%s is already taken." % username,
                       field="username"), 409
    return jsonify(ok=True, username=profile.get("username"))


if __name__ == "__main__":
    # macOS uses port 5000 for AirPlay Receiver, so default to 5001.
    app.run(debug=True, port=int(os.environ.get("PORT", 5001)))
