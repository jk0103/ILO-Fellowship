/* Fitch proof editor.
 *
 * The Stanford intro-logic Fitch system: the propositional rules of Chapter 5,
 * the quantifier rules of Chapter 10, Domain Closure and Induction from
 * Chapter 13, and the equality rules of Chapter 15 with the Stanford tool's
 * Rational Equation and Rational Induction. You select lines with the
 * checkboxes and press a rule button; the rule is applied for you and the new
 * lines are appended. Nothing is typed except premises, assumptions, the target
 * of Or Introduction, the term or sentence a quantifier rule needs, the
 * conclusion of an induction, and the result of an equality rule.
 *
 * Quantifiers are shown the way the textbook writes them: ∀X.p(X) for every X,
 * ∃X.p(X) for some X. They can be typed that way or as the Stanford tool's
 * AX: p(X) and EX: p(X). Variables are uppercase, so a lowercase name is an
 * object constant or a placeholder, and "ground" just means "no uppercase name
 * in it"; ∀x.p(x) with a lowercase variable is normalized on the way in.
 *
 * Everything runs in the browser; nothing is sent to the server.
 */
(function () {
  "use strict";

  /* ---------------------------------------------------------------- parsing */

  const SYM = { not: "¬", and: "∧", or: "∨", imp: "⇒", iff: "⇔" };

  // A quantifier: AX: φ / EX: φ, or the Unicode ∀x.φ / ∃x.φ. Because variables
  // are uppercase, "AX:" cannot be misread as a relation named A — a relation
  // would not be followed by an uppercase name and a colon.
  const QUANT = /^(?:([AE])([A-Z][A-Za-z0-9_]*)|([∀∃])\s*([A-Za-z][A-Za-z0-9_]*))\s*[:.]/;

  // Longest match first, so "<=>" never reads as "<" then "=>", and "=>" never
  // as an equation. + and * build terms (Chapter 15), so + is not "or" here.
  const OPERATORS = [
    ["<=>", "iff"], ["<->", "iff"], ["⇔", "iff"], ["↔", "iff"], ["≡", "iff"],
    ["=>", "imp"], ["->", "imp"], ["⇒", "imp"], ["→", "imp"], ["⊃", "imp"],
    ["/\\", "and"], ["&&", "and"], ["&", "and"], ["∧", "and"], ["^", "and"],
    ["\\/", "or"], ["||", "or"], ["|", "or"], ["∨", "or"],
    ["!=", "neq"], ["≠", "neq"], ["=", "="],
    ["~", "not"], ["!", "not"], ["¬", "not"], ["-", "not"],
    ["*", "*"], ["+", "+"],
    ["(", "("], [")", ")"], [",", ","],
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
      const quant = QUANT.exec(src.slice(i));
      if (quant) {
        const sign = quant[1] || quant[3];
        const raw = quant[2] || quant[4];
        tokens.push({
          kind: sign === "A" || sign === "∀" ? "all" : "exists",
          text: quant[0], raw: raw, v: raw.toUpperCase(),
        });
        i += quant[0].length;
        continue;
      }
      if (ch === "∀" || ch === "∃") {
        throw new Error("After " + ch + " write the variable and a dot, e.g. " + ch + "X.p(X).");
      }
      // A numeral like 0 is a name too: Chapter 13's arithmetic counts from it.
      const name = /^[A-Za-z0-9][A-Za-z0-9_]*/.exec(src.slice(i));
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
  //   unary::= ~ unary | AX: unary | EX: unary | equation | relation | ( iff )
  //   equation ::= term = term | term ≠ term
  //   relation ::= name ( "(" term ("," term)* ")" )?
  //   term ::= product ( + product )*     -- left associative, plus(x,y)
  //   product ::= primary ( * primary )*  -- left associative, times(x,y)
  //   primary ::= name ( "(" term ("," term)* ")" )? | ( term )
  // Flattening only happens at the same parenthesis level, so (p&q)&r stays nested.
  // A quantifier binds as tightly as ~, so AX: p(X) & AX: q(X) is a conjunction
  // of two quantified sentences and a wider scope is written AX: (p(X) & q(X)).
  // An equation is a relation like any other, named "=" — equal(a,b) reads as
  // a = b — and binds tighter than ~, so ~a = b is ¬(a = b), as in the chapter.
  function read(src, asTerm) {
    const tokens = tokenize(src);
    let pos = 0;
    const peek = () => tokens[pos];
    const eat = (kind) => (peek() && peek().kind === kind ? tokens[pos++] : null);

    // The arguments of a relation or a function, or null when there are none.
    function argList() {
      if (!(peek() && peek().kind === "(")) return null;
      pos++;
      const args = [term()];
      while (peek() && peek().kind === ",") { pos++; args.push(term()); }
      if (!eat(")")) throw new Error("Missing a closing parenthesis.");
      return args;
    }

    function term() {
      let left = product();
      while (peek() && peek().kind === "+") { pos++; left = { n: "plus", args: [left, product()] }; }
      return left;
    }

    function product() {
      let left = primary();
      while (peek() && peek().kind === "*") { pos++; left = { n: "times", args: [left, primary()] }; }
      return left;
    }

    function primary() {
      const tok = peek();
      if (tok && tok.kind === "(") {
        pos++;
        const inner = term();
        if (!eat(")")) throw new Error("Missing a closing parenthesis.");
        return inner;
      }
      if (!tok || tok.kind !== "atom") throw new Error("Expected a term.");
      pos++;
      return { n: tok.text, args: argList() || [] };
    }

    // A term followed by = or ≠, or null with nothing consumed. Both sides of
    // an equation are terms, and a term can open with "(" just as a formula
    // can, so this reads ahead and backs off when no = follows.
    function equation() {
      const start = pos;
      let left;
      try { left = term(); } catch (e) { pos = start; return null; }
      const op = peek();
      if (!op || (op.kind !== "=" && op.kind !== "neq")) { pos = start; return null; }
      pos++;
      const eq = equals(left, term());
      return op.kind === "=" ? eq : not(eq);
    }

    function unary() {
      const tok = peek();
      if (!tok) throw new Error("The formula ends too early.");
      if (tok.kind === "not") { pos++; return { t: "not", a: unary() }; }
      if (tok.kind === "all" || tok.kind === "exists") {
        pos++;
        const body = unary();
        // ∀x.p(x) comes in with a lowercase variable; the tool's variables are
        // uppercase, so rename as it is read and everything downstream is uniform.
        return { t: tok.kind, v: tok.v, a: toVariable(body, tok.raw, tok.v) };
      }
      if (tok.kind === "atom" || tok.kind === "(") {
        const eq = equation();
        if (eq) return eq;
      }
      if (tok.kind === "atom") {
        pos++;
        const args = argList() || [];
        return tok.text === "equal" && args.length === 2 ? equals(args[0], args[1])
                                                          : { t: "atom", name: tok.text, args: args };
      }
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

    const result = asTerm ? term() : iff();
    if (pos < tokens.length) {
      throw new Error('Unexpected "' + tokens[pos].text + '" after the ' + (asTerm ? "term." : "formula."));
    }
    return result;
  }

  // A formula, or a term on its own for the rules that ask for one. Each
  // takes exactly one argument, so both are safe to hand to Array.map.
  const parse = (src) => read(src, false);
  const parseTerm = (src) => read(src, true);

  const PREC = { atom: 5, not: 4, all: 4, exists: 4, and: 3, or: 2, imp: 1, iff: 0 };

  const equals = (s, t) => ({ t: "atom", name: "=", args: [s, t] });
  const isEquation = (f) => !!f && f.t === "atom" && f.name === "=" && (f.args || []).length === 2;

  // plus and times are written infix, the way the chapters write arithmetic,
  // * binding tighter than +, both left associative. A product inside a
  // product always keeps its parentheses — (x*y)*z against x*(y*z) is the
  // whole point of a group's associativity axiom — while a sum reads
  // x*x + 2*x + 1 without them.
  const TERM_PREC = { plus: 1, times: 2 };
  const infix = (t) => t.args.length === 2 && (t.n === "plus" || t.n === "times");

  function showTerm(t, parentPrec) {
    if (infix(t)) {
      const prec = TERM_PREC[t.n];
      const leftPrec = t.n === "times" ? prec + 0.5 : prec;
      const out = showTerm(t.args[0], leftPrec) + (t.n === "plus" ? " + " : "*") + showTerm(t.args[1], prec + 0.5);
      return prec < (parentPrec || 0) ? "(" + out + ")" : out;
    }
    return t.args.length ? t.n + "(" + t.args.map((a) => showTerm(a)).join(",") + ")" : t.n;
  }

  function show(f, parentPrec) {
    parentPrec = parentPrec === undefined ? -1 : parentPrec;
    const prec = PREC[f.t];
    let out;
    switch (f.t) {
      case "atom":
        if (isEquation(f)) return showTerm(f.args[0]) + " = " + showTerm(f.args[1]);
        return showTerm({ n: f.name, args: f.args || [] });
      case "not":
        // ¬(a = b) is written a ≠ b; it takes parentheses under another ¬.
        if (isEquation(f.a)) {
          out = showTerm(f.a.args[0]) + " ≠ " + showTerm(f.a.args[1]);
          return PREC.not - 0.1 < parentPrec ? "(" + out + ")" : out;
        }
        return SYM.not + show(f.a, PREC.not);
      case "all":
      case "exists":
        out = (f.t === "all" ? "∀" : "∃") + f.v + "." + show(f.a, prec);
        break;
      case "and":
      case "or":
        // A nested conjunction keeps its parentheses: (p ∧ q) ∧ r is a
        // different line from p ∧ q ∧ r, and And Elimination treats it so.
        out = f.args.map((a) => show(a, prec + 0.5)).join(" " + SYM[f.t] + " ");
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
      case "atom": return showTerm({ n: f.name, args: f.args || [] });
      case "not": return "~(" + key(f.a) + ")";
      case "all":
      case "exists": return f.t + " " + f.v + ".(" + key(f.a) + ")";
      case "and":
      case "or": return f.t + "(" + f.args.map(key).join(",") + ")";
      default: return f.t + "(" + key(f.a) + "," + key(f.b) + ")";
    }
  }
  const same = (x, y) => !!x && !!y && key(x) === key(y);
  const not = (f) => ({ t: "not", a: f });
  const imp = (a, b) => ({ t: "imp", a: a, b: b });

  /* --------------------------------------------------------------- quantifiers
   *
   * Variables are uppercase and everything else is an object constant, so a
   * term is ground exactly when no name in it is uppercase. That one convention
   * is what the four quantifier rules check against.
   */

  const isVariable = (name) => /^[A-Z]/.test(name);

  function termNames(t, out) {
    out = out || new Set();
    out.add(t.n);
    t.args.forEach((a) => termNames(a, out));
    return out;
  }

  const isGround = (t) => ![...termNames(t)].some(isVariable);

  // Names in relation arguments that no enclosing quantifier binds.
  function freeNames(f, bound, out) {
    bound = bound || new Set();
    out = out || new Set();
    switch (f.t) {
      case "atom":
        (f.args || []).forEach((a) => {
          termNames(a).forEach((n) => { if (!bound.has(n)) out.add(n); });
        });
        break;
      case "all":
      case "exists": {
        const inner = new Set(bound);
        inner.add(f.v);
        freeNames(f.a, inner, out);
        break;
      }
      case "not": freeNames(f.a, bound, out); break;
      case "and":
      case "or": f.args.forEach((a) => freeNames(a, bound, out)); break;
      default: freeNames(f.a, bound, out); freeNames(f.b, bound, out);
    }
    return out;
  }

  function substituteTerm(t, name, value) {
    if (t.n === name && !t.args.length) return value;
    return { n: t.n, args: t.args.map((a) => substituteTerm(a, name, value)) };
  }

  /* Replace free occurrences of the 0-ary term `name` by the term `value`.
   * Throws when a quantifier on the way down binds a name that `value` carries,
   * since the result would say something else entirely. */
  function substitute(f, name, value) {
    switch (f.t) {
      case "atom":
        return { t: "atom", name: f.name,
                 args: (f.args || []).map((a) => substituteTerm(a, name, value)) };
      case "all":
      case "exists":
        if (f.v === name) return f;                       // shadowed
        if (termNames(value).has(f.v) && freeNames(f.a, new Set([f.v])).has(name)) {
          throw new Error(showTerm(value) + " would be captured by " + f.v + ".");
        }
        return { t: f.t, v: f.v, a: substitute(f.a, name, value) };
      case "not": return { t: "not", a: substitute(f.a, name, value) };
      case "and":
      case "or": return { t: f.t, args: f.args.map((a) => substitute(a, name, value)) };
      default: return { t: f.t, a: substitute(f.a, name, value),
                        b: substitute(f.b, name, value) };
    }
  }

  // Used by the parser to normalize ∀x.p(x) into AX: p(X).
  function toVariable(body, raw, upper) {
    if (raw === upper) return body;
    try { return substitute(body, raw, { n: upper, args: [] }); }
    catch (e) { throw new Error("Mixing " + raw + " and " + upper + " as variables is ambiguous."); }
  }

  /* The term that `v` stands for, turning `pattern` into `target`: null when `v`
   * does not occur and the two are already identical, and an exception when no
   * single term works. This is the whole of instance checking — every one of the
   * four rules is "these two formulas differ by one substitution". */
  function instanceOf(pattern, v, target) {
    const found = [];

    function walkTerm(p, t, bound) {
      if (p.n === v && !p.args.length && !bound.has(v)) { found.push(t); return; }
      if (p.n !== t.n || p.args.length !== t.args.length) {
        throw new Error(showTerm(p) + " does not line up with " + showTerm(t));
      }
      p.args.forEach((a, i) => walkTerm(a, t.args[i], bound));
    }

    function walk(p, t, bound) {
      if (p.t !== t.t) throw new Error(show(p) + " does not line up with " + show(t));
      switch (p.t) {
        case "atom":
          if (p.name !== t.name || (p.args || []).length !== (t.args || []).length) {
            throw new Error(show(p) + " does not line up with " + show(t));
          }
          (p.args || []).forEach((a, i) => walkTerm(a, t.args[i], bound));
          break;
        case "all":
        case "exists": {
          if (p.v !== t.v) throw new Error(show(p) + " binds " + p.v + ", " + show(t) + " binds " + t.v);
          const inner = new Set(bound);
          inner.add(p.v);
          walk(p.a, t.a, inner);
          break;
        }
        case "not": walk(p.a, t.a, bound); break;
        case "and":
        case "or":
          if (p.args.length !== t.args.length) {
            throw new Error(show(p) + " does not line up with " + show(t));
          }
          p.args.forEach((a, i) => walk(a, t.args[i], bound));
          break;
        default: walk(p.a, t.a, bound); walk(p.b, t.b, bound);
      }
    }

    walk(pattern, target, new Set());
    if (!found.length) {
      if (!same(pattern, target)) throw new Error(show(pattern) + " is not " + show(target));
      return null;
    }
    const first = found[0];
    if (found.some((t) => showTerm(t) !== showTerm(first))) {
      throw new Error(v + " would have to stand for two different terms.");
    }
    if (!same(substitute(pattern, v, first), target)) {
      throw new Error("Putting " + showTerm(first) + " in for " + v + " does not give " + show(target) + ".");
    }
    return first;
  }

  /* Names Universal Introduction may not generalize: the ones the premises and
   * the open assumptions have already pinned down. A placeholder is arbitrary
   * only if nothing in force says anything about it. */
  function fixedNames(block, lines, premises) {
    const out = new Set();
    premises.forEach((p) => freeNames(p, new Set(), out));
    for (let b = block; b; b = b.parent) {
      if (b.id !== 0 && lines[b.start]) freeNames(lines[b.start].formula, new Set(), out);
    }
    return out;
  }

  /* ---------------------------------------------------------------- induction
   *
   * Chapter 13. Domain Closure and Induction both conclude AX: φ from cases of
   * φ, and both turn on the language — the object and function constants that
   * exist. Domain Closure needs φ[σ] for every object constant σ, which covers
   * every term only when there are no function constants. Induction needs that
   * base case and, for every function constant π, the inductive case
   *
   *   AM: (φ[M] ⇒ φ[π(M)])                      π unary  (linear, tree)
   *   AL: AM: (φ[L] ∧ φ[M] ⇒ φ[π(L,M)])         π binary (structural)
   *
   * and so on for higher arities. The inductive case may name its variables as
   * it likes; they need not match the conclusion's.
   */

  // The object and function constants some sentences use, in order of first
  // appearance, with the arity each function is applied at.
  function vocabulary(formulas) {
    const objects = [], functions = [], arity = Object.create(null);
    function term(t) {
      if (t.args.length) {
        if (!(t.n in arity)) { arity[t.n] = t.args.length; functions.push(t.n); }
        t.args.forEach(term);
      } else if (!isVariable(t.n) && objects.indexOf(t.n) === -1) {
        objects.push(t.n);
      }
    }
    function walk(f) {
      switch (f.t) {
        case "atom": (f.args || []).forEach(term); break;
        case "not":
        case "all":
        case "exists": walk(f.a); break;
        case "and":
        case "or": f.args.forEach(walk); break;
        default: walk(f.a); walk(f.b);
      }
    }
    formulas.forEach(walk);
    return { objects: objects, functions: functions, arity: arity };
  }

  // φ[τ] for the conclusion AX: φ.
  const caseOf = (conclusion, t) => substitute(conclusion.a, conclusion.v, t);
  const constant = (name) => ({ n: name, args: [] });

  // The inductive case of AX: φ for function constant fn, over these variables.
  function inductiveCase(conclusion, fn, vars) {
    const hyps = vars.map((v) => caseOf(conclusion, constant(v)));
    const step = caseOf(conclusion, { n: fn, args: vars.map(constant) });
    let out = imp(hyps.length === 1 ? hyps[0] : { t: "and", args: hyps }, step);
    for (let i = vars.length - 1; i >= 0; i--) out = { t: "all", v: vars[i], a: out };
    return out;
  }

  // The arity at which f is the inductive case of AX: φ for fn, or 0. The
  // variables are read off f itself, which is what lets them be renamed.
  function inductiveArity(f, conclusion, fn) {
    const vars = [];
    for (let node = f; node.t === "all"; node = node.a) {
      vars.push(node.v);
      if (new Set(vars).size !== vars.length) return 0;
      try { if (same(f, inductiveCase(conclusion, fn, vars))) return vars.length; }
      catch (e) { /* that variable would be captured; try a longer prefix */ }
    }
    return 0;
  }

  // For an error message: the inductive case written out, if it can be.
  function describeInductive(conclusion, fn, arity) {
    const pool = [conclusion.v, "X", "Y", "Z", "U", "V", "W"]
      .filter((v, i, all) => all.indexOf(v) === i);
    try { return show(inductiveCase(conclusion, fn, pool.slice(0, arity || 1))); }
    catch (e) { return "the inductive case for " + fn; }
  }

  /* Which of `formulas` are the base cases of AX: φ, one per object constant.
   * Returns { at: [indices] } in the order of the objects, or { error }. */
  function baseCases(conclusion, objects, formulas) {
    const at = [];
    for (const name of objects) {
      let want;
      try { want = caseOf(conclusion, constant(name)); }
      catch (e) { return { error: e.message }; }
      const i = formulas.findIndex((f) => same(f, want));
      if (i === -1) return { error: "Missing the base case for " + name + ": " + show(want) + "." };
      at.push(i);
    }
    return { at: at };
  }

  /* The base cases and then the inductive cases of AX: φ among `formulas`, as
   * indices, or { error }. A function the premises or goal use at some arity
   * has to be covered at that arity — anything else leaves its terms out. */
  function inductionCases(conclusion, language, formulas) {
    const base = baseCases(conclusion, language.objects, formulas);
    if (base.error) return base;
    const at = base.at.slice();
    for (const fn of language.functions) {
      const known = language.arity[fn];
      const i = formulas.findIndex((f) => {
        const k = inductiveArity(f, conclusion, fn);
        return k > 0 && (!known || k === known);
      });
      if (i === -1) {
        return { error: "Missing the inductive case for " + fn + ": " +
                        describeInductive(conclusion, fn, known) + "." };
      }
      at.push(i);
    }
    return { at: at };
  }

  /* Why the language rules out Domain Closure, Induction or Rational
   * Induction, or null when it does not. The same split as the Stanford tool:
   * Domain Closure needs object constants and no function constants, Induction
   * needs both, and Rational Induction is for arithmetic — numerals, + and *,
   * and nothing else. */
  function languageFor(rule, language) {
    if (rule === "rind") {
      const other = language.objects.filter((n) => !/^[0-9]+$/.test(n))
        .concat(language.functions.filter((n) => n !== "plus" && n !== "times"));
      return other.length
        ? "Rational Induction ranges over the numbers, but the language also has " + other.join(", ") + "."
        : null;
    }
    if (!language.objects.length) {
      return "The language has no object constants yet — add them with Objects +.";
    }
    if (rule === "dc" && language.functions.length) {
      return "With function constants (" + language.functions.join(", ") +
             ") there are infinitely many terms, so this needs Induction, not Domain Closure.";
    }
    if (rule === "ind" && !language.functions.length) {
      return "With no function constants the language is finite: use Domain Closure.";
    }
    return null;
  }

  /* The conclusion an inductive case points to: AM: (φ[M] ⇒ …) is about φ.
   * Used only to fill in the prompt, so a wrong guess costs nothing. */
  function guessInduction(language, formulas) {
    for (const f of formulas) {
      const vars = [];
      for (let node = f; node.t === "all"; node = node.a) {
        vars.push(node.v);
        const body = node.a;
        if (body.t !== "imp") continue;
        let phi = null;
        if (vars.length === 1) phi = body.a;
        else if (body.a.t === "and" && body.a.args.length === vars.length) phi = body.a.args[0];
        if (!phi) continue;
        const guess = { t: "all", v: vars[0], a: phi };
        if (!inductionCases(guess, language, formulas).error) return guess;
      }
    }
    return null;
  }

  /* ----------------------------------------------------------------- equality
   *
   * Chapter 15. Equality Introduction writes down σ = σ for any ground σ.
   * Equality Elimination takes φ and an equation σ = τ and gives φ with some or
   * all occurrences of σ replaced by τ — or of τ by σ, since the equation reads
   * both ways. A replacement never reaches under a quantifier that binds a name
   * in the equation, which is the chapter's substitutability condition.
   *
   * The two Rational rules are the Stanford tool's arithmetic over + and *.
   * Rational Equation writes down σ = τ when the two ground terms agree once
   * multiplied out; Rational Induction is induction over the naturals, from
   * φ[0] and AX: (φ[X] ⇒ φ[X + 1]).
   */

  const termKey = (t) => showTerm(t);
  const sameTerm = (s, t) => termKey(s) === termKey(t);
  const bindsInto = (v, from, to) => termNames(from).has(v) || termNames(to).has(v);

  // Every occurrence of `from` replaced by `to`, for the prompt's suggestion.
  function replaceTerm(t, from, to) {
    if (sameTerm(t, from)) return to;
    return { n: t.n, args: t.args.map((a) => replaceTerm(a, from, to)) };
  }

  function replaceAll(f, from, to) {
    switch (f.t) {
      case "atom": return { t: "atom", name: f.name, args: (f.args || []).map((a) => replaceTerm(a, from, to)) };
      case "all":
      case "exists": return bindsInto(f.v, from, to) ? f : { t: f.t, v: f.v, a: replaceAll(f.a, from, to) };
      case "not": return { t: "not", a: replaceAll(f.a, from, to) };
      case "and":
      case "or": return { t: f.t, args: f.args.map((a) => replaceAll(a, from, to)) };
      default: return { t: f.t, a: replaceAll(f.a, from, to), b: replaceAll(f.b, from, to) };
    }
  }

  // Whether q is p with some occurrences of `from` replaced by `to`.
  function termRewrites(p, q, from, to) {
    if (sameTerm(p, from) && sameTerm(q, to)) return true;
    return p.n === q.n && p.args.length === q.args.length &&
           p.args.every((a, i) => termRewrites(a, q.args[i], from, to));
  }

  function rewrites(p, q, from, to) {
    if (p.t !== q.t) return false;
    switch (p.t) {
      case "atom":
        return p.name === q.name && (p.args || []).length === (q.args || []).length &&
               (p.args || []).every((a, i) => termRewrites(a, q.args[i], from, to));
      case "all":
      case "exists":
        if (p.v !== q.v) return false;
        return bindsInto(p.v, from, to) ? same(p, q) : rewrites(p.a, q.a, from, to);
      case "not": return rewrites(p.a, q.a, from, to);
      case "and":
      case "or":
        return p.args.length === q.args.length && p.args.every((a, i) => rewrites(a, q.args[i], from, to));
      default: return rewrites(p.a, q.a, from, to) && rewrites(p.b, q.b, from, to);
    }
  }

  /* The ways two checked lines can be "φ, then the equation": the order they
   * were ticked first, so the prompt's suggestion follows the reader's lead. */
  function equalityPairs(items, formulaOf) {
    const pairs = [];
    if (isEquation(formulaOf(items[1]))) pairs.push([items[0], items[1]]);
    if (isEquation(formulaOf(items[0]))) pairs.push([items[1], items[0]]);
    return pairs;
  }

  // Whether `result` follows from φ by the equation, read either way.
  function eliminates(phi, eq, result) {
    const [s, t] = eq.args;
    return rewrites(phi, result, s, t) || rewrites(phi, result, t, s);
  }

  /* A ground term multiplied out: a map from monomial to coefficient, where a
   * monomial is a sorted list of the non-arithmetic subterms it multiplies.
   * Numerals are numbers; anything else — a, f(a), inv(c) — is opaque. */
  const isNumeral = (name) => /^[0-9]+$/.test(name);
  const MONO = "\u0001";

  function polynomial(t) {
    if (!t.args.length && isNumeral(t.n)) return new Map([["", BigInt(t.n)]]);
    if (t.n === "plus" && t.args.length === 2) {
      const out = new Map(polynomial(t.args[0]));
      polynomial(t.args[1]).forEach((c, m) => out.set(m, (out.get(m) || 0n) + c));
      return out;
    }
    if (t.n === "times" && t.args.length === 2) {
      const out = new Map();
      const right = polynomial(t.args[1]);
      polynomial(t.args[0]).forEach((c1, m1) => right.forEach((c2, m2) => {
        const m = m1.split(MONO).concat(m2.split(MONO)).filter(Boolean).sort().join(MONO);
        out.set(m, (out.get(m) || 0n) + c1 * c2);
      }));
      return out;
    }
    return new Map([[termKey(t), 1n]]);
  }

  function samePolynomial(s, t) {
    const canon = (p) => [...p].filter(([, c]) => c !== 0n).map(([m, c]) => m + "=" + c).sort().join(";");
    return canon(polynomial(s)) === canon(polynomial(t));
  }

  // AV: (φ[V] ⇒ φ[V + 1]), the inductive case Rational Induction needs.
  function successorCase(conclusion, v) {
    const step = caseOf(conclusion, { n: "plus", args: [constant(v), constant("1")] });
    return { t: "all", v: v, a: imp(caseOf(conclusion, constant(v)), step) };
  }

  // The base case φ[0] and the inductive case, as indices, or { error }.
  function rationalCases(conclusion, formulas) {
    let base;
    try { base = caseOf(conclusion, constant("0")); }
    catch (e) { return { error: e.message }; }
    const b = formulas.findIndex((f) => same(f, base));
    if (b === -1) return { error: "Missing the base case: " + show(base) + "." };
    const s = formulas.findIndex((f) => {
      try { return f.t === "all" && same(f, successorCase(conclusion, f.v)); }
      catch (e) { return false; }
    });
    if (s === -1) {
      let want = "∀X.(φ[X] ⇒ φ[X + 1])";
      try { want = show(successorCase(conclusion, conclusion.v)); } catch (e) { /* keep the schema */ }
      return { error: "Missing the inductive case: " + want + "." };
    }
    return { at: [b, s] };
  }

  function guessRational(formulas) {
    for (const f of formulas) {
      if (f.t !== "all" || f.a.t !== "imp") continue;
      const guess = { t: "all", v: f.v, a: f.a.a };
      if (!rationalCases(guess, formulas).error) return guess;
    }
    return null;
  }

  // A term from a prompt: parseTerm gives one, and parse gives a relation
  // that reads as one, e.g. f(a).
  function asTerm(x) {
    if (!x) return null;
    if (x.n !== undefined) return x;
    if (x.t === "atom" && !isEquation(x)) return { n: x.name, args: x.args || [] };
    return null;
  }

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
    { id: "ue", label: "Universal Elimination", short: "UE" },
    { id: "ui", label: "Universal Introduction", short: "UI" },
    { id: "ei", label: "Existential Introduction", short: "EI" },
    { id: "ee", label: "Existential Elimination", short: "EE" },
    { id: "dc", label: "Domain Closure", short: "DC" },
    { id: "ind", label: "Induction", short: "Ind" },
    { id: "qi", label: "Equality Introduction", short: "QI" },
    { id: "qe", label: "Equality Elimination", short: "QE" },
    { id: "req", label: "Rational Equation", short: "RatEq" },
    { id: "rind", label: "Rational Induction", short: "RatInd" },
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

  /* Existential Elimination needs EX: φ and AX: (φ ⇒ ψ) — the same φ, with the
   * variable renamed to match, and ψ free of that variable. Returns the ψ it
   * would conclude, or null when the two lines do not fit together. */
  function existentialPair(existential, universal) {
    if (!existential || !universal) return null;
    if (existential.t !== "exists" || universal.t !== "all") return null;
    if (universal.a.t !== "imp") return null;
    let antecedent;
    try { antecedent = substitute(universal.a.a, universal.v, { n: existential.v, args: [] }); }
    catch (e) { return null; }
    if (!same(antecedent, existential.a)) return null;
    return { conclusion: universal.a.b, v: universal.v };
  }

  function checkLine(line, lines, premises, language) {
    premises = premises || [];
    language = language || state.language;
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

      case "ue": {
        if (cited.length !== 1 || cited[0].t !== "all") {
          return { ok: false, msg: "Universal Elimination cites one universally quantified line." };
        }
        let t;
        try { t = instanceOf(cited[0].a, cited[0].v, f); }
        catch (e) { return { ok: false, msg: "This is not an instance of " + show(cited[0]) + ": " + e.message }; }
        if (t && !isGround(t)) {
          return { ok: false, msg: showTerm(t) + " is not ground, so Universal Elimination cannot put it in." };
        }
        return { ok: true };
      }

      case "ui": {
        if (f.t !== "all") return { ok: false, msg: "Universal Introduction concludes a universally quantified line." };
        if (cited.length !== 1) return { ok: false, msg: "Universal Introduction cites one line." };
        let t;
        try { t = instanceOf(f.a, f.v, cited[0]); }
        catch (e) { return { ok: false, msg: show(cited[0]) + " is not an instance of " + show(f) + ": " + e.message }; }
        if (!t) return { ok: true };                      // vacuous generalization
        if (t.args.length) {
          return { ok: false, msg: "Universal Introduction generalizes a placeholder, not " + showTerm(t) + "." };
        }
        if (fixedNames(line.block, lines, premises).has(t.n)) {
          return { ok: false, msg: t.n + " is no longer arbitrary here — it occurs in a premise or in an assumption that is still open." };
        }
        return { ok: true };
      }

      case "ei": {
        if (f.t !== "exists") return { ok: false, msg: "Existential Introduction concludes an existentially quantified line." };
        if (cited.length !== 1) return { ok: false, msg: "Existential Introduction cites one line." };
        let t;
        try { t = instanceOf(f.a, f.v, cited[0]); }
        catch (e) { return { ok: false, msg: show(cited[0]) + " is not an instance of " + show(f) + ": " + e.message }; }
        if (t && !isGround(t)) {
          return { ok: false, msg: showTerm(t) + " is not ground, so Existential Introduction cannot generalize it." };
        }
        return { ok: true };
      }

      case "ee": {
        if (cited.length !== 2) {
          return { ok: false, msg: "Existential Elimination cites an existential and a universally quantified implication." };
        }
        const pair = existentialPair(cited[0], cited[1]) || existentialPair(cited[1], cited[0]);
        if (!pair) {
          return { ok: false, msg: "The cited lines are no longer ∃X.φ together with ∀X.(φ ⇒ ψ) for the same φ." };
        }
        if (!same(pair.conclusion, f)) {
          return { ok: false, msg: "That implication concludes " + show(pair.conclusion) + ", not " + show(f) + "." };
        }
        if (freeNames(pair.conclusion).has(pair.v)) {
          return { ok: false, msg: pair.v + " occurs free in the conclusion, which Existential Elimination does not allow." };
        }
        return { ok: true };
      }

      // The language can change after the line is made, so these re-check
      // against the one declared now.
      case "dc": {
        if (f.t !== "all") return { ok: false, msg: "Domain Closure concludes a universally quantified line." };
        const why = languageFor("dc", language);
        if (why) return { ok: false, msg: why };
        const base = baseCases(f, language.objects, cited);
        return base.error ? { ok: false, msg: base.error } : { ok: true };
      }

      case "ind": {
        if (f.t !== "all") return { ok: false, msg: "Induction concludes a universally quantified line." };
        const why = languageFor("ind", language);
        if (why) return { ok: false, msg: why };
        const cases = inductionCases(f, language, cited);
        return cases.error ? { ok: false, msg: cases.error } : { ok: true };
      }

      case "qi":
        if (!isEquation(f) || !sameTerm(f.args[0], f.args[1]) || !isGround(f.args[0])) {
          return { ok: false, msg: "Equality Introduction writes down σ = σ for a ground term σ." };
        }
        return { ok: true };

      case "qe": {
        if (cited.length !== 2) return { ok: false, msg: "Equality Elimination cites a line and an equation." };
        const pairs = equalityPairs(cited, (x) => x);
        if (!pairs.length) return { ok: false, msg: "Neither cited line is an equation any more." };
        if (!pairs.some(([phi, eq]) => eliminates(phi, eq, f))) {
          return { ok: false, msg: "This is not the cited line with equals put in for equals." };
        }
        return { ok: true };
      }

      case "req":
        if (!isEquation(f) || !isGround(f.args[0]) || !isGround(f.args[1])) {
          return { ok: false, msg: "Rational Equation writes down an equation between ground terms." };
        }
        if (!samePolynomial(f.args[0], f.args[1])) return { ok: false, msg: "The two sides differ once multiplied out." };
        return { ok: true };

      case "rind": {
        if (f.t !== "all") return { ok: false, msg: "Rational Induction concludes a universally quantified line." };
        const why = languageFor("rind", language);
        if (why) return { ok: false, msg: why };
        const cases = rationalCases(f, cited);
        return cases.error ? { ok: false, msg: cases.error } : { ok: true };
      }
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

    /* Universal Elimination is determined by the term you put in, so that is
     * what it asks for — not the whole instance. */
    ue: function (sel, typed) {
      if (sel.length !== 1) return { error: "Check exactly one universally quantified line." };
      const f = sel[0].formula;
      if (f.t !== "all") return { error: "Line " + (sel[0].index + 1) + " is not universally quantified." };
      if (!typed) {
        return { prompt: "Universal Elimination — type the ground term to put in for " + f.v +
                         ", e.g. a, jack or inv(c). " + show(f) + " then gives you that instance.",
                 term: true };
      }
      const t = asTerm(typed);
      if (!t) return { error: "That is a formula, not a term. A term is a name like a, or f(a)." };
      if (!isGround(t)) {
        return { error: showTerm(t) + " contains a variable, and Universal Elimination only puts in ground terms." };
      }
      let out;
      try { out = substitute(f.a, f.v, t); }
      catch (e) { return { error: e.message }; }
      return { lines: [{ formula: out, rule: "ue", refIds: citeIds(sel) }] };
    },

    /* Universal and Existential Introduction both ask for the sentence to
     * introduce, because you choose the variable, and for EI also which
     * occurrences of the term to generalize. */
    ui: function (sel, typed, block) {
      if (sel.length !== 1) return { error: "Check exactly one line to generalize." };
      if (!typed) {
        return { prompt: "Universal Introduction — type the universally quantified sentence to introduce, e.g. ∀X.p(X).",
                 seed: "∀X." };
      }
      if (typed.t !== "all") return { error: "That is not a universally quantified sentence; it should start ∀, e.g. ∀X.p(X)." };
      let t;
      try { t = instanceOf(typed.a, typed.v, sel[0].formula); }
      catch (e) { return { error: show(sel[0].formula) + " is not an instance of " + show(typed) + ": " + e.message }; }
      if (t) {
        if (t.args.length) return { error: "Universal Introduction generalizes a placeholder, not " + showTerm(t) + "." };
        const fixed = fixedNames(block, state.lines, state.premises);
        if (fixed.has(t.n)) {
          return { error: t.n + " is not arbitrary: it occurs in a premise or in an assumption that is still open, so it cannot be generalized." };
        }
      }
      return { lines: [{ formula: typed, rule: "ui", refIds: citeIds(sel) }] };
    },

    ei: function (sel, typed) {
      if (sel.length !== 1) return { error: "Check exactly one line to generalize." };
      if (!typed) {
        return { prompt: "Existential Introduction — type the existential sentence to introduce, e.g. ∃X.p(X). " +
                         "One, some, or all occurrences of a ground term may be replaced.",
                 seed: "∃X." };
      }
      if (typed.t !== "exists") return { error: "That is not an existentially quantified sentence; it should start ∃, e.g. ∃X.p(X)." };
      let t;
      try { t = instanceOf(typed.a, typed.v, sel[0].formula); }
      catch (e) { return { error: show(sel[0].formula) + " is not an instance of " + show(typed) + ": " + e.message }; }
      if (t && !isGround(t)) {
        return { error: showTerm(t) + " contains a variable, and Existential Introduction only generalizes ground terms." };
      }
      return { lines: [{ formula: typed, rule: "ei", refIds: citeIds(sel) }] };
    },

    /* Existential Elimination is fully determined by the two lines, so it asks
     * for nothing. */
    ee: function (sel) {
      if (sel.length !== 2) return { error: "Check the existential and the universally quantified implication." };
      const [x, y] = sel;
      const forward = existentialPair(x.formula, y.formula);
      const pair = forward || existentialPair(y.formula, x.formula);
      if (!pair) {
        return { error: "Existential Elimination needs ∃X.φ together with ∀X.(φ ⇒ ψ) — the same φ, and a ψ that does not mention X." };
      }
      if (freeNames(pair.conclusion).has(pair.v)) {
        return { error: pair.v + " occurs free in " + show(pair.conclusion) + ", which Existential Elimination does not allow." };
      }
      const order = forward ? [x, y] : [y, x];
      return { lines: [{ formula: pair.conclusion, rule: "ee", refIds: citeIds(order) }] };
    },

    /* Domain Closure and Induction ask for the sentence to conclude, as the
     * Stanford tool does, and then find its cases among the checked lines. The
     * citations come out in the chapter's order: base cases by object, then
     * inductive cases by function. */
    dc: function (sel, typed) {
      const language = state.language;
      const why = languageFor("dc", language);
      if (why) return { error: why };
      if (!sel.length) return { error: "Check the instances, one for each of " + language.objects.join(", ") + "." };
      if (!typed) {
        return { prompt: "Domain Closure — type the universally quantified sentence to conclude, e.g. ∀X.p(X). " +
                         "The checked lines have to give its instance for each of " + language.objects.join(", ") + ".",
                 seed: "∀X." };
      }
      if (typed.t !== "all") return { error: "Domain Closure concludes a universally quantified sentence; it should start ∀." };
      const base = baseCases(typed, language.objects, sel.map((l) => l.formula));
      if (base.error) return { error: base.error };
      return { lines: [{ formula: typed, rule: "dc", refIds: base.at.map((i) => sel[i].id) }] };
    },

    ind: function (sel, typed) {
      const language = state.language;
      const why = languageFor("ind", language);
      if (why) return { error: why };
      if (!sel.length) return { error: "Check the base cases and the inductive cases." };
      const formulas = sel.map((l) => l.formula);
      if (!typed) {
        const guess = guessInduction(language, formulas);
        return { prompt: "Induction — type the universally quantified sentence to conclude, e.g. ∀X.p(X). " +
                         "The checked lines need its base case for " + language.objects.join(", ") +
                         " and its inductive case for " + language.functions.join(", ") + ".",
                 seed: guess ? show(guess) : "∀X." };
      }
      if (typed.t !== "all") return { error: "Induction concludes a universally quantified sentence; it should start ∀." };
      const cases = inductionCases(typed, language, formulas);
      if (cases.error) return { error: cases.error };
      return { lines: [{ formula: typed, rule: "ind", refIds: cases.at.map((i) => sel[i].id) }] };
    },

    /* Equality Introduction and Rational Equation cite nothing: one asks for
     * the term, the other for the equation. */
    qi: function (sel, typed) {
      if (!typed) {
        return { prompt: "Equality Introduction — type a ground term σ, e.g. a or f(a)*c; this adds σ = σ.", term: true };
      }
      const t = asTerm(typed);
      if (!t) return { error: "That is a formula, not a term. A term is a name like a, or f(a)." };
      if (!isGround(t)) return { error: showTerm(t) + " contains a variable; Equality Introduction takes a ground term." };
      return { lines: [{ formula: equals(t, t), rule: "qi", refIds: [] }] };
    },

    /* Equality Elimination asks for the result, because the chapter lets you
     * replace one occurrence, some, or all. The prompt starts from "all of
     * them", rewriting the line ticked first with the one ticked second. */
    qe: function (sel, typed) {
      if (sel.length !== 2) return { error: "Check the line to rewrite, then the equation to rewrite it with." };
      const pairs = equalityPairs(sel, (l) => l.formula);
      if (!pairs.length) return { error: "One of the two checked lines has to be an equation, σ = τ." };
      if (!typed) {
        const [phi, eq] = pairs[0];
        const [s, t] = eq.formula.args;
        let seed = replaceAll(phi.formula, s, t);
        if (same(seed, phi.formula)) seed = replaceAll(phi.formula, t, s);
        return { prompt: "Equality Elimination — type line " + (phi.index + 1) + " with " + showTerm(s) + " and " +
                         showTerm(t) + " exchanged where you want them; one occurrence, some, or all.",
                 seed: show(seed) };
      }
      const hit = pairs.find(([phi, eq]) => eliminates(phi.formula, eq.formula, typed));
      if (!hit) {
        return { error: show(typed) + " is not either checked line with one side of the equation put in for the other." };
      }
      return { lines: [{ formula: typed, rule: "qe", refIds: citeIds(hit) }] };
    },

    req: function (sel, typed) {
      if (!typed) {
        return { prompt: "Rational Equation — type an equation between ground terms that agree once multiplied out, " +
                         "e.g. (c + 1)*(c + 1) = c*c + 2*c + 1.", seed: "" };
      }
      if (!isEquation(typed)) return { error: "That is not an equation; it should read σ = τ." };
      const [s, t] = typed.args;
      if (!isGround(s) || !isGround(t)) return { error: "Both sides have to be ground terms, with no variables." };
      if (!samePolynomial(s, t)) return { error: showTerm(s) + " and " + showTerm(t) + " differ once multiplied out." };
      return { lines: [{ formula: typed, rule: "req", refIds: [] }] };
    },

    rind: function (sel, typed) {
      const why = languageFor("rind", state.language);
      if (why) return { error: why };
      if (!sel.length) return { error: "Check the base case φ[0] and the inductive case ∀X.(φ[X] ⇒ φ[X + 1])." };
      const formulas = sel.map((l) => l.formula);
      if (!typed) {
        const guess = guessRational(formulas);
        return { prompt: "Rational Induction — type the universally quantified sentence to conclude. " +
                         "The checked lines need its base case φ[0] and its inductive case ∀X.(φ[X] ⇒ φ[X + 1]).",
                 seed: guess ? show(guess) : "∀X." };
      }
      if (typed.t !== "all") return { error: "Rational Induction concludes a universally quantified sentence; it should start ∀." };
      const cases = rationalCases(typed, formulas);
      if (cases.error) return { error: cases.error };
      return { lines: [{ formula: typed, rule: "rind", refIds: cases.at.map((i) => sel[i].id) }] };
    },
  };

  // Rules that cite no lines, so a stale selection is no reason to refuse them.
  const CITES_NOTHING = new Set(["qi", "req"]);

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
    // What Domain Closure and Induction range over, and the part of it the
    // premises and goal use, which cannot be removed.
    language: { objects: [], functions: [], arity: Object.create(null) },
    vocab: { objects: [], functions: [] },
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
    syncPremises();
    render();
  }

  // A loaded question fixes its premises. Otherwise the tool is free-form and
  // the premises are just the Premise lines on the board, so adding, deleting
  // or undoing one also updates what UI may generalize and the language.
  const isFree = () => !(state.problem && state.problem.id === "loaded");

  function syncPremises() {
    if (!isFree()) return;
    state.premises = [];
    state.lines.forEach((l) => {
      if (l.rule === "premise" && !state.premises.some((p) => same(p, l.formula))) state.premises.push(l.formula);
    });
    resetLanguage(state.language.objects, state.language.functions);
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
    const sel = CITES_NOTHING.has(ruleId) ? [] : selectedLines();

    if (ruleId === "premise" || ruleId === "assume") return addTypedLine(ruleId, typed);
    if (ruleId === "ii") return applyII(sel);

    const apply = APPLY[ruleId];
    if (!apply) return;

    const block = currentBlock();
    const stranded = sel.find((l) => !block.chain.has(l.block.id));
    if (stranded) {
      return say("Line " + (stranded.index + 1) + " is inside a subproof that has already closed, so it cannot be used here.");
    }

    const result = apply(sel, typed, block);
    if (result.error) return say(result.error);
    if (result.prompt) return openPrompt(ruleId, result.prompt, result.seed, { term: !!result.term });

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
      syncPremises();
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
    syncPremises();
    say("");
    render();
  }

  /* ------------------------------------------------------------ typed input */

  // A prompt reads a formula unless `opts` says otherwise: `term` for the
  // rules that take a term, `lang` for names to add to or remove from the
  // language.
  function openPrompt(ruleId, label, seed, opts) {
    opts = opts || {};
    state.pending = { rule: ruleId, label: label, lang: opts.lang || null, term: !!opts.term };
    render();
    const input = $("#fitch-entry-input");
    input.value = seed || "";
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  function submitPrompt() {
    const input = $("#fitch-entry-input");
    if (state.pending.lang) return editLanguage(state.pending.lang, input.value);
    let typed;
    try { typed = state.pending.term ? parseTerm(input.value) : parse(input.value); }
    catch (e) { return say(e.message); }
    runRule(state.pending.rule, typed);
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

  /* --------------------------------------------------------------- language
   *
   * The Objects and Functions lines at the top of the board. They start as the
   * constants the premises and the goal use, plus any the problem lists, and
   * can be extended with +. Only the extensions can be taken out again: a
   * language that left out one of the problem's own names would let Induction
   * conclude more than the premises support. */

  const union = (a, b) => a.concat(b.filter((n, i) => a.indexOf(n) === -1 && b.indexOf(n) === i));

  function resetLanguage(objects, functions) {
    const own = vocabulary(state.premises.concat(state.goal ? [state.goal] : []));
    state.vocab = { objects: own.objects, functions: own.functions };
    state.language = {
      objects: union(own.objects, objects || []),
      functions: union(own.functions, functions || []),
      arity: own.arity,
    };
  }

  function editLanguage(lang, text) {
    const kind = lang.kind;
    const other = kind === "objects" ? "functions" : "objects";
    const names = text.split(/[\s,]+/).filter(Boolean);
    if (!names.length) return say("Type one or more names, separated by commas.");
    for (const n of names) {
      if (!/^[A-Za-z0-9][A-Za-z0-9_]*$/.test(n)) return say('"' + n + '" is not a name.');
      if (isVariable(n)) return say(n + " starts with a capital letter, which makes it a variable, not a constant.");
      if (lang.adding && state.language[other].indexOf(n) !== -1) {
        return say(n + " is already one of the " + (other === "objects" ? "object" : "function") + " constants.");
      }
      if (!lang.adding && state.vocab[kind].indexOf(n) !== -1) {
        return say(n + " occurs in the premises or the goal, so it stays in the language.");
      }
      if (!lang.adding && state.language[kind].indexOf(n) === -1) return say(n + " is not in the language.");
    }
    state.language[kind] = lang.adding
      ? union(state.language[kind], names)
      : state.language[kind].filter((n) => names.indexOf(n) === -1);
    state.pending = null;
    say("");
    render();
  }

  function renderLanguage() {
    const objects = $("#fitch-objects");
    const functions = $("#fitch-functions");
    if (objects) objects.textContent = state.language.objects.join(", ") || "none";
    if (functions) functions.textContent = state.language.functions.join(", ") || "none";
    // Greyed out the way the Stanford tool greys them, with the reason on hover.
    ["dc", "ind", "rind"].forEach((id) => {
      const button = ruleButtons[id];
      if (!button) return;
      const why = languageFor(id, state.language);
      button.disabled = !!why;
      button.title = why || "";
    });
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
      const result = checkLine(line, lines, state.premises, state.language);
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
    // Names for the language take no logical symbols.
    const palette = entry.querySelector(".fitch-palette");
    if (palette) palette.hidden = !!(state.pending && state.pending.lang);
    renderLanguage();

    const reached = state.goal && lines.some((l) => l.depth === 0 && l.result.ok && same(l.formula, state.goal));
    const banner = $("#fitch-verdict");
    banner.className = "fitch-verdict";
    banner.hidden = !state.goal && !state.goalError;
    if (!state.goal) {
      banner.textContent = state.goalError ? "Goal does not parse: " + state.goalError : "";
      banner.classList.add("verdict-error");
    } else if (reached && allValid) {
      banner.textContent = "✓ Proved. " + show(state.goal) + " follows from the premises.";
      banner.classList.add("verdict-done");
      reportSolved();
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

  /* --------------------------------------------------------------- progress */

  // A finished proof of a stored question counts towards its level. The server
  // is told the id and nothing else: it knows the chapter and the band, and it
  // holds the worked answer already. Reported once per page, because render()
  // runs on every click and the proof stays finished.
  let reported = false;

  function reportSolved() {
    const loaded = window.__ILO_QUESTION;
    // Only for the question the page was opened on — not a built-in problem
    // picked from the list afterwards — and only when someone is signed in.
    if (reported || !loaded || !loaded.id) return;
    if (!state.problem || state.problem.id !== "loaded") return;
    reported = true;

    fetch("/api/progress/solved", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question_id: loaded.id }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => { if (data) sayProgress(data); })
      // A lost report is not worth interrupting a finished proof over; the
      // level count is recomputed from the records on the next page anyway.
      .catch(() => {});
  }

  function sayProgress(data) {
    const note = $("#fitch-progress");
    if (!note) return;

    const parts = [];
    if (!data.first_solve) parts.push("You had already solved this one.");
    else parts.push("Counted: " + data.solved + " of " + data.need + " at this level.");
    (data.unlocked || []).forEach((level) => {
      parts.push("Unlocked " + level.band + " in Chapter " + level.chapter + ".");
    });
    if (data.unlocked && data.unlocked.length) parts.push("See the dashboard.");

    note.textContent = parts.join(" ");
    note.classList.toggle("is-unlock", !!(data.unlocked && data.unlocked.length));
    note.hidden = false;
  }

  /* ------------------------------------------------------------------ setup */

  function loadProblem(problem) {
    state.problem = problem;
    state.premiseSrc = problem.premises.slice();
    state.goalSrc = problem.goal;
    reparseGoal();
    resetLanguage(problem.objects, problem.functions);
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

  function resetProof() {
    if (isFree()) { state.premises = []; resetLanguage(); }
    resetLines();
  }

  function resetLines() {
    state.lines = state.premises.map((p) => makeLine({ formula: p, rule: "premise", depth: 0 }));
    state.selected.clear();
    state.pending = null;
    state.history = [];
    say("");
    render();
  }

  const ruleButtons = {};

  function buildButtons() {
    // Laid out in the Stanford tool's five columns: Premise and the editing
    // buttons; Negation, And and Or; Reiteration, Assumption, Implication and
    // Biconditional; the quantifiers with Domain Closure and Induction; and
    // equality with the Rational rules.
    const columns = [
      ["premise"],
      ["ni", "ne", "ai", "ae", "oi", "oe"],
      ["reit", "assume", "ii", "ie", "bi", "be"],
      ["ui", "ue", "ei", "ee", "dc", "ind"],
      ["qi", "qe", "req", "rind"],
    ];
    const grid = $("#fitch-buttons");
    columns.forEach((ids) => {
      const col = el("div", "fitch-bcol");
      ids.forEach((id) => {
        const b = el("button", "fitch-rule-btn", RULE_BY_ID[id].label);
        b.type = "button";
        b.addEventListener("click", () => runRule(id));
        ruleButtons[id] = b;
        col.appendChild(b);
      });
      grid.appendChild(col);
    });
    // The editing buttons sit under Premise, as Delete does in the Stanford tool.
    const first = grid.firstElementChild;
    [["Undo", undo], ["Delete", deleteSelected], ["Reset", resetProof]].forEach(([label, fn]) => {
      const b = el("button", "fitch-rule-btn fitch-util", label);
      b.type = "button";
      b.addEventListener("click", fn);
      first.appendChild(b);
    });
  }

  function init() {
    if (!$("#fitch-lines")) return; // Not on the Fitch page.
    [["objects", "Objects", "object constants"], ["functions", "Functions", "function constants"]]
      .forEach(([kind, label, noun]) => {
        const add = $("#fitch-" + kind + "-add");
        const remove = $("#fitch-" + kind + "-remove");
        if (add) add.addEventListener("click", () => openPrompt("lang",
          label + " — type the " + noun + " to add, separated by commas.", "",
          { lang: { kind: kind, adding: true } }));
        if (remove) remove.addEventListener("click", () => openPrompt("lang",
          label + " — type the " + noun + " to remove. The ones the premises or the goal use stay.", "",
          { lang: { kind: kind, adding: false } }));
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
    // Opened from the Dashboard or Generate: that question. Otherwise a blank
    // proof, the way the Stanford tool starts.
    const q = window.__ILO_QUESTION;
    loadProblem(q ? { id: "loaded", premises: q.premises, goal: q.goal, objects: q.objects || [] }
                  : { id: "blank", premises: [], goal: "" });
  }

  // Exposed for the console and for tests.
  window.Fitch = {
    parse: parse, show: show, same: same, analyze: analyze, checkLine: checkLine,
    runRule: runRule, state: state, loadProblem: loadProblem, RULES: RULES,
    APPLY: APPLY, substitute: substitute, instanceOf: instanceOf,
    freeNames: freeNames, isGround: isGround, showTerm: showTerm,
    vocabulary: vocabulary, parseTerm: parseTerm,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
