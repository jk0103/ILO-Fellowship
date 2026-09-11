"""Tests for ch10_checker, the Chapter 10 relational Fitch checker.

The proofs the chapter works through in its own text must pass, and the
unsound patterns it explicitly warns against must be refused. Everything runs
offline; no API key and no network.

Run:  python3 test_ch10_checker.py
"""

import ch10_checker as cc

checks = []


def check(label, condition):
    checks.append((label, bool(condition)))
    print("%-52s %s" % (label, "PASS" if condition else "FAIL"))


def line(formula, rule, depth, refs=None, subref=None):
    return {"formula": formula, "rule": rule, "depth": depth,
            "refs": refs or [], "subref": subref}


def accepts(label, premises, goal, steps, constants=None):
    problems = cc.check_proof(premises, goal, steps, constants)
    check(label, not problems)
    if problems:
        for problem in problems:
            print("    " + problem)


def rejects(label, premises, goal, steps, constants=None, because=""):
    problems = cc.check_proof(premises, goal, steps, constants)
    hit = any(because in p for p in problems) if because else bool(problems)
    check(label, hit)
    if not hit:
        print("    got:", problems or "no complaint at all")


# --- the grammar ------------------------------------------------------------

for src in ["∀x.(p(x) ∧ q(x))", "∀x.p(x) ∧ ∀x.q(x)", "∃x.¬p(x)", "¬∀x.p(x)",
            "∀x.∀y.(∃z.loves(y,z) ⇒ loves(x,y))", "p(c) ∧ q(c) ⇒ ∃x.q(x)",
            "∀x.∃y.p(x,y)"]:
    check(f"round trips: {src}", cc.show(cc.parse(src)) == src)

check("quantifiers bind tightly, as the chapter writes them",
      cc.parse("∀x.p(x) ∧ ∀x.q(x)")[0] == "and")

# --- the chapter's own proofs ----------------------------------------------

accepts("10.5 existential pattern, worked in the text",
        ["∃x.(p(x) ∧ q(x))"], "∃x.q(x)", [
            line("∃x.(p(x) ∧ q(x))", "premise", 0),
            line("p(c) ∧ q(c)", "assume", 1),
            line("q(c)", "ae", 1, [2]),
            line("∃x.q(x)", "ei", 1, [3]),
            line("p(c) ∧ q(c) ⇒ ∃x.q(x)", "ii", 0, None, [2, 4]),
            line("∀x.(p(x) ∧ q(x) ⇒ ∃x.q(x))", "ui", 0, [5]),
            line("∃x.q(x)", "ee", 0, [1, 6]),
        ])

accepts("10.3 everybody loves a lover, with placeholders",
        ["∀y.∃z.loves(y,z)", "∀x.∀y.(∃z.loves(y,z) ⇒ loves(x,y))"],
        "∀x.∀y.loves(x,y)", [
            line("∀y.∃z.loves(y,z)", "premise", 0),
            line("∀x.∀y.(∃z.loves(y,z) ⇒ loves(x,y))", "premise", 0),
            line("∃z.loves(d,z)", "ue", 0, [1]),
            line("∀y.(∃z.loves(y,z) ⇒ loves(c,y))", "ue", 0, [2]),
            line("∃z.loves(d,z) ⇒ loves(c,d)", "ue", 0, [4]),
            line("loves(c,d)", "ie", 0, [5, 3]),
            line("∀y.loves(c,y)", "ui", 0, [6]),
            line("∀x.∀y.loves(x,y)", "ui", 0, [7]),
        ])

accepts("10.4 an existential antecedent becomes universal",
        ["∀x.(∃y.p(x,y) ⇒ q(x))"], "∀x.∀y.(p(x,y) ⇒ q(x))", [
            line("∀x.(∃y.p(x,y) ⇒ q(x))", "premise", 0),
            line("∃y.p(c,y) ⇒ q(c)", "ue", 0, [1]),
            line("p(c,d)", "assume", 1),
            line("∃y.p(c,y)", "ei", 1, [3]),
            line("q(c)", "ie", 1, [2, 4]),
            line("p(c,d) ⇒ q(c)", "ii", 0, None, [3, 5]),
            line("∀y.(p(c,y) ⇒ q(c))", "ui", 0, [6]),
            line("∀x.∀y.(p(x,y) ⇒ q(x))", "ui", 0, [7]),
        ])

accepts("10.5 Existential Elimination in one step",
        ["∃x.p(a,x)", "∀x.(p(a,x) ⇒ q(a))"], "q(a)", [
            line("∃x.p(a,x)", "premise", 0),
            line("∀x.(p(a,x) ⇒ q(a))", "premise", 0),
            line("q(a)", "ee", 0, [1, 2]),
        ])

accepts("10.6 Domain Closure over a fixed language",
        ["p(a)", "p(b)"], "∀x.p(x)", [
            line("p(a)", "premise", 0),
            line("p(b)", "premise", 0),
            line("∀x.p(x)", "dc", 0, [1, 2]),
        ], constants=["a", "b"])

# --- what the chapter warns against ---------------------------------------

rejects("Existential Elimination leaving the variable free",
        ["∃x.p(x)", "∀x.(p(x) ⇒ q(x))"], "∀x.q(x)", [
            line("∃x.p(x)", "premise", 0),
            line("∀x.(p(x) ⇒ q(x))", "premise", 0),
            line("q(x)", "ee", 0, [1, 2]),
            line("∀x.q(x)", "ui", 0, [3]),
        ], because="occurs free in the conclusion")

rejects("Existential Introduction over a bound variable",
        ["∀x.hates(x,x)"], "∃y.∀x.hates(x,y)", [
            line("∀x.hates(x,x)", "premise", 0),
            line("∃y.∀x.hates(x,y)", "ei", 0, [1]),
        ], because="captured")

rejects("Universal Introduction over a name fixed by a premise",
        ["p(a)"], "∀x.p(x)", [
            line("p(a)", "premise", 0),
            line("∀x.p(x)", "ui", 0, [1]),
        ], because="not arbitrary")

rejects("Universal Introduction inside its own assumption",
        ["∀x.∃y.p(x,y)"], "∀x.p(x,x)", [
            line("∀x.∃y.p(x,y)", "premise", 0),
            line("∃y.p(c,y)", "ue", 0, [1]),
            line("p(c,d)", "assume", 1),
            line("∀x.p(x,d)", "ui", 1, [3]),
            line("p(c,d) ⇒ ∀x.p(x,d)", "ii", 0, None, [3, 4]),
            line("∀x.p(x,x)", "ui", 0, [5]),
        ], because="not arbitrary")

rejects("Domain Closure missing an instance",
        ["p(a)"], "∀x.p(x)", [
            line("p(a)", "premise", 0),
            line("∀x.p(x)", "dc", 0, [1]),
        ], constants=["a", "b"], because="instance")

rejects("Domain Closure without a fixed language",
        ["p(a)"], "∀x.p(x)", [
            line("p(a)", "premise", 0),
            line("∀x.p(x)", "dc", 0, [1]),
        ], because="fixes the object constants")

rejects("Universal Elimination that is not an instance",
        ["∀x.p(x,x)"], "p(a,b)", [
            line("∀x.p(x,x)", "premise", 0),
            line("p(a,b)", "ue", 0, [1]),
        ], because="two different terms")

# --- the propositional rules still bite ------------------------------------

rejects("Negation Introduction citing one line twice",
        ["p(a) ⇒ q(a)"], "¬p(a)", [
            line("p(a) ⇒ q(a)", "premise", 0),
            line("¬p(a)", "ni", 0, [1, 1]),
        ], because="different lines")

rejects("citing a line inside a closed subproof",
        ["p(a)"], "q(a)", [
            line("p(a)", "premise", 0),
            line("p(a)", "assume", 1),
            line("p(a) ⇒ p(a)", "ii", 0, None, [2, 2]),
            line("q(a)", "reit", 0, [2]),
        ], because="already closed")

rejects("Existential Introduction passed off as double negation",
        ["¬p(c)"], "¬¬p(c)", [
            line("¬p(c)", "premise", 0),
            line("¬¬p(c)", "ei", 0, [1]),
        ], because="Existential Introduction")

rejects("an open sentence as the goal",
        ["∀x.p(x)"], "p(x)", [
            line("∀x.p(x)", "premise", 0),
            line("p(x)", "ue", 0, [1]),
        ], because="not a closed sentence")

rejects("a proof that ends on something other than the goal",
        ["∀x.p(x)"], "∃x.p(x)", [
            line("∀x.p(x)", "premise", 0),
            line("p(a)", "ue", 0, [1]),
        ], because="not the goal")

check("difficulty bands on proof length",
      (cc.difficulty([0] * 4), cc.difficulty([0] * 15), cc.difficulty([0] * 30))
      == ("easy", "medium", "hard"))

failed = [label for label, ok in checks if not ok]
print("\n%d/%d passed" % (len(checks) - len(failed), len(checks)))
if failed:
    print("FAILED:", ", ".join(failed))
    raise SystemExit(1)
