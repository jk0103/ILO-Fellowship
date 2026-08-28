"""Firestore data layer for ILO Prep.

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

usernames/{username_lower}
    uid           (str)

Firestore has no unique constraints, so the username is the document id in
`usernames` and reserved in the same transaction that writes the profile.
"""

import json
import os
import re
import threading

import firebase_admin
from firebase_admin import credentials, firestore

USERS = "users"
USERNAMES = "usernames"

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
    username = profile.get("username")
    if username:
        db.collection(USERNAMES).document(username.lower()).delete()
    db.collection(USERS).document(uid).delete()
