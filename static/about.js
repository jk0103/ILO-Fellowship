// The welcome page's "about you" form. The server checks the answers again
// against the same lists (demographics.py); this only saves a round trip.

(function () {
  var form = document.getElementById("about-form");
  if (!form) return;
  var $ = function (id) { return document.getElementById(id); };

  function fail(message, field) {
    var box = $("about-error");
    box.textContent = message;
    box.hidden = false;
    if (field && $(field)) $(field).focus();
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var about = {
      gender: $("gender").value,
      age: Number($("age").value),
      school: $("school").value.trim(),
      nationality: $("nationality").value,
    };
    var min = Number($("age").min), max = Number($("age").max);
    if (!about.gender) return fail("Please select your gender.", "gender");
    if (!(Number.isInteger(about.age) && about.age >= min && about.age <= max)) {
      return fail("Please enter your age (" + min + "–" + max + ").", "age");
    }
    if (!about.school) return fail("Please enter your school.", "school");
    if (!about.nationality) return fail("Please select your nationality.", "nationality");

    var button = $("about-save");
    button.disabled = true;
    button.textContent = "Saving…";
    fetch("/api/about", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ about: about }),
    })
      .then(function (r) { return r.json().then(function (data) { return [r.ok, data]; }); })
      .then(function (result) {
        if (result[0]) return window.location.assign(result[1].redirect || "/dashboard");
        fail(result[1].error || "Could not save your answers.", result[1].field);
        button.disabled = false;
        button.textContent = "Continue";
      })
      .catch(function () {
        fail("Network problem. Check your connection and try again.");
        button.disabled = false;
        button.textContent = "Continue";
      });
  });
})();
