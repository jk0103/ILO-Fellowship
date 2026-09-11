/* Fitch proof editor.
 *
 * Propositional fragment of the Stanford intro-logic Fitch system. You select
 * lines with the checkboxes and press a rule button; the rule is applied for
 * you and the new lines are appended. Nothing is typed except premises,
 * assumptions, and the target of Or Introduction.
 *
 * Everything runs in the browser; nothing is sent to the server.
 */
(function () {
  "use strict";

  /* ---------------------------------------------------------------- parsing */

  const SYM = { not: "¬", and: "∧", or: "∨", imp: "⇒", iff: "⇔" };

  // Longest match first, so "<=>" never reads as "<" then "=>".
  const OPERATORS = [
    ["<=>", "iff"], ["<->", "iff"], ["⇔", "iff"], ["↔", "iff"], ["≡", "iff"],
    ["=>", "imp"], ["->", "imp"], ["⇒", "imp"], ["→", "imp"], ["⊃", "imp"],
    ["/\\", "and"], ["&&", "and"], ["&", "and"], ["∧", "and"], ["^", "and"],
    ["\\/", "or"], ["||", "or"], ["|", "or"], ["∨", "or"], ["+", "or"],
    ["~", "not"], ["!", "not"], ["¬", "not"], ["-", "not"],
    ["(", "("], [")", ")"],
  ];

  function tokenize(src) {
    const tokens = [];
    let i = 0;
    while (i < src.length) {
      const ch = src[i];
      if (/\s/.test(ch)) { i++; continue; }
      let matched = null;
      for (const [text, kind] of OPERATORS) {
        if (src.startsWith(text, i)) { matched = { kind, text }; break; }
      }
      if (matched) { tokens.push(matched); i += matched.text.length; continue; }
      const name = /^[A-Za-z][A-Za-z0-9_]*/.exec(src.slice(i));
      if (name) { tokens.push({ kind: "atom", text: name[0] }); i += name[0].length; continue; }
      throw new Error('Unexpected character "' + ch + '".');
    }
    return tokens;
  }

  // Grammar (loosest to tightest):
  //   iff  ::= imp ( <=> imp )?          -- not chainable, like Stanford
  //   imp  ::= or ( => imp )?            -- right associative
  //   or   ::= and ( | and )*            -- flattened into one n-ary node
  //   and  ::= unary ( & unary )*        -- flattened into one n-ary node
  //   unary::= ~ unary | atom | ( iff )
  // Flattening only happens at the same parenthesis level, so (p&q)&r stays nested.
  function parse(src) {
    const tokens = tokenize(src);
    let pos = 0;
    const peek = () => tokens[pos];
    const eat = (kind) => (peek() && peek().kind === kind ? tokens[pos++] : null);

    function unary() {
      const tok = peek();
      if (!tok) throw new Error("The formula ends too early.");
      if (tok.kind === "not") { pos++; return { t: "not", a: unary() }; }
      if (tok.kind === "atom") { pos++; return { t: "atom", name: tok.text }; }
      if (tok.kind === "(") {
        pos++;
        const inner = iff();
        if (!eat(")")) throw new Error("Missing a closing parenthesis.");
        return inner;
      }
      throw new Error('Expected a formula, found "' + tok.text + '".');
    }

    function nary(kind, next) {
      const args = [next()];
      while (peek() && peek().kind === kind) { pos++; args.push(next()); }
      return args.length === 1 ? args[0] : { t: kind, args: args };
    }

    const and = () => nary("and", unary);
    const or = () => nary("or", and);

    function imp() {
      const left = or();
      if (peek() && peek().kind === "imp") { pos++; return { t: "imp", a: left, b: imp() }; }
      return left;
    }

    function iff() {
      const left = imp();
      if (peek() && peek().kind === "iff") {
        pos++;
        const right = imp();
        if (peek() && peek().kind === "iff") throw new Error("Chained ⇔ is ambiguous; add parentheses.");
        return { t: "iff", a: left, b: right };
      }
      return left;
    }

    const result = iff();
    if (pos < tokens.length) throw new Error('Unexpected "' + tokens[pos].text + '" after the formula.');
    return result;
  }

  const PREC = { atom: 5, not: 4, and: 3, or: 2, imp: 1, iff: 0 };

  function show(f, parentPrec) {
    parentPrec = parentPrec === undefined ? -1 : parentPrec;
    const prec = PREC[f.t];
    let out;
    switch (f.t) {
      case "atom": return f.name;
      case "not": return SYM.not + show(f.a, PREC.not);
      case "and":
      case "or":
        out = f.args.map((a) => show(a, prec)).join(" " + SYM[f.t] + " ");
        break;
      case "imp":
        // Right associative: the left side needs parens at equal precedence.
        out = show(f.a, prec + 0.5) + " " + SYM.imp + " " + show(f.b, prec);
        break;
      case "iff":
        out = show(f.a, prec + 0.5) + " " + SYM.iff + " " + show(f.b, prec + 0.5);
        break;
    }
    return prec < parentPrec ? "(" + out + ")" : out;
  }

  // Structural identity. Two formulas are the same iff they print the same
  // fully-parenthesized, so a canonical string doubles as an equality test.
  function key(f) {
    switch (f.t) {
      case "atom": return f.name;
      case "not": return "~(" + key(f.a) + ")";
      case "and":
      case "or": return f.t + "(" + f.args.map(key).join(",") + ")";
      default: return f.t + "(" + key(f.a) + "," + key(f.b) + ")";
    }
  }
  const same = (x, y) => !!x && !!y && key(x) === key(y);
  const not = (f) => ({ t: "not", a: f });
  const imp = (a, b) => ({ t: "imp", a: a, b: b });

  /* ------------------------------------------------------------------ rules */

  const RULES = [
    { id: "premise", label: "Premise", short: "Premise" },
    { id: "assume", label: "Assumption", short: "Assumption" },
    { id: "reit", label: "Reiteration", short: "R" },
    { id: "ai", label: "And Introduction", short: "AI" },
    { id: "ae", label: "And Elimination", short: "AE" },
    { id: "oi", label: "Or Introduction", short: "OI" },
    { id: "oe", label: "Or Elimination", short: "OE" },
    { id: "ni", label: "Negation Introduction", short: "NI" },
    { id: "ne", label: "Negation Elimination", short: "NE" },
    { id: "ii", label: "Implication Introduction", short: "II" },
    { id: "ie", label: "Implication Elimination", short: "IE" },
    { id: "bi", label: "Biconditional Introduction", short: "BI" },
    { id: "be", label: "Biconditional Elimination", short: "BE" },
  ];
  const RULE_BY_ID = {};
  RULES.forEach((r) => { RULE_BY_ID[r.id] = r; });

  /* Walks the flat line list and works out the subproof structure.
   *
   * Each line carries a depth. A line deeper than the one before it opens a
   * subproof, which is only legal if that line is an assumption. An assumption
   * at the same depth as the line before closes the current subproof and opens
   * a sibling. Every line ends up tagged with the block it lives in, plus that
   * block's chain of ancestors, which is exactly what citation scope needs.
   */
  function analyze(lines) {
    let nextBlock = 1;
    const root = { id: 0, parent: null, depth: 0, start: 0, end: lines.length - 1, chain: new Set([0]) };
    const blocks = [root];
    const stack = [root];

    lines.forEach((line, i) => {
      line.index = i;
      line.error = null;
      const depth = line.depth;

      while (stack.length - 1 > depth) { stack[stack.length - 1].end = i - 1; stack.pop(); }

      const openNew = () => {
        const parent = stack[stack.length - 1];
        const block = {
          id: nextBlock++, parent: parent, depth: stack.length,
          start: i, end: lines.length - 1, chain: new Set(parent.chain),
        };
        block.chain.add(block.id);
        blocks.push(block);
        stack.push(block);
        return block;
      };

      if (depth > stack.length - 1) {
        if (line.rule !== "assume") {
          line.error = "An indented block has to start with an assumption.";
        }
        openNew();
      } else if (line.rule === "assume") {
        if (depth === 0) {
          line.error = "Assumptions live inside a subproof.";
        } else if (stack[stack.length - 1].start !== i) {
          stack[stack.length - 1].end = i - 1;
          stack.pop();
          openNew();
        }
      }

      line.block = stack[stack.length - 1];
    });

    while (stack.length > 1) { stack[stack.length - 1].end = lines.length - 1; stack.pop(); }
    return { blocks: blocks, root: root };
  }

  /* ------------------------------------------------------------- verification
   *
   * Rules are applied by the buttons below, so freshly made lines are correct
   * by construction. This pass runs anyway: deleting a line can strand the
   * citations of the lines that came after it, and that has to show up. */

  // Order-insensitive pairing: every disjunct needs its own matching implication.
  function matchDisjuncts(disjuncts, implications, conclusion) {
    const pool = implications.slice();
    for (const d of disjuncts) {
      const at = pool.findIndex((i) => i && i.t === "imp" && same(i.a, d) && same(i.b, conclusion));
      if (at === -1) return false;
      pool.splice(at, 1);
    }
    return pool.length === 0;
  }

  function checkLine(line, lines, premises) {
    if (line.error) return { ok: false, msg: line.error };

    const cited = [];
    for (const id of line.refIds) {
      const target = lines.find((l) => l.id === id);
      if (!target) return { ok: false, msg: "This cites a line that has been deleted." };
      if (target.index >= line.index) return { ok: false, msg: "Line " + (target.index + 1) + " comes later in the proof." };
      if (!line.block.chain.has(target.block.id)) {
        return { ok: false, msg: "Line " + (target.index + 1) + " sits in a subproof that has closed." };
      }
      cited.push(target.formula);
    }

    let sub = null;
    if (line.subRef) {
      const head = lines.find((l) => l.id === line.subRef.fromId);
      const tail = lines.find((l) => l.id === line.subRef.toId);
      if (!head || !tail) return { ok: false, msg: "This cites a subproof that has been deleted." };
      const block = head.block;
      // The range runs from the subproof's assumption to any later line of that
      // same subproof — the consequent need not be the subproof's last line.
      if (block.id === 0 || block.start !== head.index || tail.block.id !== block.id || tail.index < head.index) {
        return { ok: false, msg: "Lines " + (head.index + 1) + "-" + (tail.index + 1) + " are no longer one subproof." };
      }
      if (block.end >= line.index || !line.block.chain.has(block.parent.id)) {
        return { ok: false, msg: "That subproof is not in scope here." };
      }
      sub = { assumption: head.formula, conclusion: tail.formula };
    }

    const f = line.formula;

    switch (line.rule) {
      case "premise":
        if (line.depth !== 0) return { ok: false, msg: "Premises belong at the outermost level." };
        if (!premises.some((p) => same(p, f))) return { ok: false, msg: "That is not one of the premises." };
        return { ok: true };

      case "assume":
        return { ok: true };

      case "reit":
        if (cited.length !== 1 || !same(cited[0], f)) return { ok: false, msg: "Reiteration repeats one line exactly." };
        return { ok: true };

      case "ai":
        if (f.t !== "and" || f.args.length !== cited.length || !f.args.every((a, i) => same(a, cited[i]))) {
          return { ok: false, msg: "The conjuncts no longer match the cited lines." };
        }
        return { ok: true };

      case "ae":
        if (cited.length !== 1 || cited[0].t !== "and" || !cited[0].args.some((a) => same(a, f))) {
          return { ok: false, msg: "This is not a conjunct of the cited line." };
        }
        return { ok: true };

      case "oi":
        if (cited.length !== 1 || f.t !== "or" || !f.args.some((a) => same(a, cited[0]))) {
          return { ok: false, msg: "The cited line is not one of these disjuncts." };
        }
        return { ok: true };

      case "oe": {
        if (cited.length < 3 || cited[0].t !== "or" || !matchDisjuncts(cited[0].args, cited.slice(1), f)) {
          return { ok: false, msg: "The cited cases no longer cover the disjunction." };
        }
        return { ok: true };
      }

      case "ni": {
        if (cited.length !== 2 || f.t !== "not") return { ok: false, msg: "Negation Introduction needs two implications." };
        const [x, y] = cited;
        const clash = (p, q) => p.t === "imp" && q.t === "imp" && same(p.a, f.a) && same(q.a, f.a) &&
          (same(q.b, not(p.b)) || same(p.b, not(q.b)));
        if (!clash(x, y) && !clash(y, x)) return { ok: false, msg: "The cited implications no longer contradict." };
        return { ok: true };
      }

      case "ne":
        if (cited.length !== 1 || cited[0].t !== "not" || cited[0].a.t !== "not" || !same(cited[0].a.a, f)) {
          return { ok: false, msg: "Negation Elimination needs a double negation." };
        }
        return { ok: true };

      case "ii":
        if (!sub || cited.length) return { ok: false, msg: "Implication Introduction cites one subproof." };
        if (f.t !== "imp" || !same(sub.assumption, f.a) || !same(sub.conclusion, f.b)) {
          return { ok: false, msg: "That subproof now discharges to " + show(imp(sub.assumption, sub.conclusion)) + "." };
        }
        return { ok: true };

      case "ie": {
        if (cited.length !== 2) return { ok: false, msg: "Implication Elimination cites two lines." };
        const [x, y] = cited;
        const fires = (i, ant) => i.t === "imp" && same(i.a, ant) && same(i.b, f);
        if (!fires(x, y) && !fires(y, x)) return { ok: false, msg: "The cited lines no longer yield this." };
        return { ok: true };
      }

      case "bi": {
        if (cited.length !== 2 || f.t !== "iff") return { ok: false, msg: "Biconditional Introduction needs two implications." };
        const [x, y] = cited;
        const fwd = imp(f.a, f.b), bwd = imp(f.b, f.a);
        if (!((same(x, fwd) && same(y, bwd)) || (same(x, bwd) && same(y, fwd)))) {
          return { ok: false, msg: "The cited implications no longer run both ways." };
        }
        return { ok: true };
      }

      case "be":
        if (cited.length !== 1 || cited[0].t !== "iff" ||
            (!same(f, imp(cited[0].a, cited[0].b)) && !same(f, imp(cited[0].b, cited[0].a)))) {
          return { ok: false, msg: "Biconditional Elimination needs a biconditional." };
        }
        return { ok: true };
    }
    return { ok: false, msg: "Unknown rule." };
  }

  /* ------------------------------------------------------- applying the rules
   *
   * Each entry takes the checked lines and returns either { error } or
   * { lines: [...] } — the lines to append, already justified. A rule that
   * needs something typed returns { prompt } instead and is resumed with the
   * formula the user entered. */

  function citeIds(selected) { return selected.map((l) => l.id); }

  const APPLY = {
    ai: function (sel) {
      if (sel.length < 2) return { error: "Check two or more lines to conjoin." };
      return { lines: [{ formula: { t: "and", args: sel.map((l) => l.formula) }, rule: "ai", refIds: citeIds(sel) }] };
    },

    ae: function (sel) {
      if (sel.length !== 1) return { error: "Check exactly one conjunction." };
      const f = sel[0].formula;
      if (f.t !== "and") return { error: "Line " + (sel[0].index + 1) + " is not a conjunction." };
      return { lines: f.args.map((arg) => ({ formula: arg, rule: "ae", refIds: citeIds(sel) })) };
    },

    oi: function (sel, typed) {
      if (sel.length !== 1) return { error: "Check exactly one line to weaken into a disjunction." };
      if (!typed) {
        return { prompt: "Or Introduction — type the disjunction to introduce. It has to contain " + show(sel[0].formula) + " as a disjunct.", seed: show(sel[0].formula) + " ∨ " };
      }
      if (typed.t !== "or") return { error: "That is not a disjunction." };
      if (!typed.args.some((a) => same(a, sel[0].formula))) {
        return { error: show(sel[0].formula) + " is not one of those disjuncts." };
      }
      return { lines: [{ formula: typed, rule: "oi", refIds: citeIds(sel) }] };
    },

    oe: function (sel) {
      const at = sel.findIndex((l) => l.formula.t === "or");
      if (at === -1) return { error: "Check a disjunction along with one implication per disjunct." };
      const disj = sel[at].formula;
      const rest = sel.slice(0, at).concat(sel.slice(at + 1));
      if (rest.length !== disj.args.length) {
        return { error: "That disjunction has " + disj.args.length + " disjuncts, so check " + disj.args.length + " implications with it." };
      }
      const bad = rest.find((l) => l.formula.t !== "imp");
      if (bad) return { error: "Line " + (bad.index + 1) + " is not an implication." };
      const conclusion = rest[0].formula.b;
      if (!rest.every((l) => same(l.formula.b, conclusion))) {
        return { error: "The cited implications have to share one conclusion." };
      }
      if (!matchDisjuncts(disj.args, rest.map((l) => l.formula), conclusion)) {
        return { error: "Each disjunct needs its own implication among the checked lines." };
      }
      return { lines: [{ formula: conclusion, rule: "oe", refIds: citeIds([sel[at]].concat(rest)) }] };
    },

    ni: function (sel) {
      if (sel.length !== 2) return { error: "Check the two implications that contradict." };
      const [x, y] = sel.map((l) => l.formula);
      if (x.t !== "imp" || y.t !== "imp") return { error: "Negation Introduction needs two implications." };
      if (!same(x.a, y.a)) return { error: "Both implications need the same antecedent." };
      const opposed = same(y.b, not(x.b)) || same(x.b, not(y.b));
      if (!opposed) return { error: "The consequents have to be a formula and its negation." };
      return { lines: [{ formula: not(x.a), rule: "ni", refIds: citeIds(sel) }] };
    },

    ne: function (sel) {
      if (sel.length !== 1) return { error: "Check exactly one double negation." };
      const f = sel[0].formula;
      if (f.t !== "not" || f.a.t !== "not") return { error: "Line " + (sel[0].index + 1) + " is not a double negation." };
      return { lines: [{ formula: f.a.a, rule: "ne", refIds: citeIds(sel) }] };
    },

    ie: function (sel) {
      if (sel.length !== 2) return { error: "Check an implication and its antecedent." };
      const [x, y] = sel;
      const fire = (i, a) => i.formula.t === "imp" && same(i.formula.a, a.formula);
      const pair = fire(x, y) ? [x, y] : (fire(y, x) ? [y, x] : null);
      if (!pair) return { error: "Neither checked line is an implication whose antecedent is the other." };
      return { lines: [{ formula: pair[0].formula.b, rule: "ie", refIds: citeIds(sel) }] };
    },

    bi: function (sel) {
      if (sel.length !== 2) return { error: "Check the two implications to join." };
      const [x, y] = sel.map((l) => l.formula);
      if (x.t !== "imp" || y.t !== "imp") return { error: "Biconditional Introduction needs two implications." };
      if (!same(x.a, y.b) || !same(x.b, y.a)) return { error: "Those implications do not run in opposite directions." };
      return { lines: [{ formula: { t: "iff", a: x.a, b: x.b }, rule: "bi", refIds: citeIds(sel) }] };
    },

    be: function (sel) {
      if (sel.length !== 1) return { error: "Check exactly one biconditional." };
      const f = sel[0].formula;
      if (f.t !== "iff") return { error: "Line " + (sel[0].index + 1) + " is not a biconditional." };
      return {
        lines: [
          { formula: imp(f.a, f.b), rule: "be", refIds: citeIds(sel) },
          { formula: imp(f.b, f.a), rule: "be", refIds: citeIds(sel) },
        ],
      };
    },

    reit: function (sel) {
      if (sel.length !== 1) return { error: "Check exactly one line to repeat." };
      return { lines: [{ formula: sel[0].formula, rule: "reit", refIds: citeIds(sel) }] };
    },
  };

  /* ---------------------------------------------------------------- problems */

  const PROBLEMS = [
    { id: "and-comm", title: "Commuting a conjunction", premises: ["p & q"], goal: "q & p", tags: "AI, AE" },
    { id: "mp", title: "Modus ponens, twice", premises: ["p", "p => q", "q => r"], goal: "r", tags: "IE" },
    { id: "imp-self", title: "Implication is reflexive", premises: [], goal: "p => p", tags: "II" },
    { id: "and-imp", title: "Currying", premises: ["(p & q) => r"], goal: "p => (q => r)", tags: "II, AI, IE" },
    { id: "hyp-syll", title: "Hypothetical syllogism", premises: ["p => q", "q => r"], goal: "p => r", tags: "II, IE" },
    { id: "contra", title: "Contraposition", premises: ["p => q"], goal: "~q => ~p", tags: "II, NI" },
    { id: "mt", title: "Modus tollens", premises: ["p => q", "~q"], goal: "~p", tags: "NI, II, R" },
    { id: "or-comm", title: "Commuting a disjunction", premises: ["p | q"], goal: "q | p", tags: "OE, OI, II" },
    { id: "dilemma", title: "Constructive dilemma", premises: ["p | q", "p => r", "q => r"], goal: "r", tags: "OE" },
    { id: "iff-comm", title: "Biconditionals commute", premises: ["p <=> q"], goal: "q <=> p", tags: "BE, BI" },
    { id: "dn-in", title: "Double negation introduction", premises: ["p"], goal: "~~p", tags: "NI, II, R" },
    { id: "and-assoc", title: "Regrouping a conjunction", premises: ["p & (q & r)"], goal: "(p & q) & r", tags: "AE, AI" },
    { id: "distrib", title: "Distribution", premises: ["p & (q | r)"], goal: "(p & q) | (p & r)", tags: "OE, OI, AI, II" },
    { id: "demorgan", title: "De Morgan, one direction", premises: ["~p & ~q"], goal: "~(p | q)", tags: "NI, II, OE" },
    { id: "excluded", title: "Excluded middle", premises: [], goal: "p | ~p", tags: "NI, NE, II, OI" },
    { id: "peirce", title: "Peirce's law", premises: ["(p => q) => p"], goal: "p", tags: "NI, NE, II, IE" },
  ];

  /* --------------------------------------------------------------------- UI */

  let uid = 0;
  const state = {
    premises: [],
    premiseSrc: [],
    goal: null,
    goalSrc: "",
    goalError: null,
    lines: [],
    selected: new Set(),   // line ids
    problem: null,
    pending: null,         // a rule waiting on a typed formula
    history: [],
  };

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const makeLine = (spec) => Object.assign({ id: ++uid, depth: 0, refIds: [], subRef: null }, spec);

  function snapshot() {
    state.history.push(state.lines.map((l) => Object.assign({}, l, {
      refIds: l.refIds.slice(),
      subRef: l.subRef ? Object.assign({}, l.subRef) : null,
    })));
    if (state.history.length > 60) state.history.shift();
  }

  function undo() {
    if (!state.history.length) return say("Nothing to undo.");
    state.lines = state.history.pop();
    state.selected.clear();
    state.pending = null;
    render();
  }

  function say(message, kind) {
    const box = $("#fitch-message");
    box.textContent = message || "";
    box.className = "fitch-message" + (message ? " message-" + (kind || "error") : "");
  }

  /* The proof grows downward, so new lines land at the end. Their depth is the
   * depth of the last line — that subproof is the one still open. */
  function currentBlock() {
    const last = state.lines[state.lines.length - 1];
    return last ? last.block : analyze(state.lines).root;
  }

  /* In the order the boxes were ticked, not the order the lines appear: And
   * Introduction builds its conjunction in that order, so ticking q then p is
   * how you get q ∧ p out of p ∧ q. */
  function selectedLines() {
    const byId = new Map(state.lines.map((l) => [l.id, l]));
    return [...state.selected].map((id) => byId.get(id)).filter(Boolean);
  }

  function runRule(ruleId, typed) {
    say("");
    const sel = selectedLines();

    if (ruleId === "premise" || ruleId === "assume") return addTypedLine(ruleId, typed);
    if (ruleId === "ii") return applyII(sel);

    const apply = APPLY[ruleId];
    if (!apply) return;

    const block = currentBlock();
    const stranded = sel.find((l) => !block.chain.has(l.block.id));
    if (stranded) {
      return say("Line " + (stranded.index + 1) + " is inside a subproof that has already closed, so it cannot be used here.");
    }

    const result = apply(sel, typed);
    if (result.error) return say(result.error);
    if (result.prompt) return openPrompt(ruleId, result.prompt, result.seed);

    snapshot();
    const depth = block.depth;
    result.lines.forEach((spec) => state.lines.push(makeLine(Object.assign({ depth: depth }, spec))));
    state.selected.clear();
    state.pending = null;
    render();
  }

  function addTypedLine(ruleId, typed) {
    if (!typed) {
      return openPrompt(ruleId, ruleId === "premise"
        ? "Premise — type the formula to assume outright."
        : "Assumption — type the formula to suppose. It opens a new subproof.");
    }
    snapshot();
    if (ruleId === "premise") {
      // Premises belong at the top, ahead of any reasoning.
      let at = 0;
      while (at < state.lines.length && state.lines[at].rule === "premise" && state.lines[at].depth === 0) at++;
      state.lines.splice(at, 0, makeLine({ formula: typed, rule: "premise", depth: 0 }));
      if (!state.premises.some((p) => same(p, typed))) state.premises.push(typed);
    } else {
      state.lines.push(makeLine({ formula: typed, rule: "assume", depth: currentBlock().depth + 1 }));
    }
    state.selected.clear();
    state.pending = null;
    render();
  }

  /* Implication Introduction discharges a subproof. Check its assumption and
   * the line to discharge to — or just that line, and the assumption is taken
   * from the subproof it sits in. */
  function applyII(sel) {
    if (!sel.length || sel.length > 2) {
      return say("Check the line to discharge to (and, if you like, its assumption).");
    }
    const block = sel[sel.length - 1].block;
    if (block.id === 0) return say("Line " + (sel[0].index + 1) + " is not inside a subproof.");
    if (!sel.every((l) => l.block.id === block.id)) return say("Both checked lines have to sit in the same subproof.");
    const head = state.lines[block.start];
    if (sel.length === 2 && sel[0].id !== head.id) {
      return say("The first checked line has to be the subproof's assumption, line " + (head.index + 1) + ".");
    }
    const tail = sel[sel.length - 1];

    const here = currentBlock();
    let depth;
    if (block.id === here.id) {
      depth = block.parent.depth;          // discharging the subproof we are in closes it
    } else if (block.end < state.lines.length - 1 && here.chain.has(block.parent.id)) {
      depth = here.depth;                  // a subproof that already closed, still in scope
    } else {
      return say("That subproof is not in scope at the end of the proof.");
    }

    snapshot();
    state.lines.push(makeLine({
      formula: imp(head.formula, tail.formula),
      rule: "ii",
      subRef: { fromId: head.id, toId: tail.id },
      depth: depth,
    }));
    state.selected.clear();
    state.pending = null;
    render();
  }

  function deleteSelected() {
    const sel = selectedLines();
    if (!sel.length) return say("Check the lines to delete.");
    snapshot();
    const doomed = new Set(sel.map((l) => l.id));
    state.lines = state.lines.filter((l) => !doomed.has(l.id));
    state.selected.clear();
    say("");
    render();
  }

  /* ------------------------------------------------------------ typed input */

  function openPrompt(ruleId, label, seed) {
    state.pending = { rule: ruleId, label: label };
    render();
    const input = $("#fitch-entry-input");
    input.value = seed || "";
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  function submitPrompt() {
    const input = $("#fitch-entry-input");
    let formula;
    try { formula = parse(input.value); }
    catch (e) { return say(e.message); }
    runRule(state.pending.rule, formula);
  }

  function insertSymbol(text) {
    const input = $("#fitch-entry-input");
    if (!input) return;
    const start = input.selectionStart === null ? input.value.length : input.selectionStart;
    const end = input.selectionEnd === null ? start : input.selectionEnd;
    input.value = input.value.slice(0, start) + text + input.value.slice(end);
    input.focus();
    input.setSelectionRange(start + text.length, start + text.length);
  }

  /* --------------------------------------------------------------- rendering */

  function justification(line, lines) {
    const numbers = line.refIds.map((id) => {
      const target = lines.find((l) => l.id === id);
      return target ? target.index + 1 : "?";
    });
    if (line.subRef) {
      const head = lines.find((l) => l.id === line.subRef.fromId);
      const tail = lines.find((l) => l.id === line.subRef.toId);
      numbers.push((head ? head.index + 1 : "?") + "-" + (tail ? tail.index + 1 : "?"));
    }
    const short = RULE_BY_ID[line.rule].short;
    return numbers.length ? numbers.join(", ") + " " + short : short;
  }

  function render() {
    const lines = state.lines;
    analyze(lines);

    const board = $("#fitch-lines");
    board.innerHTML = "";
    if (!lines.length) {
      board.appendChild(el("p", "fitch-empty", "Nothing yet. Add a premise or an assumption to start."));
    }

    let allValid = true;
    lines.forEach((line) => {
      const result = checkLine(line, lines, state.premises);
      line.result = result;
      if (!result.ok) allValid = false;

      const row = el("div", "fitch-row" + (result.ok ? "" : " bad"));
      row.style.setProperty("--depth", line.depth);

      const box = el("input", "fitch-check");
      box.type = "checkbox";
      box.checked = state.selected.has(line.id);
      box.title = "Select line " + (line.index + 1);
      box.addEventListener("change", () => {
        if (box.checked) state.selected.add(line.id); else state.selected.delete(line.id);
        updateSelectionUI();
      });
      row.appendChild(box);

      row.appendChild(el("span", "fitch-num", String(line.index + 1)));

      const scope = el("span", "fitch-scope");
      for (let d = 0; d < line.depth; d++) scope.appendChild(el("span", "fitch-bar"));
      row.appendChild(scope);

      const formula = el("span", "fitch-formula", show(line.formula));
      if (line.rule === "assume") formula.classList.add("is-assumption");
      row.appendChild(formula);

      row.appendChild(el("span", "fitch-just", justification(line, lines)));
      if (!result.ok) row.appendChild(el("span", "fitch-note", result.msg));
      board.appendChild(row);
    });

    // Typed-formula bar, shown only while a rule is waiting on one.
    const entry = $("#fitch-entry");
    entry.hidden = !state.pending;
    if (state.pending) $("#fitch-entry-label").textContent = state.pending.label;

    $("#fitch-premises").textContent = state.premises.length
      ? state.premises.map((p) => show(p)).join(",   ")
      : "(none — this one is a theorem)";
    $("#fitch-goal-display").textContent = state.goal ? show(state.goal) : "—";

    const reached = state.goal && lines.some((l) => l.depth === 0 && l.result.ok && same(l.formula, state.goal));
    const banner = $("#fitch-verdict");
    banner.className = "fitch-verdict";
    if (!state.goal) {
      banner.textContent = state.goalError ? "Goal does not parse: " + state.goalError : "Set a goal to prove.";
      banner.classList.add("verdict-error");
    } else if (reached && allValid) {
      banner.textContent = "✓ Proved. " + show(state.goal) + " follows from the premises.";
      banner.classList.add("verdict-done");
    } else if (!allValid) {
      banner.textContent = "Some lines no longer hold up — a line they cite was deleted or fell out of scope.";
      banner.classList.add("verdict-error");
    } else {
      banner.textContent = "Goal: " + show(state.goal) + " — not derived yet.";
      banner.classList.add("verdict-working");
    }

    updateSelectionUI();
  }

  // Cheap enough to recompute on every checkbox click, and it keeps the
  // "selected" readout and the row highlight in step without a full rebuild.
  function updateSelectionUI() {
    const rows = document.querySelectorAll("#fitch-lines .fitch-row");
    state.lines.forEach((line, i) => {
      if (rows[i]) rows[i].classList.toggle("selected", state.selected.has(line.id));
    });
    const master = $("#fitch-select-all");
    master.checked = state.lines.length > 0 && state.selected.size === state.lines.length;
    master.indeterminate = state.selected.size > 0 && !master.checked;

    const picked = selectedLines();
    $("#fitch-selected").textContent = picked.length
      ? "Selected: " + picked.map((l) => l.index + 1).join(", ") + "  (in the order ticked)"
      : "Select lines with the checkboxes, then press a rule.";
  }

  /* ------------------------------------------------------------------ setup */

  function loadProblem(problem) {
    state.problem = problem;
    state.premiseSrc = problem.premises.slice();
    state.goalSrc = problem.goal;
    reparseGoal();
    resetLines();
  }

  function reparseGoal() {
    state.premises = [];
    state.premiseErrors = [];
    state.premiseSrc.forEach((src) => {
      try { state.premises.push(parse(src)); }
      catch (e) { state.premiseErrors.push(src + ": " + e.message); }
    });
    try { state.goal = state.goalSrc.trim() ? parse(state.goalSrc) : null; state.goalError = null; }
    catch (e) { state.goal = null; state.goalError = e.message; }
  }

  function resetLines() {
    state.lines = state.premises.map((p) => makeLine({ formula: p, rule: "premise", depth: 0 }));
    state.selected.clear();
    state.pending = null;
    state.history = [];
    say("");
    render();
  }

  function buildButtons() {
    // Laid out in the columns of the Stanford tool: structural, And/Or,
    // Implication/Biconditional, Negation.
    const columns = [
      ["premise", "assume", "reit"],
      ["ai", "ae", "oi", "oe"],
      ["ii", "ie", "bi", "be"],
      ["ni", "ne"],
    ];
    const grid = $("#fitch-buttons");
    columns.forEach((ids) => {
      const col = el("div", "fitch-bcol");
      ids.forEach((id) => {
        const b = el("button", "fitch-rule-btn", RULE_BY_ID[id].label);
        b.type = "button";
        b.addEventListener("click", () => runRule(id));
        col.appendChild(b);
      });
      grid.appendChild(col);
    });
    const col = el("div", "fitch-bcol");
    [["Undo", undo], ["Delete", deleteSelected], ["Reset", resetLines]].forEach(([label, fn]) => {
      const b = el("button", "fitch-rule-btn fitch-util", label);
      b.type = "button";
      b.addEventListener("click", fn);
      col.appendChild(b);
    });
    grid.appendChild(col);
  }

  function init() {
    const picker = $("#fitch-problem");
    if (!picker) return; // Not on the Fitch page.

    // A question loaded from the Generate page goes to the top of the list and
    // is what the editor opens on.
    const loaded = window.__ILO_QUESTION
      ? { id: "loaded", title: window.__ILO_QUESTION.title, tags: "generated",
          premises: window.__ILO_QUESTION.premises, goal: window.__ILO_QUESTION.goal }
      : null;
    const problems = loaded ? [loaded].concat(PROBLEMS) : PROBLEMS;

    problems.forEach((p, i) => picker.appendChild(new Option((i + 1) + ". " + p.title + "  (" + p.tags + ")", p.id)));
    picker.appendChild(new Option("Custom — write your own", "custom"));
    picker.addEventListener("change", () => {
      if (picker.value === "custom") { $("#fitch-custom").hidden = false; return; }
      $("#fitch-custom").hidden = true;
      loadProblem(problems.find((p) => p.id === picker.value));
    });

    $("#fitch-custom-apply").addEventListener("click", () => {
      state.problem = null;
      state.premiseSrc = $("#fitch-custom-premises").value.split(/[\n,;]/).map((s) => s.trim()).filter(Boolean);
      state.goalSrc = $("#fitch-custom-goal").value;
      reparseGoal();
      const bad = (state.premiseErrors || []).concat(state.goalError ? ["goal: " + state.goalError] : []);
      $("#fitch-custom-error").textContent = bad.join("  ·  ");
      resetLines();
    });

    $("#fitch-select-all").addEventListener("change", (ev) => {
      state.selected.clear();
      if (ev.target.checked) state.lines.forEach((l) => state.selected.add(l.id));
      render();
    });

    $("#fitch-entry-ok").addEventListener("click", submitPrompt);
    $("#fitch-entry-cancel").addEventListener("click", () => { state.pending = null; say(""); render(); });
    $("#fitch-entry-input").addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); submitPrompt(); }
      if (ev.key === "Escape") { state.pending = null; say(""); render(); }
    });
    document.querySelectorAll("[data-symbol]").forEach((btn) => {
      btn.addEventListener("click", () => insertSymbol(btn.dataset.symbol));
    });

    buildButtons();
    loadProblem(problems[0]);
  }

  // Exposed for the console and for tests.
  window.Fitch = {
    parse: parse, show: show, same: same, analyze: analyze, checkLine: checkLine,
    runRule: runRule, state: state, PROBLEMS: PROBLEMS, RULES: RULES,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
