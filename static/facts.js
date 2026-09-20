/* Facts about logic, rotating at the foot of every page.
 *
 * All of them are drawn from the two chapters this site generates questions
 * for — "Introduction to Logic" Chapter 5 (propositional Fitch) and Chapter 10
 * (relational Fitch) — so what a reader picks up here is the same material the
 * exercises are built on. Each is paraphrased tightly enough to stay true to
 * the chapter without lifting its prose wholesale.
 *
 * One rotation drives every target on the page: the strip above the footer and
 * the card inside the loading overlay both carry [data-fact], so they always
 * show the same thing and a single timer moves them on together. The overlay
 * needs its own copy because the strip is behind the blur while it is up.
 */
(function () {
  "use strict";

  const ROTATE_MS = 10000;

  const FACTS = [
    // --- Chapter 5: propositional Fitch ---
    {
      text: "The Fitch system is sound and complete for Propositional Logic, "
          + "which makes entailment and provability the same thing: Δ ⊢ φ "
          + "exactly when Δ ⊨ φ.",
      source: "Chapter 5",
    },
    {
      text: "Inside a subproof you may assume whatever you like. The assumption "
          + "need not be one of the premises — it cannot be used outside, so it "
          + "never contaminates the proof around it.",
      source: "Chapter 5",
    },
    {
      text: "All a closed subproof leaves behind is one implication: its "
          + "assumption as the antecedent, the line it reached as the "
          + "consequent. Nothing inside it can be cited again.",
      source: "Chapter 5",
    },
    {
      text: "Or Introduction will infer any disjunction at all, so long as one "
          + "of its disjuncts is already sitting in the proof.",
      source: "Chapter 5",
    },
    {
      text: "Or Elimination cannot simply drop the ∨, because you do not know "
          + "which disjunct is true. But if every disjunct entails the same "
          + "sentence, that sentence follows regardless.",
      source: "Chapter 5",
    },
    {
      text: "A premise set entails a conclusion when every truth assignment "
          + "that satisfies the premises satisfies the conclusion. It proves "
          + "one when there is a finite proof of it.",
      source: "Chapter 5",
    },
    {
      text: "To prove φ by contradiction: assume ¬φ, derive a contradiction, "
          + "conclude ¬¬φ, and finish with Negation Elimination.",
      source: "Chapter 5",
    },
    {
      text: "Conditional proofs exist because direct deduction becomes "
          + "unwieldy. The deduction theorem promises a proof of the "
          + "implication exists; a subproof is what actually builds it.",
      source: "Chapter 5",
    },
    {
      text: "False Introduction and False Elimination add nothing to what Fitch "
          + "can prove — the other rules are already complete. They only make "
          + "some proofs shorter.",
      source: "Chapter 5",
    },

    // --- Chapter 10: relational Fitch ---
    {
      text: "Relational Fitch is propositional Fitch plus five rules: Universal "
          + "Elimination and Introduction, Existential Elimination and "
          + "Introduction, and Domain Closure.",
      source: "Chapter 10",
    },
    {
      text: "Universal Elimination reasons from the general to the particular. "
          + "From ∀y.hates(jane, y) you may infer that Jane hates Jill — and "
          + "that Jane hates Jane.",
      source: "Chapter 10",
    },
    {
      text: "Universal Introduction is the harder direction. Proving something "
          + "of one object is not proving it of every object, so the name you "
          + "generalise has to be genuinely arbitrary.",
      source: "Chapter 10",
    },
    {
      text: "Existential Elimination needs the universal quantifier wrapped "
          + "around the whole implication. The simpler version you would expect "
          + "cannot reach everything that is entailed.",
      source: "Chapter 10",
    },
    {
      text: "Domain Closure works only where there are finitely many ground "
          + "terms. Infinitely many would need a rule of infinite length, and "
          + "no sentence here may be infinitely large.",
      source: "Chapter 10",
    },
    {
      text: "Domain Closure ignores placeholders entirely. Prove a condition "
          + "for every object constant in the language and it holds of "
          + "everything, whatever the placeholders stand for.",
      source: "Chapter 10",
    },
    {
      text: "Relational Fitch handles only closed sentences. That costs "
          + "nothing: every open sentence is equivalent to a closed one whose "
          + "free variables have been universally quantified.",
      source: "Chapter 10",
    },
    {
      text: "In Relational Logic a conclusion is entailed exactly when a finite "
          + "proof of it exists — and such a proof can be found in finite time.",
      source: "Chapter 10",
    },
  ];

  // Start somewhere different each load, so moving between pages does not
  // always open on the same fact.
  let at = Math.floor(Math.random() * FACTS.length);
  let timer = null;

  function paint() {
    const fact = FACTS[at];
    const targets = document.querySelectorAll("[data-fact]");
    for (let i = 0; i < targets.length; i++) {
      const node = targets[i];
      const text = node.querySelector("[data-fact-text]");
      const source = node.querySelector("[data-fact-source]");
      if (text) text.textContent = fact.text;
      if (source) source.textContent = fact.source;
      // Restart the fade: removing the class and reading offsetWidth forces
      // the style to settle before it goes back on, which is what makes the
      // animation replay rather than sit at its finished state.
      node.classList.remove("is-in");
      void node.offsetWidth;
      node.classList.add("is-in");
    }
  }

  function advance() {
    at = (at + 1) % FACTS.length;
    paint();
  }

  function start() {
    if (timer === null) timer = window.setInterval(advance, ROTATE_MS);
  }

  paint();
  start();

  window.ILOFacts = {
    /* Move to the next fact and restart the clock. The loading overlay calls
       this as it opens, so a reader who has been staring at one fact for nine
       seconds is not handed the same one to wait with. */
    next: function () {
      if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
      advance();
      start();
    },
  };
})();
