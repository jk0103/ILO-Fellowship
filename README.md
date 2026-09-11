# ILO Prep

A practice site for International Logic Olympiad problems.

- **Flask** backend
- **Firebase Authentication** for sign-in (email/password + Google)
- **Cloud Firestore** for everything else (profiles, and later problems and attempts)
- Plain HTML/CSS/JS frontend

Project: `ilo-fellowship`

## Running it

```bash
pip3 install -r requirements.txt
python3 app.py
```

Then open http://localhost:5001. The app picks up `./serviceAccountKey.json`
automatically; no environment variables are needed for local development.

## Fitch practice

`/fitch` is a natural-deduction proof editor for the propositional fragment of
the Stanford intro-logic Fitch system. It needs no account and no server: the
parser, the scope analysis, the rules, and the checker all live in
`static/fitch.js`.

It works the way the Stanford tool does. Tick the lines you want to work from,
press a rule button, and the rule is *applied* — the resulting lines are
appended, already justified. And Elimination on `p ∧ q` gives you two lines,
`p` and `q`; Biconditional Elimination gives you both implications. Nothing is
typed except premises, assumptions, and the target of Or Introduction, each of
which opens a small entry bar.

Order matters where the rule cares: And Introduction builds its conjunction in
the order you ticked the boxes, so ticking `q` then `p` turns `p ∧ q` into
`q ∧ p`.

The proof grows downward, so a rule always adds to the subproof you are
currently inside. Assumption opens one; Implication Introduction discharges it
and closes it, emitting one level out. Cited lines have to be in scope — a
line's own subproof or an enclosing one, never one that has already closed.

Formulas accept ASCII or symbols (`~ & | => <=>` or `¬ ∧ ∨ ⇒ ⇔`) and are
displayed as symbols.

Because rules are applied rather than typed, every line is correct when it is
made. The checker still runs over the whole proof on every change, because
Delete can strand the citations of the lines below it; anything stranded turns
red and says so.

## How sign-in works

Passwords never reach the Flask server. Firebase handles them.

1. The browser signs in with the Firebase JS SDK — `signInWithEmailAndPassword`
   or `signInWithPopup(GoogleAuthProvider)`.
2. It posts the resulting **ID token** to `POST /api/session`.
3. Flask verifies that token with the Admin SDK, creates or refreshes the
   Firestore profile, and mints a **session cookie** (5 days, HttpOnly,
   SameSite=Lax, Secure over HTTPS) named `__session`.
4. Every later request verifies that cookie with `verify_session_cookie(check_revoked=True)`.

`GET /logout` clears the cookie; `POST /api/logout` also revokes the user's
refresh tokens so the session cannot be resumed anywhere.

If the server and browser ever disagree — an expired cookie, a logout in
another tab — the client signs itself out on the next page load so the two
sides stay in step.

### Endpoints

| Route | Purpose |
|---|---|
| `POST /api/session` | ID token → session cookie; creates the profile on first sign-in |
| `POST /api/logout` | Clear cookie and revoke refresh tokens |
| `GET /api/username-available?u=` | Live check for the signup form |

## Generating questions

`/generate` writes new exercises with the GPT API and files them by difficulty.
It needs a login and `OPENAI_API_KEY`.

The model is grounded on `Introduction to Logic - Chapter 5.html`, uploaded to
an OpenAI vector store and reached with `file_search`, so the problems it writes
stay inside the eleven rules the chapter teaches. It is asked for a worked proof
along with each problem, in the same line/rule/citation shape the editor uses.

**Nothing the model says is taken on trust.** `fitch_checker.py` is a Python port
of the checker in `static/fitch.js` — same grammar, same rules, same scope
analysis — so it accepts exactly the proofs the editor accepts. Every candidate
has to clear two hurdles before it is stored:

1. the argument must be valid, by truth table (Fitch is complete, so a valid
   argument is a provable one);
2. the proof must pass the checker, line by line.

A proof that fails is handed back to the model with the checker's complaints for
one repair attempt. What still fails is dropped. The route re-checks each proof
a second time immediately before writing it, so an unverified answer cannot
reach Firestore even if the generator changes.

**Difficulty is measured, not claimed.** It comes from the length of the
verified proof: under 10 lines is easy, under 20 is medium, 20 or more is hard.
Asking for a band steers the prompt, but a question whose proof lands elsewhere
is filed under the band it actually reached.

Reductio proofs are long in this system — there is no `false` rule, so every
contradiction routes through Negation Introduction on two implications — which
is why several natural-looking problems come out `hard`.

`seed_questions.py` loads the five hand-written starter questions in
`seed_questions.json`, checking each proof first. It is safe to re-run: a
question's document id is a fingerprint of its premises and goal.

```bash
export OPENAI_API_KEY=...
python3 fitch_generator.py -n 3 -d medium --proofs   # CLI, prints only
python3 seed_questions.py --dry-run                  # verify the seed data
```

## Chapter 10: relational exercises

The same pipeline, one chapter further on. `Introduction to Logic - Chapter 10.html`
covers Fitch proofs for Relational Logic: the eleven propositional rules plus
Universal Elimination, Universal Introduction, Existential Introduction,
Existential Elimination, and Domain Closure. It is uploaded to its own vector
store, and `ch10_generator.py` writes exercises phrased like the chapter's own
Exercise 10.x list.

`ch10_checker.py` is the counterpart to `fitch_checker.py` for that language. It
parses relation constants applied to terms and the two quantifiers — binding as
tightly as `¬`, so `∀x.p(x) ∧ ∀x.q(x)` is a conjunction of two quantified
sentences, exactly as the chapter writes it — and applies all eighteen rules
with the restrictions the chapter places on them: the substituted term must be
ground for Universal Elimination and Existential Introduction, the generalized
placeholder must be arbitrary for Universal Introduction (never a name from a
premise or from an assumption still open), Existential Elimination needs both
`∃ν.φ` and `∀ν.(φ ⇒ ψ)` with `ν` not free in `ψ`, and Domain Closure needs every
instance over a declared finite language.

Relational Logic has no truth table, so there is no validity pre-check here as
there is for Chapter 5. None is needed: Fitch is sound, so a proof whose every
line passes the checker is a proof, and the entailment it claims holds. What the
checker cannot do is rescue a bad proof of a true claim — those are dropped.

Candidates are also dropped when they are a chapter exercise in disguise. The
comparison is on the shape of the argument, blind to the names it uses and to
transposed relation arguments, so "Given ∃x.∀y.r(x,y), prove ∀y.∃x.r(x,y)" is
recognized as Exercise 10.10 rewritten.

```bash
python3 openai_vector_store.py "Introduction to Logic - Chapter 10.html"
python3 ch10_generator.py -n 4 --difficulty easy -o ch10_questions.json
python3 ch10_generator.py -n 3 --difficulty medium -o ch10_questions.json -a
```

`--append` adds to an existing file without repeating what is already in it.
Long relational proofs are where the model struggles: `gpt-4.1` reliably clears
the easy band and rarely survives the checker at medium or harder, most often by
citing into a subproof that has closed. Pass `--model` to try a stronger one.

## Data model

```
users/{uid}                        uid is the Firebase Auth uid
    username      string, unique
    email         string, lowercased
    display_name  string
    photo_url     string or null   (set by Google sign-in)
    providers     array            ["password"] / ["google.com"]
    created_at    timestamp
    last_login    timestamp
    stats         map              solved / attempted / streak

usernames/{username_lower}
    uid           string

questions/{fingerprint}            id is sha256(premises + goal), truncated
    statement     string           the exercise as prose
    premises      array of string
    goal          string
    hint          string
    proof         array of map     the worked answer, one map per line
    line_count    number           len(proof)
    difficulty    string           easy / medium / hard, derived from line_count
    source        string           "generated" or "seed"
    created_by    string or null   uid of whoever generated it
    created_at    timestamp
```

A proof line is `{formula, rule, depth, refs, subref}`: `rule` is one of the
eleven rule ids, `depth` is the subproof nesting level, `refs` are 1-based line
numbers, and `subref` is `[assumption line, consequent line]` for Implication
Introduction.

Because the document id is a fingerprint, generating the same exercise twice
updates one document rather than accumulating duplicates.

Firestore has no unique constraints, so the username is the document id in
`usernames` and is reserved in the *same transaction* that writes the profile.
If a handle collides, the next free variant (`name2`, `name3`, …) is used — so
a Google sign-in never fails just because someone already took that name.

Google sign-in has no username field, so one is derived from the email or
display name and made unique the same way.

## Firebase console settings this relies on

All of these are already enabled on `ilo-fellowship`:

- **Authentication → Sign-in method**: Email/Password, Google
- **Authentication → Authorized domains**: includes `localhost`
- **Firestore**: `(default)` database, native mode
- **Web app** registered (its public config lives in `firebase_web_config.json`)

Before deploying, add your production domain to the authorized domains list.

## Security notes

- `serviceAccountKey.json` is full admin access to the project. It is in
  `.gitignore` — keep it there, and never ship it to the browser.
- `firebase_web_config.json` is **public by design**. It identifies the project
  and grants nothing on its own; access is controlled by Auth and by rules.
- `firestore.rules` denies all direct client access, since the browser only
  talks to Firebase Auth and the backend does all Firestore work through the
  Admin SDK. Deploy it with:

  ```bash
  firebase deploy --only firestore:rules
  ```

- Set `ILO_SECRET_KEY` in production (it signs flash-message cookies):

  ```bash
  ILO_SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 app.py
  ```

## Environment variables

| Variable | Purpose |
|---|---|
| `FIREBASE_CREDENTIALS` | Path to the service-account JSON (default: `./serviceAccountKey.json`) |
| `FIREBASE_CREDENTIALS_JSON` | The JSON itself, for hosts that only offer env vars |
| `FIREBASE_PROJECT_ID` | Overrides the project id in the credentials |
| `FIRESTORE_EMULATOR_HOST` | e.g. `localhost:8080`, to use the local emulator |
| `ILO_SECRET_KEY` | Flask session signing key |
| `OPENAI_API_KEY` | Required by `/generate`; without it the page still lists saved questions. May live in a gitignored `.env`, which `load_env.py` reads |
| `FITCH_VECTOR_STORE_ID` | Vector store holding the chapter (has a default) |
| `FITCH_MODEL` | Defaults to `gpt-4.1`; `ch10_generator.py` reads it too |
| `CH10_VECTOR_STORE_ID` | Vector store holding Chapter 10 (has a default) |
| `PORT` | Defaults to 5001 (macOS uses 5000 for AirPlay) |

## Tests

```bash
python3 test_app.py
```

Runs end to end against the real Firebase project: it signs up and signs in
through the same REST endpoints the JS SDK uses, exchanges tokens for session
cookies, checks the Firestore writes, and deletes the test users afterwards.

The proof checker has no external dependencies, so it can be exercised on its
own:

```bash
python3 seed_questions.py --dry-run
python3 test_ch10_checker.py
```

`test_ch10_checker.py` runs offline, with no key and no network. It verifies the
proofs Chapter 10 works through in its own text and refuses the unsound
patterns the chapter warns against.

## Files

| File | Role |
|---|---|
| `app.py` | Routes, session cookies, auth API |
| `firestore_db.py` | Firestore data layer and Admin SDK setup |
| `fitch_checker.py` | Server-side proof checker, mirroring `static/fitch.js` |
| `fitch_generator.py` | Writes exercises with the GPT API and verifies them |
| `ch10_checker.py` | Proof checker for the relational system of Chapter 10 |
| `ch10_generator.py` | Writes Chapter 10 exercises and verifies them |
| `openai_vector_store.py` | Uploads a chapter and indexes it for `file_search` |
| `load_env.py` | Reads `.env` into the environment, without a dependency |
| `seed_questions.py` / `.json` | The five starter questions and their proofs |
| `static/generate.js` | The Generate page |
| `static/auth.js` | Firebase Auth in the browser (ES module) |
| `static/main.js` | Password strength, username availability, show/hide |
| `templates/` | Jinja templates |
| `firebase_web_config.json` | Public web app config |
| `firestore.rules` | Locks Firestore to Admin SDK access only |
| `test_app.py` | End-to-end tests |
| `test_ch10_checker.py` | Offline tests for the Chapter 10 checker |
