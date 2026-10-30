"""End-to-end tests against the real Firebase project.

Exercises the same REST endpoints the Firebase JS SDK calls in the browser
(accounts:signUp / accounts:signInWithPassword), then feeds the resulting ID
token to the Flask app exactly as the frontend does. Test users and their
Firestore documents are deleted afterwards.

Run:  python3 test_app.py
"""

import json
import uuid

import requests
from firebase_admin import auth as fb_auth

import firestore_db as store
import progress
import app as m

CONFIG = json.load(open("firebase_web_config.json"))
API = "https://identitytoolkit.googleapis.com/v1/accounts:%s?key=" + CONFIG["apiKey"]

store.ensure_app()
m.app.config.update(TESTING=True)

checks = []
created_uids = []


def check(label, condition):
    checks.append((label, bool(condition)))
    print("%-38s %s" % (label, "PASS" if condition else "FAIL"))


def sign_up(email, password):
    """What createUserWithEmailAndPassword does in the browser."""
    r = requests.post(API % "signUp",
                      json={"email": email, "password": password,
                            "returnSecureToken": True}, timeout=30)
    r.raise_for_status()
    data = r.json()
    created_uids.append(data["localId"])
    return data["idToken"]


def sign_in(email, password):
    """What signInWithEmailAndPassword does in the browser."""
    r = requests.post(API % "signInWithPassword",
                      json={"email": email, "password": password,
                            "returnSecureToken": True}, timeout=30)
    r.raise_for_status()
    return r.json()["idToken"]


suffix = uuid.uuid4().hex[:8]
EMAIL = "ilo_test_%s@example.com" % suffix
PASSWORD = "practice-logic-%s" % suffix
USERNAME = "tester_%s" % suffix[:6]

try:
    # --- pages render -------------------------------------------------------
    c = m.app.test_client()
    check("index renders", c.get("/").status_code == 200)
    check("login page renders", c.get("/login").status_code == 200)
    check("register page renders", c.get("/register").status_code == 200)
    check("dashboard gated when anon", c.get("/dashboard").status_code == 302)
    check("web config injected", CONFIG["apiKey"].encode() in c.get("/login").data)

    # --- signup -> session --------------------------------------------------
    id_token = sign_up(EMAIL, PASSWORD)
    ABOUT = {"gender": "female", "age": 17, "school": "Test High School",
             "nationality": "South Korea"}
    r = c.post("/api/session", json={"idToken": id_token, "username": USERNAME,
                                     "about": dict(ABOUT, gender="bogus")})
    body = r.get_json() or {}
    check("session created from ID token", r.status_code == 200 and body.get("ok"))
    check("marked as new account", body.get("created") is True)
    check("username honoured", body.get("username") == USERNAME)
    check("session cookie set", "__session" in [k.split("=")[0] for k in
          [h[1] for h in r.headers if h[0] == "Set-Cookie"]])

    uid = created_uids[-1]
    profile = store.get_profile(uid)
    check("firestore profile written", profile is not None)
    check("profile email correct", profile["email"] == EMAIL.lower())
    check("provider recorded", "password" in profile["providers"])
    check("stats initialised", profile["stats"]["solved"] == 0)
    about = dict(profile.get("demographics") or {})
    check("about-you answers stored", about.pop("collected_at", None) is not None
          and about == {k: v for k, v in ABOUT.items() if k != "gender"})
    check("username index written",
          store.get_client().collection("usernames").document(USERNAME.lower())
          .get().to_dict()["uid"] == uid)
    check("no password stored in firestore",
          not any("pass" in k for k in profile.keys()))
    check("a new account is sent to the level test",
          (body.get("redirect") or "").endswith("/level-test"))

    # --- the level test -----------------------------------------------------
    # Dealing, marking and placing are tested offline in test_level_test.py;
    # what is checked here is that the page opens and skipping is stored.
    check("level test page opens", c.get("/level-test").status_code == 200)
    r = c.post("/api/level-test/skip")
    check("level test can be skipped", r.status_code == 200
          and (r.get_json() or {}).get("redirect", "").endswith("/dashboard"))
    check("skipping is stored", (store.get_profile(uid).get("level_test") or {})
          .get("status") == "skipped")

    # --- authenticated browsing --------------------------------------------
    r = c.get("/dashboard")
    check("dashboard reachable with cookie", r.status_code == 200)
    check("dashboard greets user", USERNAME.encode() in r.data)
    check("dashboard draws the ladder", b"level-card" in r.data)
    check("login redirects when signed in", c.get("/login").status_code == 302)

    # --- the level ladder ---------------------------------------------------
    # The rule itself is tested offline in test_progress.py; what is checked
    # here is the round trip through Firestore and the routes that enforce it.
    check("a new account has no progress", store.progress_counts(uid) == {})
    r = c.get("/practice?chapter=10&difficulty=easy")
    check("practice at a locked chapter bounces", r.status_code == 302
          and r.headers["Location"].endswith("/dashboard"))
    r = c.get("/practice?chapter=5&difficulty=hard")
    check("practice at a locked band bounces", r.status_code == 302
          and r.headers["Location"].endswith("/dashboard"))

    # Two openings and a solve of the same question: one document, one solve.
    store.record_attempt(uid, "test_progress_1", 5, "easy")
    store.record_attempt(uid, "test_progress_1", 5, "easy")
    first = store.record_solved(uid, "test_progress_1", 5, "easy")
    again = store.record_solved(uid, "test_progress_1", 5, "easy")
    cell = store.progress_counts(uid)[5]["easy"]
    check("openings counted", cell["attempts"] == 2)
    check("one question, one solve", cell["solved"] == 1 and cell["seen"] == 1)
    check("first solve reported as first", first is True)
    check("re-solving is not a new solve", again is False)
    profile = store.get_profile(uid)
    check("profile solved count moved", profile["stats"]["solved"] == 1)
    check("profile attempted count moved", profile["stats"]["attempted"] == 2)

    # Enough distinct solves to clear the band, and medium opens.
    for n in range(2, progress.TO_CLEAR + 1):
        store.record_solved(uid, "test_progress_%d" % n, 5, "easy")
    counts = store.progress_counts(uid)
    check("clearing easy opens medium", progress.is_unlocked(counts, 5, "medium"))
    check("clearing easy leaves hard shut",
          not progress.is_unlocked(counts, 5, "hard"))
    check("clearing easy leaves chapter 10 shut",
          not progress.is_unlocked(counts, 10))
    r = c.get("/dashboard")
    check("dashboard says the level is cleared", b"Cleared" in r.data)

    store.clear_progress(uid)
    check("progress can be cleared", store.progress_counts(uid) == {})

    # --- username collision -------------------------------------------------
    r = c.get("/api/username-available?u=" + USERNAME)
    check("taken username reported taken", r.get_json()["available"] is False)
    r = c.get("/api/username-available?u=free_%s" % suffix[:6])
    check("free username reported free", r.get_json()["available"] is True)
    r = c.get("/api/username-available?u=no")
    check("invalid username rejected", r.get_json()["valid"] is False)

    # A second account asking for the same handle gets a suffixed one, not an error.
    email2 = "ilo_test2_%s@example.com" % suffix
    token2 = sign_up(email2, PASSWORD)
    c2 = m.app.test_client()
    r = c2.post("/api/session", json={"idToken": token2, "username": USERNAME})
    body2 = r.get_json() or {}
    check("duplicate handle auto-suffixed",
          r.status_code == 200 and body2.get("username") == USERNAME + "2")

    # --- level test with proofs, on the second account ---------------------
    # Submitting places the account, which would upset the ladder checks the
    # first one has just run, so it is done here.
    import level_test as lt
    uid2 = created_uids[-1]
    r = c2.get("/level-test")
    dealt2 = store.get_level_test_questions(
        store.get_profile(uid2)["level_test"]["questions"])
    kinds = [lt.kind(q) for q in dealt2]
    check("the test ends on Fitch proofs",
          kinds[-sum(lt.FITCH_MIX.values()):] == [lt.FITCH] * sum(lt.FITCH_MIX.values())
          and b"fitch-lines" in r.data)
    answers = {q["id"]: (q["proof"] if lt.kind(q) == lt.FITCH else q["answer"])
               for q in dealt2}
    # Spoil the last proof: its final line is the goal no longer.
    last = dealt2[-1]
    answers[last["id"]] = last["proof"][:-1]
    r = c2.post("/api/level-test/submit", json={"answers": answers})
    body = r.get_json() or {}
    review = {m["id"]: m for m in body.get("review", [])}
    check("submitted proofs are marked",
          r.status_code == 200 and body.get("right") == len(dealt2) - 1)
    check("a broken proof says what is wrong",
          review[last["id"]]["correct"] is False and review[last["id"]]["problems"]
          and review[last["id"]]["proof"])
    stored = store.get_profile(uid2)["level_test"]["answers"]
    check("proof steps are kept with the test",
          stored[dealt2[-2]["id"]][-1]["formula"] == dealt2[-2]["proof"][-1]["formula"])

    # --- profile page -------------------------------------------------------
    check("profile gated when anon",
          m.app.test_client().get("/profile").status_code == 302)
    r = c.get("/profile")
    check("profile renders", r.status_code == 200)
    check("profile shows stored answers", b"Test High School" in r.data)

    names = store.get_client().collection("usernames")
    first_collected = store.get_profile(uid)["demographics"]["collected_at"]
    renamed = USERNAME + "x"
    edit = dict(ABOUT, age=18, school="Another School")
    r = c.post("/api/profile", json={"username": renamed, "about": edit})
    after = store.get_profile(uid)
    check("profile edit saved", r.status_code == 200 and after["username"] == renamed)
    check("rename moves the username index",
          names.document(renamed.lower()).get().to_dict()["uid"] == uid
          and not names.document(USERNAME.lower()).get().exists)
    check("edited answers stored",
          after["demographics"]["age"] == 18
          and after["demographics"]["school"] == "Another School")
    check("first collection time kept",
          after["demographics"]["collected_at"] == first_collected)

    r = c.post("/api/profile", json={"username": USERNAME + "2", "about": edit})
    check("someone else's username refused", r.status_code == 409)
    r = c.post("/api/profile", json={"username": renamed,
                                     "about": dict(edit, nationality="Narnia")})
    check("bad answer refused", r.status_code == 400
          and (r.get_json() or {}).get("field") == "nationality")
    r = m.app.test_client().post("/api/profile", json={"username": renamed})
    check("profile edit needs a session", r.status_code == 401)

    # Back to the original, which the returning-user checks below expect.
    r = c.post("/api/profile", json={"username": USERNAME, "about": edit})
    check("rename back works", r.status_code == 200
          and not names.document(renamed.lower()).get().exists)

    # --- logout -------------------------------------------------------------
    r = c.post("/api/logout")
    check("logout ok", r.status_code == 200)
    check("dashboard gated after logout", c.get("/dashboard").status_code == 302)

    # --- returning user -----------------------------------------------------
    id_token = sign_in(EMAIL, PASSWORD)
    c3 = m.app.test_client()
    r = c3.post("/api/session", json={"idToken": id_token})
    body3 = r.get_json() or {}
    check("returning login works", r.status_code == 200)
    check("not marked as new", body3.get("created") is False)
    check("username unchanged", body3.get("username") == USERNAME)
    check("dashboard reachable again", c3.get("/dashboard").status_code == 200)

    # --- rejected tokens ----------------------------------------------------
    r = m.app.test_client().post("/api/session", json={"idToken": "not-a-token"})
    check("garbage token rejected", r.status_code == 401)
    r = m.app.test_client().post("/api/session", json={})
    check("missing token rejected", r.status_code == 400)
    c4 = m.app.test_client()
    c4.set_cookie("__session", "forged", domain="localhost")
    check("forged cookie rejected", c4.get("/dashboard").status_code == 302)

finally:
    for uid in created_uids:
        try:
            store.delete_profile(uid)
        except Exception as exc:
            print("cleanup(profile)", uid, exc)
        try:
            fb_auth.delete_user(uid)
        except Exception as exc:
            print("cleanup(auth)", uid, exc)
    print("\ncleaned up %d test user(s)" % len(created_uids))

failed = [label for label, ok in checks if not ok]
print("%d/%d passed" % (len(checks) - len(failed), len(checks)))
if failed:
    print("FAILED:", ", ".join(failed))
    raise SystemExit(1)
