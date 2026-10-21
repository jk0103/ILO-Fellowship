// The level test: intro, one question at a time, then the result.
//
// The page carries the dealt questions without their answers. Nothing is
// marked here: the answers are posted to /api/level-test/submit, which marks
// them against the questions stored on the profile and sends back the level,
// and only then the right answers for the review.

(function () {
  const questions = (window.__ILO_TEST && window.__ILO_TEST.questions) || [];
  const $ = (id) => document.getElementById(id);
  if (!questions.length || !$("test-start")) return;

  const answers = {};          // question id -> chosen index
  let index = 0;

  function show(screen) {
    ["test-intro", "test-question", "test-result"].forEach((id) => {
      $(id).hidden = id !== screen;
    });
    showError("");
  }

  function showError(message) {
    const box = $("test-error");
    box.textContent = message;
    box.hidden = !message;
  }

  // The bar, Back and Next/Submit. Picking a choice only updates these, so
  // the radio buttons are not rebuilt under a keyboard user's focus.
  function refresh() {
    const q = questions[index];
    // The bar counts questions answered, not the one on screen, so it reaches
    // the end only when the last answer is in.
    const answered = questions.filter((x) => x.id in answers).length;
    $("test-meter").setAttribute("aria-valuenow", answered);
    $("test-meter-fill").style.width = (100 * answered / questions.length) + "%";

    $("test-back").disabled = index === 0;
    const next = $("test-next");
    next.textContent = index === questions.length - 1 ? "Submit" : "Next";
    next.disabled = !(q.id in answers);
  }

  function render() {
    const q = questions[index];

    $("test-count").textContent = "Question " + (index + 1) + " of " + questions.length;
    const band = $("test-band");
    band.textContent = q.difficulty;
    band.className = "badge badge-" + q.difficulty;

    $("test-prompt").textContent = q.prompt;
    const list = $("test-choices");
    list.replaceChildren();
    q.choices.forEach((text, i) => {
      const label = document.createElement("label");
      label.className = "test-choice";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "choice";
      input.value = String(i);
      input.checked = answers[q.id] === i;
      input.addEventListener("change", () => {
        answers[q.id] = i;
        refresh();
      });
      const letter = document.createElement("span");
      letter.className = "test-letter";
      letter.textContent = String.fromCharCode(65 + i);
      const body = document.createElement("span");
      body.textContent = text;
      label.append(input, letter, body);
      list.append(label);
    });
    refresh();
  }

  async function submit() {
    const next = $("test-next");
    next.disabled = true;
    $("test-back").disabled = true;
    next.textContent = "Scoring…";
    try {
      const response = await fetch("/api/level-test/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Could not submit the test.");
      result(data);
    } catch (error) {
      render();
      showError(error.message);
    }
  }

  function bandName(level) {
    return "Chapter " + level.chapter + " " + level.band;
  }

  function result(data) {
    $("result-level").textContent = data.level;
    $("result-score").textContent =
      "You answered " + data.right + " of " + data.total + " correctly, " +
      "for " + data.earned + " of " + data.possible + " points. " +
      "Harder questions are worth more.";

    const unlocked = $("result-unlocked");
    unlocked.replaceChildren();
    data.unlocked.forEach((level) => {
      const item = document.createElement("li");
      const badge = document.createElement("span");
      badge.className = "badge badge-" + level.band;
      badge.textContent = level.band;
      item.append(badge, " Chapter " + level.chapter);
      item.title = bandName(level);
      unlocked.append(item);
    });

    const review = $("result-review");
    review.replaceChildren();
    const byId = Object.fromEntries(questions.map((q) => [q.id, q]));
    data.review.forEach((mark) => {
      const q = byId[mark.id];
      if (!q) return;
      const item = document.createElement("li");
      item.className = mark.correct ? "is-right" : "is-wrong";
      const prompt = document.createElement("p");
      prompt.className = "test-review-prompt";
      prompt.textContent = (mark.correct ? "✓ " : "✗ ") + q.prompt;
      const answer = document.createElement("p");
      answer.className = "hint";
      answer.textContent = mark.correct
        ? "Your answer: " + q.choices[mark.answer]
        : "Your answer: " + (mark.chosen == null ? "none" : q.choices[mark.chosen]) +
          ". Correct: " + q.choices[mark.answer];
      const why = document.createElement("p");
      why.className = "hint";
      why.textContent = mark.explanation;
      item.append(prompt, answer, why);
      review.append(item);
    });

    if (data.redirect) $("result-continue").href = data.redirect;
    show("test-result");
    $("result-level").focus();
  }

  $("test-start").addEventListener("click", () => {
    index = 0;
    show("test-question");
    render();
  });

  $("test-skip").addEventListener("click", async () => {
    $("test-skip").disabled = true;
    try {
      const response = await fetch("/api/level-test/skip", { method: "POST" });
      const data = await response.json().catch(() => ({}));
      window.location.assign(data.redirect || "/dashboard");
    } catch (error) {
      $("test-skip").disabled = false;
      showError("Could not skip the test. Check your connection and try again.");
    }
  });

  $("test-back").addEventListener("click", () => {
    if (index > 0) {
      index -= 1;
      render();
    }
  });

  $("test-next").addEventListener("click", () => {
    if (!(questions[index].id in answers)) return;
    if (index === questions.length - 1) {
      submit();
    } else {
      index += 1;
      render();
    }
  });
})();
