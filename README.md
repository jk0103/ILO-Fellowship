# ILO Bank

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

`/fitch` is a natural-deduction proof editor for the Stanford intro-logic Fitch
system: the propositional rules of Chapter 5 and the quantifier rules of
Chapter 10. It needs no account and no server: the parser, the scope analysis,
the rules, and the checker all live in `static/fitch.js`.

It works the way the Stanford tool does. Tick the lines you want to work from,
press a rule button, and the rule is *applied* — the resulting lines are
appended, already justified. And Elimination on `p ∧ q` gives you two lines,
`p` and `q`; Biconditional Elimination gives you both implications. Nothing is
typed except premises, assumptions, the target of Or Introduction, and the term
or sentence a quantifier rule needs, each of which opens a small entry bar.

Order matters where the rule cares: And Introduction builds its conjunction in
the order you ticked the boxes, so ticking `q` then `p` turns `p ∧ q` into
`q ∧ p`.

The proof grows downward, so a rule always adds to the subproof you are
currently inside. Assumption opens one; Implication Introduction discharges it
and closes it, emitting one level out. Cited lines have to be in scope — a
line's own subproof or an enclosing one, never one that has already closed.

Formulas accept ASCII or symbols (`~ & | => <=>` or `¬ ∧ ∨ ⇒ ⇔`) and are
displayed as symbols.

### Quantifiers

Quantifiers are written the way the Stanford tool writes them:

| Written | Means |
|---|---|
| `AX: p(X)` | ∀x.p(x) — every X is p |
| `EX: p(X)` | ∃x.p(x) — some X is p |

**Variables are uppercase.** That one convention does the work: a lowercase name
is an object constant or a placeholder, and a term is *ground* exactly when no
uppercase name appears in it — which is the side condition Universal Elimination
and Existential Introduction turn on. A quantifier binds as tightly as `~`, so
`AX: p(X) & AX: q(X)` is a conjunction of two quantified sentences and a wider
scope is written `AX: (p(X) & q(X))`. The Unicode forms `∀x.p(x)` and `∃x.p(x)`
are accepted on input, which is how a generated Chapter 10 question opens in the
editor; they are normalized to uppercase variables and shown in the tool's own
notation.

The four rules, and what each asks for:

| Rule | Select | Type | Gives |
|---|---|---|---|
| Universal Elimination | one `AX: φ` | a ground term | φ with that term in for X |
| Universal Introduction | one line | the `AX: …` to introduce | that sentence |
| Existential Introduction | one line | the `EX: …` to introduce | that sentence |
| Existential Elimination | `EX: φ` and `AX: (φ ⇒ ψ)` | — | ψ |

Universal Elimination asks only for the term, since the instance follows from
it. The two introductions ask for the sentence, because you choose the variable
— and, for Existential Introduction, which occurrences of the term to
generalize, since the chapter allows one, some, or all of them. Existential
Elimination asks for nothing: its two lines determine the conclusion.

The restrictions the chapter places on these rules are enforced, so the editor
refuses the mistakes it warns about. Universal Introduction will not generalize
a name that a premise or a still-open assumption has pinned down — the
placeholder has to be arbitrary. Existential Introduction will not generalize a
bound variable. Existential Elimination will not fire when its variable occurs
free in the conclusion.

`static/fitch_tests.html` exercises all of this against the real script: run the
app and open `/static/fitch_tests.html`. It checks the notation, each quantifier
rule in isolation, and then drives the editor itself the way the buttons do,
building the chapter's existential pattern end to end.

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

The page carries a **chapter** selector — Chapter 5 (propositional) or Chapter 10
(relational). The chapter is a mode, not a filter: it picks which generator runs,
and the saved list below it shows only that chapter's questions, with the
easy/medium/hard filter working within it. `app.py` keeps a `CHAPTERS` registry
mapping each number to its checker, its generator and the way that generator
wants to be called, because the two differ in all three. Chapter 5 is the
default, so an old link with no `?chapter=` still lands where it used to.

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

`seed_questions.py` loads the starter questions that ship as JSON — Chapter 5
from the five hand-written ones in `seed_questions.json`, Chapter 10 from
`ch10_questions.json` — checking every proof with that chapter's own checker
first. It is safe to re-run: a question's document id is a fingerprint of its
premises and goal, so a second run updates the same documents rather than
adding more.

```bash
export OPENAI_API_KEY=...
python3 fitch_generator.py -n 3 -d medium --proofs   # CLI, prints only
python3 seed_questions.py --dry-run                  # verify the seed data
python3 seed_questions.py --chapter 10               # load Chapter 10
python3 seed_questions.py --chapter all              # load both
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
That is why a medium or hard run from the web page can come back with fewer
questions than were asked for; the page says so when it does.

Chapter 10 is reached from the same `/generate` page by picking it in the
chapter selector. Two things differ from Chapter 5 once a question is on screen:

- An exercise that fixes its language names its object constants, and the card
  and the practice editor both print them, since Domain Closure means nothing
  without them.
- A proof answered by **Domain Closure** gets no *Practise this* link. The
  editor has buttons for the other seventeen rules but not that one, so the card
  offers the worked proof and says why.

Where Chapter 5 repeats itself, `fitch_generator` catches it inside a single
call. Chapter 10 draws on a much smaller stock of arguments, so the route hands
its generator everything already saved for that chapter and the prompt asks for
something else — which is why `/generate` reads the stored questions before
calling the model, but only for Chapter 10.

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
    chapter       number           5 (propositional) or 10 (relational)
    premises      array of string
    goal          string
    constants     array of string  object constants the language is limited to;
                                   empty unless the exercise declares them
    hint          string
    proof         array of map     the worked answer, one map per line
    line_count    number           len(proof)
    difficulty    string           easy / medium / hard, derived from line_count
    source        string           "generated" or "seed"
    created_by    string or null   uid of whoever generated it
    created_at    timestamp
```

A proof line is `{formula, rule, depth, refs, subref}`: `rule` is a rule id —
one of the eleven propositional ones, or one of Chapter 10's five quantifier
rules — `depth` is the subproof nesting level, `refs` are 1-based line numbers,
and `subref` is `[assumption line, consequent line]` for Implication
Introduction.

Because the document id is a fingerprint, generating the same exercise twice
updates one document rather than accumulating duplicates. Chapter 5 fingerprints
are the bare digest they have always been, so documents written before chapters
existed keep their ids and the links into them still work; Chapter 10 mixes the
number into the digest, which is what stops a relational exercise from ever
colliding with a propositional one. A document with no `chapter` field is read
as Chapter 5.

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
python3 seed_questions.py --chapter all --dry-run
python3 test_ch10_checker.py
```

The browser editor has its own suite, which needs a browser rather than Python:
start the app and open `/static/fitch_tests.html`.

`test_ch10_checker.py` runs offline, with no key and no network. It verifies the
proofs Chapter 10 works through in its own text and refuses the unsound
patterns the chapter warns against.

## Look and feel

The site wears the ILO's own colours on a white background, and
`static/style.css` gives each one a single job so a new page never has to guess
which to reach for:

| Token | Colour | Used for |
|---|---|---|
| `--red` | `#a4161a` | Identity only — the nav bar, page headings, every third card, the `hard` band |
| `--orange` / `--orange-deep` | `#ed7a1b` / `#b45309` | Highlight and the secondary call to action — the nav's sign-up button, the eyebrow, every third card, the loaded-question edge, the `medium` band |
| `--blue` | `#297197` | The primary action and every affordance — primary buttons, links, focus rings, scope bars, selected lines, filter chips, the `easy` band |

The three are kept deliberately apart, and the split matters in two places:

- **Red is identity, not action.** Primary buttons are blue. Red on a button
  plus red in the bar plus red headings makes a page that is only red.
- **Orange sits at hue 26°, red at 358°.** An earlier coral at hue 10° was close
  enough to red that the two read as one colour, which is also why the `medium`
  and `hard` badges were hard to tell apart. The bright orange fills shapes; the
  deep one is used wherever orange is text or sits behind white text.

The difficulty badges are filled tints rather than outlines — at that size a pill
of colour separates the three bands far better than a hairline and a word.

Every page carries all three. The bar keeps ordinary links — colour arrives on
hover, as an underline in each link's own accent, lightened because the body's
orange and blue are too dark to register against the red. The main block on a
page (the auth card, the proof board) is topped with a three-colour stripe, and
card rows cycle blue → red → orange, the way the ILO home page tints its three
day-cards.

Red doubles as the error colour, so alerts are drawn as a tinted block with dark
red text rather than as brand-red type, which keeps the two readings apart.
Success keeps a teal (`#0e8a6f`), the colour of the ILO site's own Register
button.

Every text-on-background pair clears WCAG AA (4.5:1) — badges, chips and the
links inside cards included.

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
| `seed_questions.py` | Loads either chapter's starter questions into Firestore |
| `seed_questions.json` | The five hand-written Chapter 5 starters and their proofs |
| `ch10_questions.json` | The Chapter 10 starters, written by `ch10_generator.py` |
| `static/fitch_tests.html` | Browser tests for the editor; open `/static/fitch_tests.html` |
| `static/style.css` | The whole stylesheet; the palette is the `:root` block at the top |
| `static/generate.js` | The Generate page |
| `static/auth.js` | Firebase Auth in the browser (ES module) |
| `static/main.js` | Password strength, username availability, show/hide |
| `templates/` | Jinja templates |
| `firebase_web_config.json` | Public web app config |
| `firestore.rules` | Locks Firestore to Admin SDK access only |
| `test_app.py` | End-to-end tests |
| `test_ch10_checker.py` | Offline tests for the Chapter 10 checker |
