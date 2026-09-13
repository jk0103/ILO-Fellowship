/* The Generate page.
 *
 * Asks the server for new exercises, then lists what is stored. The server
 * verifies every proof before saving, so anything shown here has been checked;
 * this file only renders.
 *
 * The chapter selector picks which generator runs and which saved questions are
 * listed: Chapter 5 is propositional, Chapter 10 adds the quantifier rules.
 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const RULES = {
    premise: "Premise", assume: "Assumption", reit: "Reiteration",
    ai: "And Introduction", ae: "And Elimination",
    oi: "Or Introduction", oe: "Or Elimination",
    ni: "Negation Introduction", ne: "Negation Elimination",
    ii: "Implication Introduction", ie: "Implication Elimination",
    bi: "Biconditional Introduction", be: "Biconditional Elimination",
    // Chapter 10.
    ue: "Universal Elimination", ui: "Universal Introduction",
    ei: "Existential Introduction", ee: "Existential Elimination",
    dc: "Domain Closure",
  };

  // Domain Closure is the one rule the practice editor has no button for, so a
  // proof that needs it can be read here but not worked through there.
  const NO_EDITOR_RULE = "dc";

  const CHAPTERS = window.__ILO_CHAPTERS || [];

  let band = "";
  let chapter = 5;   // set from the selector in init()

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // The proof is rendered as a table so the indent bars, formulas and
  // justifications line up the way they do in the chapter.
  function proofTable(proof) {
    const table = el("table", "proof");
    proof.forEach((step, i) => {
      const row = el("tr");
      row.appendChild(el("td", "proof-num", (i + 1) + "."));

      const cell = el("td", "proof-formula");
      const depth = step.depth || 0;
      for (let d = 0; d < depth; d++) cell.appendChild(el("span", "proof-bar"));
      cell.appendChild(el("span", step.rule === "assume" ? "proof-assume" : "", step.formula));
      row.appendChild(cell);

      let just = RULES[step.rule] || step.rule;
      if (step.subref) just += ": " + step.subref[0] + "–" + step.subref[1];
      else if (step.refs && step.refs.length) just += ": " + step.refs.join(", ");
      row.appendChild(el("td", "proof-just", just));
      table.appendChild(row);
    });
    return table;
  }

  // The rules a proof actually uses, in the order they first appear, as the
  // short labels the chapter uses for them.
  function rulesUsed(proof) {
    const seen = [];
    (proof || []).forEach((step) => {
      if (step.rule === "premise" || step.rule === "assume") return;
      if (seen.indexOf(step.rule) === -1) seen.push(step.rule);
    });
    return seen;
  }

  function usesRule(proof, rule) {
    return (proof || []).some((step) => step.rule === rule);
  }

  function card(question) {
    const article = el("article", "card gen-card");

    const head = el("div", "gen-card-head");
    head.appendChild(el("span", "badge badge-" + question.difficulty, question.difficulty));
    head.appendChild(el("span", "hint", question.line_count + " lines"));
    const used = rulesUsed(question.proof);
    if (used.length) {
      head.appendChild(el("span", "hint",
        used.map((r) => RULES[r] || r).join(", ")));
    }
    article.appendChild(head);

    article.appendChild(el("p", "gen-statement", question.statement));
    if (question.constants && question.constants.length) {
      article.appendChild(el("p", "hint", "The language has just these object "
        + "constants: " + question.constants.join(", ") + "."));
    }
    if (question.hint) article.appendChild(el("p", "hint", "Hint: " + question.hint));

    // A Domain Closure proof has no path through the editor, so offer the
    // worked answer instead of a link that would only strand the reader.
    const workable = !usesRule(question.proof, NO_EDITOR_RULE);

    const actions = el("div", "gen-card-actions");
    if (workable) {
      const practise = el("a", "btn btn-primary", "Practise this");
      practise.href = window.__ILO_FITCH_URL + "?q=" + encodeURIComponent(question.id);
      actions.appendChild(practise);
    }

    const toggle = el("button", "btn btn-ghost", "Show answer");
    toggle.type = "button";
    actions.appendChild(toggle);
    article.appendChild(actions);

    if (!workable) {
      article.appendChild(el("p", "hint", "This one is answered with Domain "
        + "Closure, which the practice editor has no button for — read the "
        + "worked proof instead."));
    }

    const answer = el("div", "gen-answer");
    answer.hidden = true;
    answer.appendChild(proofTable(question.proof || []));
    article.appendChild(answer);

    toggle.addEventListener("click", () => {
      answer.hidden = !answer.hidden;
      toggle.textContent = answer.hidden ? "Show answer" : "Hide answer";
    });
    return article;
  }

  function fill(target, questions, emptyText) {
    target.textContent = "";
    if (!questions.length) {
      target.appendChild(el("p", "hint", emptyText));
      return;
    }
    questions.forEach((q) => target.appendChild(card(q)));
  }

  async function loadSaved() {
    const list = $("#gen-list");
    try {
      const url = "/api/questions?chapter=" + chapter +
        (band ? "&difficulty=" + band : "");
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not load questions.");
      // A slow request for one chapter must not overwrite a later one.
      if (data.chapter !== undefined && Number(data.chapter) !== chapter) return;
      const scope = "Chapter " + chapter + " ";
      fill(list, data.questions, band
        ? "No " + band + " " + scope + "questions saved yet."
        : "No " + scope + "questions saved yet. Generate one above.");
      const c = data.counts || {};
      $("#gen-counts").textContent =
        (c.total || 0) + " saved for Chapter " + chapter + " · " +
        (c.easy || 0) + " easy · " + (c.medium || 0) + " medium · " +
        (c.hard || 0) + " hard";
    } catch (err) {
      list.textContent = "";
      list.appendChild(el("p", "hint danger", err.message));
    }
  }

  async function run() {
    const button = $("#gen-run");
    const status = $("#gen-status");
    button.disabled = true;
    status.className = "hint";
    status.textContent = "Writing and checking proofs… this takes a moment.";

    try {
      const res = await fetch("/api/questions/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chapter: chapter,
          difficulty: $("#gen-difficulty").value,
          count: Number($("#gen-count").value),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Generation failed.");

      $("#gen-results").hidden = false;
      fill($("#gen-new"), data.questions, "Nothing came back.");
      const asked = $("#gen-difficulty").value;
      const wanted = Number($("#gen-count").value);
      const got = data.questions.length;
      const offBand = asked && data.questions.some((q) => q.difficulty !== asked);
      status.textContent = "Saved " + got + " question" +
        (got === 1 ? "" : "s") + "." +
        (got < wanted ? " The rest did not pass the checker and were dropped." : "") +
        (offBand ? " Some proofs came out a different length than asked for, so"
                 + " they are filed under the band they actually landed in." : "");
      loadSaved();
    } catch (err) {
      status.className = "hint danger";
      status.textContent = err.message;
    } finally {
      button.disabled = false;
    }
  }

  function showBlurb() {
    const spec = CHAPTERS.filter((c) => Number(c.number) === chapter)[0];
    let text = spec ? spec.blurb : "";
    if (chapter === 10) {
      text += " Long relational proofs are where the model struggles, so a"
        + " medium or hard run may come back with fewer than you asked for.";
    }
    $("#gen-blurb").textContent = text;
  }

  function init() {
    if (!$("#gen-run")) return;
    const picker = $("#gen-chapter");
    chapter = Number(picker.value) || chapter;
    showBlurb();

    picker.addEventListener("change", () => {
      chapter = Number(picker.value);
      showBlurb();
      // The two chapters share nothing, so drop what the last one produced.
      $("#gen-results").hidden = true;
      $("#gen-new").textContent = "";
      $("#gen-status").textContent = "";
      loadSaved();
    });

    $("#gen-run").addEventListener("click", run);
    $("#gen-filters").addEventListener("click", (ev) => {
      const button = ev.target.closest("[data-band]");
      if (!button) return;
      band = button.dataset.band;
      $("#gen-filters").querySelectorAll("[data-band]").forEach(
        (b) => b.classList.toggle("is-on", b === button));
      loadSaved();
    });
    loadSaved();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
