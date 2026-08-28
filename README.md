# ILO Practice

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
```

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
| `PORT` | Defaults to 5001 (macOS uses 5000 for AirPlay) |

## Tests

```bash
python3 test_app.py
```

Runs end to end against the real Firebase project: it signs up and signs in
through the same REST endpoints the JS SDK uses, exchanges tokens for session
cookies, checks the Firestore writes, and deletes the test users afterwards.

## Files

| File | Role |
|---|---|
| `app.py` | Routes, session cookies, auth API |
| `firestore_db.py` | Firestore data layer and Admin SDK setup |
| `static/auth.js` | Firebase Auth in the browser (ES module) |
| `static/main.js` | Password strength, username availability, show/hide |
| `templates/` | Jinja templates |
| `firebase_web_config.json` | Public web app config |
| `firestore.rules` | Locks Firestore to Admin SDK access only |
| `test_app.py` | End-to-end tests |
