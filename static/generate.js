/* The Generate page.
 *
 * Asks the server for new exercises, then lists what is stored. The server
 * verifies every proof before saving, so anything shown here has been checked;
 * this file only renders.
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
  };

  let band = "";

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

  function card(question) {
    const article = el("article", "card gen-card");

    const head = el("div", "gen-card-head");
    head.appendChild(el("span", "badge badge-" + question.difficulty, question.difficulty));
    head.appendChild(el("span", "hint", question.line_count + " lines"));
    article.appendChild(head);

    article.appendChild(el("p", "gen-statement", question.statement));
    if (question.hint) article.appendChild(el("p", "hint", "Hint: " + question.hint));

    const actions = el("div", "gen-card-actions");
    const practise = el("a", "btn btn-primary", "Practise this");
    practise.href = window.__ILO_FITCH_URL + "?q=" + encodeURIComponent(question.id);
    actions.appendChild(practise);

    const toggle = el("button", "btn btn-ghost", "Show answer");
    toggle.type = "button";
    actions.appendChild(toggle);
    article.appendChild(actions);

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
      const url = "/api/questions" + (band ? "?difficulty=" + band : "");
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not load questions.");
      fill(list, data.questions, band
        ? "No " + band + " questions saved yet."
        : "Nothing saved yet. Generate one above.");
      const c = data.counts || {};
      $("#gen-counts").textContent =
        (c.total || 0) + " saved · " + (c.easy || 0) + " easy · " +
        (c.medium || 0) + " medium · " + (c.hard || 0) + " hard";
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
          difficulty: $("#gen-difficulty").value,
          count: Number($("#gen-count").value),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Generation failed.");

      $("#gen-results").hidden = false;
      fill($("#gen-new"), data.questions, "Nothing came back.");
      const asked = $("#gen-difficulty").value;
      const offBand = asked && data.questions.some((q) => q.difficulty !== asked);
      status.textContent = "Saved " + data.questions.length + " question" +
        (data.questions.length === 1 ? "" : "s") + "." +
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

  function init() {
    if (!$("#gen-run")) return;
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
