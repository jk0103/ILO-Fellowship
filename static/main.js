// Progressive form polish. Sign-in itself lives in auth.js.

// Show/hide password toggles
document.querySelectorAll(".toggle-pw").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var input = document.getElementById(btn.dataset.target);
    var showing = input.type === "text";
    input.type = showing ? "password" : "text";
    btn.textContent = showing ? "Show" : "Hide";
    btn.setAttribute("aria-label", showing ? "Show password" : "Hide password");
  });
});

var registerForm = document.getElementById("register-form");
if (registerForm) {
  var username = document.getElementById("username");
  var usernameHint = document.getElementById("username-hint");
  var pw = document.getElementById("password");
  var confirmPw = document.getElementById("confirm");
  var bar = document.getElementById("strength-bar");
  var strengthText = document.getElementById("strength-text");
  var matchText = document.getElementById("match-text");

  // --- live username availability ---
  var DEFAULT_HINT = usernameHint.textContent;
  var debounce;

  username.addEventListener("input", function () {
    clearTimeout(debounce);
    var value = username.value.trim();
    usernameHint.className = "hint";
    if (!/^[A-Za-z0-9_]{3,20}$/.test(value)) {
      usernameHint.textContent = DEFAULT_HINT;
      return;
    }
    usernameHint.textContent = "Checking…";
    debounce = setTimeout(function () {
      fetch("/api/username-available?u=" + encodeURIComponent(value))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (username.value.trim() !== value) return;  // typed on since
          if (data.available) {
            usernameHint.textContent = value + " is available.";
            usernameHint.className = "hint ok-hint";
          } else {
            usernameHint.textContent = value + " is already taken.";
            usernameHint.className = "hint error-hint";
          }
        })
        .catch(function () { usernameHint.textContent = DEFAULT_HINT; });
    }, 350);
  });

  // --- password strength ---
  function score(value) {
    var s = 0;
    if (value.length >= 8) s++;
    if (value.length >= 12) s++;
    if (/[A-Z]/.test(value) && /[a-z]/.test(value)) s++;
    if (/\d/.test(value)) s++;
    if (/[^A-Za-z0-9]/.test(value)) s++;
    return s;
  }

  var LEVELS = [
    { width: "0%", color: "#ff6b6b", label: "At least 8 characters." },
    { width: "20%", color: "#ff6b6b", label: "Weak password." },
    { width: "40%", color: "#ffa94d", label: "Fair password." },
    { width: "60%", color: "#ffd43b", label: "Good password." },
    { width: "80%", color: "#4ade80", label: "Strong password." },
    { width: "100%", color: "#4ade80", label: "Very strong password." }
  ];

  pw.addEventListener("input", function () {
    var level = LEVELS[pw.value ? score(pw.value) : 0];
    bar.style.width = level.width;
    bar.style.background = level.color;
    strengthText.textContent = level.label;
    checkMatch();
  });

  function checkMatch() {
    matchText.textContent =
      confirmPw.value && confirmPw.value !== pw.value ? "Passwords do not match." : "";
  }
  confirmPw.addEventListener("input", checkMatch);
}
