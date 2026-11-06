// Firebase Authentication for the login and register pages.
//
// Passwords are handled entirely by Firebase and never touch the Flask server.
// After a successful sign-in the ID token is posted to /api/session, which
// verifies it with the Admin SDK and returns an HttpOnly session cookie.

import { initializeApp } from "https://www.gstatic.com/firebasejs/12.5.0/firebase-app.js";
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  getRedirectResult,
  GoogleAuthProvider,
  sendPasswordResetEmail,
  updateProfile,
  signOut,
  setPersistence,
  browserLocalPersistence,
} from "https://www.gstatic.com/firebasejs/12.5.0/firebase-auth.js";

const config = window.__ILO.firebaseConfig;
const app = initializeApp(config);
const auth = getAuth(app);
auth.useDeviceLanguage();

const googleProvider = new GoogleAuthProvider();

// --- helpers ----------------------------------------------------------------

const $ = (id) => document.getElementById(id);

function showError(message) {
  const box = $("auth-error");
  if (!box) return;
  box.textContent = message;
  box.hidden = !message;
  if (message) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function setBusy(busy) {
  document.querySelectorAll("form button, .btn-google").forEach((el) => {
    el.disabled = busy;
  });
  const submit = $("submit-btn");
  if (submit) {
    if (busy) {
      submit.dataset.label = submit.textContent;
      submit.textContent = "Please wait…";
    } else if (submit.dataset.label) {
      submit.textContent = submit.dataset.label;
    }
  }
}

// Firebase error codes are precise but not friendly. Translate the ones a
// user can actually act on and fall back to the raw message otherwise.
const MESSAGES = {
  "auth/invalid-credential": "Incorrect email or password.",
  "auth/invalid-email": "That doesn't look like a valid email address.",
  "auth/user-not-found": "Incorrect email or password.",
  "auth/wrong-password": "Incorrect email or password.",
  "auth/email-already-in-use": "An account with that email already exists.",
  "auth/weak-password": "Password must be at least 6 characters.",
  "auth/too-many-requests": "Too many attempts. Wait a moment and try again.",
  "auth/popup-closed-by-user": "Google sign-in was cancelled.",
  "auth/cancelled-popup-request": "Google sign-in was cancelled.",
  "auth/network-request-failed": "Network problem. Check your connection and try again.",
  "auth/account-exists-with-different-credential":
    "That email is already registered with a different sign-in method.",
  "auth/operation-not-allowed":
    "That sign-in method is not enabled for this Firebase project.",
  "auth/unauthorized-domain":
    "This domain is not in the Firebase authorised domains list.",
};

function describe(error) {
  return MESSAGES[error?.code] || error?.message || "Something went wrong.";
}

/** Trade the Firebase ID token for a server session cookie, then continue. */
async function startSession(user, username) {
  const idToken = await user.getIdToken(/* forceRefresh */ true);
  const response = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idToken, username: username || null }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // The server would not accept the sign-in, so don't leave the browser
    // holding a session the server doesn't know about.
    await signOut(auth).catch(() => {});
    throw new Error(data.error || "Could not start your session.");
  }
  window.location.assign(data.redirect || "/dashboard");
}

// --- Google sign-in ---------------------------------------------------------

async function googleSignIn() {
  showError("");
  setBusy(true);
  try {
    const result = await signInWithPopup(auth, googleProvider);
    await startSession(result.user);
  } catch (error) {
    if (error?.code === "auth/popup-blocked") {
      // Popups blocked: fall back to a full-page redirect.
      sessionStorage.setItem("ilo:redirecting", "1");
      await signInWithRedirect(auth, googleProvider);
      return;
    }
    setBusy(false);
    showError(describe(error));
  }
}

/** Completes the redirect fallback above after the page reloads. */
async function resumeRedirect() {
  if (!sessionStorage.getItem("ilo:redirecting")) return false;
  sessionStorage.removeItem("ilo:redirecting");
  try {
    const result = await getRedirectResult(auth);
    if (result?.user) {
      setBusy(true);
      await startSession(result.user);
      return true;
    }
  } catch (error) {
    showError(describe(error));
  }
  return false;
}

// --- page wiring ------------------------------------------------------------

async function init() {
  await setPersistence(auth, browserLocalPersistence).catch(() => {});

  if (await resumeRedirect()) return;

  // If the server says nobody is signed in but the browser still holds a
  // Firebase session (expired cookie, logout in another tab), clear it so the
  // two sides agree.
  if (!window.__ILO.loggedIn && auth.currentUser) {
    await signOut(auth).catch(() => {});
  }

  $("google-btn")?.addEventListener("click", googleSignIn);

  const loginForm = $("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      showError("");
      setBusy(true);
      try {
        const cred = await signInWithEmailAndPassword(
          auth, $("email").value.trim(), $("password").value
        );
        await startSession(cred.user);
      } catch (error) {
        setBusy(false);
        showError(describe(error));
      }
    });

    $("reset-link")?.addEventListener("click", async (event) => {
      event.preventDefault();
      const email = $("email").value.trim();
      if (!email) {
        showError("Enter your email address first, then click reset.");
        return;
      }
      try {
        await sendPasswordResetEmail(auth, email);
        showError("");
        const note = $("auth-note");
        note.textContent = "Password reset email sent to " + email + ".";
        note.hidden = false;
      } catch (error) {
        showError(describe(error));
      }
    });
  }

  const registerForm = $("register-form");
  if (registerForm) {
    registerForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      showError("");

      const username = $("username").value.trim();
      const email = $("email").value.trim();
      const password = $("password").value;

      if (!/^[A-Za-z0-9_]{3,20}$/.test(username)) {
        showError("Username must be 3-20 characters: letters, numbers, underscores.");
        return;
      }
      if (password.length < 8) {
        showError("Password must be at least 8 characters long.");
        return;
      }
      if (password !== $("confirm").value) {
        showError("Passwords do not match.");
        return;
      }

      setBusy(true);
      try {
        const cred = await createUserWithEmailAndPassword(auth, email, password);
        await updateProfile(cred.user, { displayName: username });
        await startSession(cred.user, username);
      } catch (error) {
        setBusy(false);
        showError(describe(error));
      }
    });
  }
}

init();

// --- logout -----------------------------------------------------------------

document.getElementById("logout-btn")?.addEventListener("click", async (event) => {
  event.preventDefault();
  await signOut(auth).catch(() => {});
  await fetch("/api/logout", { method: "POST" }).catch(() => {});
  window.location.assign("/");
});
