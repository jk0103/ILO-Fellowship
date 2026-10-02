"""Firestore data layer for ILO Bank.

Identity lives in Firebase Authentication; this module stores everything else.

Collections
-----------
users/{uid}
    username      (str)  display handle, unique
    email         (str, lowercased)
    display_name  (str)
    photo_url     (str or None)
    providers     (list[str])  e.g. ["password"], ["google.com"]
    created_at    (server timestamp)
    last_login    (server timestamp)
    stats         (map) solved / attempted / streak

users/{uid}/progress/{question id}
    chapter       (int)
    difficulty    (str)  the band the question belongs to
    attempts      (int)  how many times this user has opened it
    solved        (bool) whether its proof has ever been completed
    solved_at     (server timestamp, once)
    updated_at    (server timestamp)

    One document per question a user has met. `progress.py` turns these into
    the level ladder: a band opens when enough *distinct* questions in the one
    before it are solved, which is why this is per question and not a counter.

usernames/{username_lower}
    uid           (str)

questions/{fingerprint}
    statement     (str)  the exercise as prose
    chapter       (int)  5 (propositional) or 10 (relational)
    premises      (list[str])
    goal          (str)
    constants     (list[str])  object constants the language is limited to,
                               empty unless the exercise declares them
    hint          (str)
    proof         (list[map])  the worked answer, one map per line
    line_count    (int)  len(proof)
    difficulty    (str)  "easy" | "medium" | "hard", from line_count
    source        (str)  "generated" or "seed"
    created_by    (str or None)  uid of whoever generated it
    created_at    (server timestamp)

question_pool/{fingerprint}
    The waiting area. Same fields as `questions`, minus `source`. A generator
    is always asked for more exercises than were wanted, since some candidates
    fail the checker; on a good run the spares pass too. Those spares land here
    instead of being thrown away, and the next request for that chapter is
    served out of here before the model is called at all. Claiming one is a
    transaction, so two requests arriving together cannot be handed the same
    exercise. Nothing is ever shown to anyone from this collection — a claim
    moves the document into `questions` first.

The document id is a fingerprint of the premises and goal, so generating the
same exercise twice updates one document instead of accumulating duplicates.
The pool uses the same fingerprint, which is what stops it from banking an
exercise that is already public or already waiting. Documents written before
chapters existed carry no `chapter` field; they are all Chapter 5, which is why
reads default it rather than requiring it.

Firestore has no unique constraints, so the username is the document id in
`usernames` and reserved in the same transaction that writes the profile.
"""

import hashlib
import json
import os
import re
import threading

import firebase_admin
from firebase_admin import credentials, firestore

USERS = "users"
USERNAMES = "usernames"
QUESTIONS = "questions"
POOL = "question_pool"

# How many spare exercises to hold per chapter. The pool is drained by ordinary
# use, so this only matters for a band nobody asks for: without a cap those
# would accumulate forever.
POOL_LIMIT = 50

# Chapter 5 came first and its documents predate the field, so a question with
# no chapter recorded is one of its.
DEFAULT_CHAPTER = 5

_client = None
_lock = threading.Lock()


class ConfigError(Exception):
    """Raised when Firebase credentials are missing or unusable."""


_SETUP_HELP = (
    "Could not connect to Firebase: %s\n\n"
    "Set FIREBASE_CREDENTIALS to the path of your service-account JSON file:\n"
    "  Firebase console -> Project settings -> Service accounts\n"
    "  -> Generate new private key\n\n"
    "By default the app looks for ./serviceAccountKey.json"
)

DEFAULT_KEY_FILE = "serviceAccountKey.json"


def ensure_app():
    """Initialise the Firebase Admin app once per process.

    Resolution order for credentials:
      1. FIRESTORE_EMULATOR_HOST   -> no real credentials needed
      2. FIREBASE_CREDENTIALS      -> path to a service-account JSON file
      3. FIREBASE_CREDENTIALS_JSON -> the service-account JSON itself
      4. ./serviceAccountKey.json  -> the usual local development spot
      5. Application Default Credentials (gcloud / Cloud Run / GCE)
    """
    if firebase_admin._apps:
        return

    project_id = os.environ.get("FIREBASE_PROJECT_ID")

    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        firebase_admin.initialize_app(
            options={"projectId": project_id or "demo-ilo-practice"}
        )
        return

    options = {"projectId": project_id} if project_id else {}
    cred_path = os.environ.get("FIREBASE_CREDENTIALS")
    cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")

    local_key = os.path.join(os.path.dirname(os.path.abspath(__file__)), DEFAULT_KEY_FILE)

    try:
        if cred_path:
            if not os.path.exists(cred_path):
                raise ConfigError(
                    "FIREBASE_CREDENTIALS points at %r, which does not exist." % cred_path
                )
            cred = credentials.Certificate(cred_path)
        elif cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
        elif os.path.exists(local_key):
            cred = credentials.Certificate(local_key)
        else:
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, options)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(_SETUP_HELP % exc) from exc


def get_client():
    """Return a lazily-initialised Firestore client (one per process)."""
    global _client
    if _client is not None:
        return _client

    with _lock:
        if _client is not None:
            return _client
        try:
            ensure_app()
            # Credentials resolve lazily, so this is where a bad or missing
            # service account actually surfaces.
            _client = firestore.client()
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(_SETUP_HELP % exc) from exc
        return _client


# --- usernames --------------------------------------------------------------

USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,20}")


def is_valid_username(username):
    return bool(username) and bool(USERNAME_RE.fullmatch(username))


def username_taken(username):
    if not is_valid_username(username):
        return False
    return get_client().collection(USERNAMES).document(username.lower()).get().exists


def suggest_username(seed):
    """Turn an email or display name into a plausible username."""
    base = re.sub(r"[^A-Za-z0-9_]", "", (seed or "").split("@")[0])[:20]
    if len(base) < 3:
        base = (base + "user")[:20]
    return base


# --- profiles ---------------------------------------------------------------

def get_profile(uid):
    """Return the profile dict for `uid`, or None."""
    if not uid:
        return None
    snapshot = get_client().collection(USERS).document(uid).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    data["uid"] = uid
    return data


def ensure_profile(uid, email, display_name=None, photo_url=None,
                   provider=None, providers=None, desired_username=None):
    """Create the profile on first sign-in, or refresh it on later ones.

    Returns (profile, created). The username is reserved transactionally; if
    `desired_username` is taken (or not given) a numbered variant is used, so
    signing in never fails just because a handle collided.
    """
    db = get_client()
    existing = get_profile(uid)

    if existing:
        updates = {"last_login": firestore.SERVER_TIMESTAMP}
        if email and existing.get("email") != email.lower():
            updates["email"] = email.lower()
        if display_name and existing.get("display_name") != display_name:
            updates["display_name"] = display_name
        if photo_url and existing.get("photo_url") != photo_url:
            updates["photo_url"] = photo_url
        # Firebase can *remove* a provider — linking Google to an account whose
        # email was unverified drops the password provider — so mirror the
        # current list rather than accumulating one.
        current = providers if providers is not None else (
            [provider] if provider else None)
        if current is not None and sorted(current) != sorted(existing.get("providers") or []):
            updates["providers"] = current
        db.collection(USERS).document(uid).update(updates)
        return get_profile(uid), False

    seed = desired_username if is_valid_username(desired_username) else \
        suggest_username(display_name or email)

    # Try the preferred handle, then seed2, seed3, ... The transaction is what
    # actually guarantees uniqueness; the loop just finds a free candidate.
    for attempt in range(25):
        candidate = seed if attempt == 0 else "%s%d" % (seed[:18], attempt + 1)
        if _claim(db, uid, candidate, email, display_name, photo_url,
                  providers if providers is not None else
                  ([provider] if provider else [])):
            return get_profile(uid), True

    raise RuntimeError("Could not allocate a username for uid %s" % uid)


def _claim(db, uid, username, email, display_name, photo_url, providers):
    """Reserve `username` and write the profile atomically. False if taken."""
    name_ref = db.collection(USERNAMES).document(username.lower())
    user_ref = db.collection(USERS).document(uid)

    @firestore.transactional
    def _txn(transaction):
        # All reads must happen before any write in a Firestore transaction.
        if name_ref.get(transaction=transaction).exists:
            return False
        transaction.set(name_ref, {"uid": uid})
        transaction.set(user_ref, {
            "username": username,
            "email": (email or "").lower(),
            "display_name": display_name or username,
            "photo_url": photo_url,
            "providers": providers if providers is not None else (
                [provider] if provider else []),
            "created_at": firestore.SERVER_TIMESTAMP,
            "last_login": firestore.SERVER_TIMESTAMP,
            "stats": {"solved": 0, "attempted": 0, "streak": 0},
        })
        return True

    return _txn(db.transaction())


def delete_profile(uid):
    """Remove a profile and release its username. Used by tests and cleanup."""
    db = get_client()
    profile = get_profile(uid)
    if not profile:
        return
    # Deleting a document does not delete what is under it, and orphaned
    # progress records would be handed straight back to a recreated uid.
    clear_progress(uid)
    username = profile.get("username")
    if username:
        db.collection(USERNAMES).document(username.lower()).delete()
    db.collection(USERS).document(uid).delete()


# --- questions --------------------------------------------------------------

def _parser_for(chapter):
    """The module that parses and prints the formulas of `chapter`."""
    if int(chapter) == 10:
        import ch10_checker
        return ch10_checker
    import fitch_checker
    return fitch_checker


def question_id(premises, goal, chapter=DEFAULT_CHAPTER):
    """A stable id for an exercise, so the same problem never lands twice.

    Formulas are normalised through the chapter's own checker first, so "p&q"
    and "p ∧ q" fingerprint alike. Chapter 5 fingerprints stay the bare digest
    they have always been, so existing documents and the links into them keep
    working; later chapters mix the number in, which is what keeps a relational
    exercise from ever colliding with a propositional one.
    """
    chapter = int(chapter)
    fc = _parser_for(chapter)

    parts = sorted(fc.show(fc.parse(p)) for p in premises) + \
        ["⊢ " + fc.show(fc.parse(goal))]
    if chapter != DEFAULT_CHAPTER:
        parts.insert(0, "chapter %d" % chapter)
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:20]


def _payload(question):
    """The stored shape of one question, shared by the bank and the pool.

    `question` is what a chapter's generator returns: premises, goal, hint,
    proof and difficulty, plus `statement` from Chapter 5 or `prompt` from
    Chapter 10. Nothing is validated here — callers check the proof with that
    chapter's checker before saving.
    """
    return {
        # Chapter 5 calls the prose "statement", Chapter 10 calls it "prompt".
        "statement": question.get("statement") or question.get("prompt") or "",
        "chapter": int(question.get("chapter") or DEFAULT_CHAPTER),
        "premises": question["premises"],
        "goal": question["goal"],
        "constants": list(question.get("constants") or []),
        "hint": question.get("hint", ""),
        "proof": question["proof"],
        "line_count": question.get("line_count") or len(question["proof"]),
        "difficulty": question["difficulty"],
    }


def save_question(question, created_by=None, source="generated"):
    """Write one verified question and return its document id."""
    payload = _payload(question)
    chapter = payload["chapter"]
    qid = question_id(question["premises"], question["goal"], chapter)
    ref = get_client().collection(QUESTIONS).document(qid)
    existing = ref.get()

    payload["source"] = source
    if existing.exists:
        # Keep the original authorship and timestamp; only the answer can change
        # (a later run may find a shorter proof, which changes the difficulty).
        ref.update(payload)
    else:
        payload["created_by"] = created_by
        payload["created_at"] = firestore.SERVER_TIMESTAMP
        ref.set(payload)
    return qid


def get_question(qid):
    """One question by id, or None."""
    if not qid:
        return None
    snapshot = get_client().collection(QUESTIONS).document(qid).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    data["id"] = qid
    data["chapter"] = int(data.get("chapter") or DEFAULT_CHAPTER)
    return data


def list_questions(difficulty=None, chapter=None, limit=100):
    """Stored questions, newest first, optionally narrowed to one chapter
    and one difficulty band.

    Ordering by created_at with an equality filter needs a composite index in
    Firestore, so both filters are applied here instead. That is fine at this
    size and keeps deployment to a single collection with no index
    configuration.

    The `limit` is the number of documents read, not the number returned, so a
    narrow filter over a large collection can come back short.
    """
    query = get_client().collection(QUESTIONS) \
        .order_by("created_at", direction=firestore.Query.DESCENDING) \
        .limit(max(1, min(int(limit), 500)))

    out = []
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        data["chapter"] = int(data.get("chapter") or DEFAULT_CHAPTER)
        if chapter is not None and data["chapter"] != int(chapter):
            continue
        if difficulty and data.get("difficulty") != difficulty:
            continue
        data["id"] = snapshot.id
        out.append(data)
    return out


def question_counts(chapter=None):
    """How many questions are stored, per difficulty band.

    Counts every chapter unless one is named.
    """
    counts = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    for snapshot in get_client().collection(QUESTIONS).stream():
        data = snapshot.to_dict() or {}
        if chapter is not None and \
                int(data.get("chapter") or DEFAULT_CHAPTER) != int(chapter):
            continue
        band = data.get("difficulty")
        if band in counts:
            counts[band] += 1
        counts["total"] += 1
    return counts


def delete_question(qid):
    """Remove one question. Used by tests and cleanup."""
    get_client().collection(QUESTIONS).document(qid).delete()


# --- the waiting area -------------------------------------------------------
#
# A generator is asked for more exercises than were wanted, because candidates
# get dropped. When the spares survive the checker too, they are verified work
# that has already been paid for, so they wait here for the next request
# instead of being discarded. Nothing here is visible to anyone: a question is
# moved into `questions` at the moment it is claimed.

def pool_add(questions, created_by=None):
    """Bank verified spares. Returns the ids that were actually banked.

    A spare is skipped when the exercise is already public, when an identical
    one is already waiting, or when its chapter's pool is full — so handing
    this everything left over is safe. Takes the whole batch at once so the
    chapter's pool is counted once rather than once per spare.
    """
    db = get_client()
    banked, room = [], {}

    for question in questions:
        payload = _payload(question)
        chapter = payload["chapter"]
        if chapter not in room:
            room[chapter] = POOL_LIMIT - pool_counts(chapter=chapter)["total"]
        if room[chapter] <= 0:
            continue

        qid = question_id(question["premises"], question["goal"], chapter)
        if db.collection(QUESTIONS).document(qid).get().exists:
            continue                   # already on file; not new to anyone
        ref = db.collection(POOL).document(qid)
        if ref.get().exists:
            continue                   # already waiting

        payload["created_by"] = created_by
        payload["created_at"] = firestore.SERVER_TIMESTAMP
        ref.set(payload)
        room[chapter] -= 1
        banked.append(qid)

    return banked


def pool_take(chapter, difficulty=None, limit=1):
    """Claim up to `limit` waiting questions, oldest first, and return them.

    A claimed question is removed from the pool and handed back for the caller
    to check and save; the claim is transactional, so two requests arriving
    together never receive the same exercise. If the caller dies before saving,
    the question is lost — this is a cache of spare work, not a record of it.

    Like `list_questions`, the chapter and difficulty are filtered here rather
    than in the query, to keep Firestore free of composite indexes.
    """
    limit = max(0, int(limit))
    if not limit:
        return []

    db = get_client()
    query = db.collection(POOL) \
        .order_by("created_at", direction=firestore.Query.ASCENDING) \
        .limit(2 * POOL_LIMIT)

    taken = []
    for snapshot in query.stream():
        if len(taken) >= limit:
            break
        data = snapshot.to_dict() or {}
        if int(data.get("chapter") or DEFAULT_CHAPTER) != int(chapter):
            continue
        if difficulty and data.get("difficulty") != difficulty:
            continue
        claimed = _claim_pooled(db, snapshot.id)
        if claimed is not None:
            claimed["id"] = snapshot.id
            claimed["chapter"] = int(claimed.get("chapter") or DEFAULT_CHAPTER)
            taken.append(claimed)
    return taken


def _claim_pooled(db, qid):
    """Remove one pooled question and return it, or None if it is already gone."""
    ref = db.collection(POOL).document(qid)

    @firestore.transactional
    def _txn(transaction):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            return None                # another request got there first
        transaction.delete(ref)
        return snapshot.to_dict() or {}

    return _txn(db.transaction())


def list_pool(chapter=None, difficulty=None):
    """Everything waiting, so a generator can be told not to write it again."""
    out = []
    for snapshot in get_client().collection(POOL).stream():
        data = snapshot.to_dict() or {}
        data["chapter"] = int(data.get("chapter") or DEFAULT_CHAPTER)
        if chapter is not None and data["chapter"] != int(chapter):
            continue
        if difficulty and data.get("difficulty") != difficulty:
            continue
        data["id"] = snapshot.id
        out.append(data)
    return out


def pool_counts(chapter=None):
    """How many spares are waiting, per difficulty band."""
    counts = {"easy": 0, "medium": 0, "hard": 0, "total": 0}
    for snapshot in get_client().collection(POOL).stream():
        data = snapshot.to_dict() or {}
        if chapter is not None and \
                int(data.get("chapter") or DEFAULT_CHAPTER) != int(chapter):
            continue
        band = data.get("difficulty")
        if band in counts:
            counts[band] += 1
        counts["total"] += 1
    return counts


def delete_pooled(qid):
    """Remove one waiting question. Used by tests and cleanup."""
    get_client().collection(POOL).document(qid).delete()


# --- progress ---------------------------------------------------------------
#
# One document per user per question, under the profile. It is what the level
# ladder in `progress.py` is computed from, and keeping it per question is what
# makes a level count *distinct* questions solved: re-proving the same exercise
# does not move anyone up a level.
#
# `attempts` counts openings rather than wrong moves, because the editor checks
# every line as it is written and never rejects a finished proof — there is no
# "submit" to fail. That makes it a rough denominator for the accuracy gate
# that is planned, not an exact one.

PROGRESS = "progress"


def _progress_ref(db, uid, qid):
    return db.collection(USERS).document(uid).collection(PROGRESS).document(qid)


def record_attempt(uid, qid, chapter, difficulty):
    """Note that `uid` has opened question `qid`.

    Creates the record on the first opening and increments `attempts` on every
    one. Never clears `solved`, so revisiting a question already proved leaves
    the level count where it was.
    """
    if not (uid and qid):
        return
    db = get_client()
    _progress_ref(db, uid, qid).set({
        "chapter": int(chapter or DEFAULT_CHAPTER),
        "difficulty": difficulty,
        "attempts": firestore.Increment(1),
        "updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)
    db.collection(USERS).document(uid).update(
        {"stats.attempted": firestore.Increment(1)})


def record_solved(uid, qid, chapter, difficulty):
    """Mark question `qid` as proved by `uid`. True if that is new.

    Transactional, because the profile's `stats.solved` may only move on the
    first solve and two tabs can report the same proof at once. `attempts` is
    left alone: solving is not a separate attempt from the opening it ends.
    """
    if not (uid and qid):
        return False
    db = get_client()
    ref = _progress_ref(db, uid, qid)
    user_ref = db.collection(USERS).document(uid)

    @firestore.transactional
    def _txn(transaction):
        snapshot = ref.get(transaction=transaction)
        data = snapshot.to_dict() or {}
        first = not data.get("solved")

        payload = {
            "chapter": int(chapter or DEFAULT_CHAPTER),
            "difficulty": difficulty,
            "solved": True,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        if first:
            payload["solved_at"] = firestore.SERVER_TIMESTAMP
            # Reaching a question by a route that did not record the opening
            # (a shared link, say) should still leave a sane denominator.
            if not snapshot.exists:
                payload["attempts"] = 1
        transaction.set(ref, payload, merge=True)
        if first:
            transaction.update(user_ref, {"stats.solved": firestore.Increment(1)})
        return first

    return _txn(db.transaction())


def list_progress(uid, chapter=None):
    """This user's per-question records, optionally for one chapter."""
    if not uid:
        return []
    out = []
    for snapshot in get_client().collection(USERS).document(uid) \
            .collection(PROGRESS).stream():
        data = snapshot.to_dict() or {}
        data["chapter"] = int(data.get("chapter") or DEFAULT_CHAPTER)
        if chapter is not None and data["chapter"] != int(chapter):
            continue
        data["id"] = snapshot.id
        data["solved"] = bool(data.get("solved"))
        data["attempts"] = int(data.get("attempts") or 0)
        out.append(data)
    return out


def progress_counts(uid):
    """Per chapter and band: {"solved", "seen", "attempts"}.

    `solved` and `seen` count distinct questions — the level ladder is built on
    those. `attempts` totals the openings, and is here for the accuracy gate.
    Bands the user has not touched are absent rather than zero; `progress.py`
    treats a missing cell as empty.
    """
    counts = {}
    for record in list_progress(uid):
        band = record.get("difficulty")
        if band not in ("easy", "medium", "hard"):
            continue          # a question written before difficulty was stored
        cell = counts.setdefault(record["chapter"], {}).setdefault(
            band, {"solved": 0, "seen": 0, "attempts": 0})
        cell["seen"] += 1
        cell["attempts"] += record["attempts"]
        if record["solved"]:
            cell["solved"] += 1
    return counts


def clear_progress(uid):
    """Drop every progress record for a user. Used by tests and cleanup."""
    if not uid:
        return
    db = get_client()
    for snapshot in db.collection(USERS).document(uid) \
            .collection(PROGRESS).stream():
        snapshot.reference.delete()
