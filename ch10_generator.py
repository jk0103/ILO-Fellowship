"""Generate Chapter 10 (Relational Logic) Fitch exercises with the GPT API.

The model is grounded on "Introduction to Logic - Chapter 10" through a
file_search vector store, so the exercises it writes stay inside the rule set
that chapter teaches and read like the Exercise 10.x list at the end of it.

Nothing the model returns is trusted. Every candidate is checked locally by
ch10_checker: each line must follow from the lines it cites, under the rule it
names and the restrictions Chapter 10 places on that rule. Fitch is sound, so a
proof that passes is a proof, and its goal really is entailed by its premises. A
proof that fails is handed back to the model with the checker's complaints and
one repair attempt. Only what survives is returned, and its difficulty comes
from the length of the verified proof, not from the model's opinion.

CLI:
    export OPENAI_API_KEY=...
    python ch10_generator.py -n 5 --difficulty medium -o ch10_questions.json
"""

import argparse
import json
import os
import sys
import time

import requests

import ch10_checker as cc

import load_env

load_env.load()

API_URL = "https://api.openai.com/v1/responses"
MODEL = os.environ.get("FITCH_MODEL", "gpt-4.1")

# Vector store holding "Introduction to Logic - Chapter 10.html".
VECTOR_STORE_ID = os.environ.get(
    "CH10_VECTOR_STORE_ID", "vs_6aa3f2d8cd80819191a883102f447895"
)

REPAIR_ATTEMPTS = 2

# Rule descriptions for the prompt; the ids themselves come from the checker.
RULE_NOTES = {
    "premise": "a premise, at depth 0",
    "assume": "an assumption; it opens a subproof and is its first line",
    "reit": "refs [i] — repeat line i verbatim",
    "ai": "refs [i,j,...] — from the conjuncts infer the conjunction",
    "ae": "refs [i] — from a conjunction infer one conjunct",
    "oi": "refs [i] — from φ infer any disjunction with φ as a disjunct",
    "oe": "refs [d,c1,c2] — a disjunction plus one implication per disjunct, "
          "all sharing a consequent, gives that consequent",
    "ni": "refs [i,j] — from φ ⇒ ψ and φ ⇒ ¬ψ, on two different lines, infer ¬φ",
    "ne": "refs [i] — from ¬¬φ infer φ",
    "ii": "subref [a,b] — discharge the subproof opened at a, whose line b is "
          "the consequent, into (assumption ⇒ line b)",
    "ie": "refs [i,j] — from φ ⇒ ψ and φ infer ψ",
    "bi": "refs [i,j] — from φ ⇒ ψ and ψ ⇒ φ infer φ ⇔ ψ",
    "be": "refs [i] — from φ ⇔ ψ infer either direction",
    "ue": "refs [i] — Universal Elimination: from ∀ν.φ infer φ with ν replaced "
          "throughout by a ground term τ",
    "ui": "refs [i] — Universal Introduction: from φ containing a placeholder σ "
          "infer ∀ν.φ with σ replaced by ν",
    "ei": "refs [i] — Existential Introduction: from φ containing a ground term "
          "τ infer ∃ν.φ with one, some, or all occurrences of τ replaced by ν",
    "ee": "refs [i,j] — Existential Elimination: from ∃ν.φ and ∀ν.(φ ⇒ ψ), "
          "where ν is not free in ψ, infer ψ",
    "dc": "refs [i,...] — Domain Closure: from φ[σ] for every object constant σ "
          "of the language infer ∀ν.φ[ν]",
}
RULES = cc.RULES

# The chapter's own exercises: the style reference, and the do-not-repeat list.
CHAPTER_EXERCISES = [
    "Given ∀x.(p(x) ∧ q(x)), use the Fitch System to prove ∀x.p(x) ∧ ∀x.q(x).",
    "Given ∀x.p(x) ∧ ∀x.q(x), use the Fitch System to prove ∀x.(p(x) ∧ q(x)).",
    "Given ∀x.(p(x) ⇒ q(x)), use the Fitch System to prove ∀x.p(x) ⇒ ∀x.q(x).",
    "Given ∀x.p(x) ∨ ∀x.q(x), use the Fitch System to prove ∀x.(p(x) ∨ q(x)).",
    "Given ∀x.∀y.p(x,y), use the Fitch System to prove ∀y.∀x.p(x,y).",
    "Given ∃x.(p(x) ∧ q(x)), use the Fitch System to prove ∃x.p(x) ∧ ∃x.q(x).",
    "Given ∃x.(p(x) ∨ q(x)), use the Fitch System to prove ∃x.p(x) ∨ ∃x.q(x).",
    "Given ∃x.p(x) ∨ ∃x.q(x), use the Fitch System to prove ∃x.(p(x) ∨ q(x)).",
    "Given ∃x.∃y.p(x,y), use the Fitch System to prove ∃y.∃x.p(x,y).",
    "Given ∃y.∀x.p(x,y), use the Fitch system to prove ∀x.∃y.p(x,y).",
    "Given ∃x.¬p(x), use the Fitch System to prove ¬∀x.p(x).",
    "Given ∀x.¬p(x), use the Fitch System to prove ¬∃x.p(x).",
    "Given ¬∃x.p(x), use the Fitch System to prove ∀x.¬p(x).",
    "Given ¬∀x.p(x), use the Fitch System to prove ∃x.¬p(x).",
    "Consider a language with just three object constants - a, b, and c. Given "
    "p(a,b) and p(b,c) and p(c,a), use the Fitch System to prove ∀x.∃y.p(x,y).",
    "Consider a language with just two object constants - a and b. Given ¬p(a) "
    "and q(b), use the Fitch System to prove ∀x.(p(x) ⇒ q(x)).",
]

# The same exercises as (premises, goal), so a candidate that merely renames one
# can be recognized and dropped.
CHAPTER_ARGUMENTS = [
    (["∀x.(p(x) ∧ q(x))"], "∀x.p(x) ∧ ∀x.q(x)"),
    (["∀x.p(x) ∧ ∀x.q(x)"], "∀x.(p(x) ∧ q(x))"),
    (["∀x.(p(x) ⇒ q(x))"], "∀x.p(x) ⇒ ∀x.q(x)"),
    (["∀x.p(x) ∨ ∀x.q(x)"], "∀x.(p(x) ∨ q(x))"),
    (["∀x.∀y.p(x,y)"], "∀y.∀x.p(x,y)"),
    (["∃x.(p(x) ∧ q(x))"], "∃x.p(x) ∧ ∃x.q(x)"),
    (["∃x.(p(x) ∨ q(x))"], "∃x.p(x) ∨ ∃x.q(x)"),
    (["∃x.p(x) ∨ ∃x.q(x)"], "∃x.(p(x) ∨ q(x))"),
    (["∃x.∃y.p(x,y)"], "∃y.∃x.p(x,y)"),
    (["∃y.∀x.p(x,y)"], "∀x.∃y.p(x,y)"),
    (["∃x.¬p(x)"], "¬∀x.p(x)"),
    (["∀x.¬p(x)"], "¬∃x.p(x)"),
    (["¬∃x.p(x)"], "∀x.¬p(x)"),
    (["¬∀x.p(x)"], "∃x.¬p(x)"),
    (["p(a,b)", "p(b,c)", "p(c,a)"], "∀x.∃y.p(x,y)"),
    (["¬p(a)", "q(b)"], "∀x.(p(x) ⇒ q(x))"),
    # and the two the chapter works through in the text itself
    (["∃x.(p(x) ∧ q(x))"], "∃x.q(x)"),
    (["∀x.(∃y.p(x,y) ⇒ q(x))"], "∀x.∀y.(p(x,y) ⇒ q(x))"),
]

# A worked proof from the chapter itself, so the JSON shape is unambiguous.
EXAMPLE = {
    "prompt": "Given ∃x.(p(x) ∧ q(x)), use the Fitch System to prove ∃x.q(x).",
    "premises": ["∃x.(p(x) ∧ q(x))"],
    "goal": "∃x.q(x)",
    "constants": [],
    "hint": "Assume the scope for a placeholder, prove the goal inside the "
            "subproof, then get it out with Implication Introduction, "
            "Universal Introduction, and Existential Elimination.",
    "rules_used": ["ae", "ei", "ii", "ui", "ee"],
    "proof": [
        {"formula": "∃x.(p(x) ∧ q(x))", "rule": "premise", "depth": 0,
         "refs": [], "subref": None},
        {"formula": "p(c) ∧ q(c)", "rule": "assume", "depth": 1,
         "refs": [], "subref": None},
        {"formula": "q(c)", "rule": "ae", "depth": 1, "refs": [2],
         "subref": None},
        {"formula": "∃x.q(x)", "rule": "ei", "depth": 1, "refs": [3],
         "subref": None},
        {"formula": "p(c) ∧ q(c) ⇒ ∃x.q(x)", "rule": "ii", "depth": 0,
         "refs": [], "subref": [2, 4]},
        {"formula": "∀x.(p(x) ∧ q(x) ⇒ ∃x.q(x))", "rule": "ui", "depth": 0,
         "refs": [5], "subref": None},
        {"formula": "∃x.q(x)", "rule": "ee", "depth": 0, "refs": [1, 6],
         "subref": None},
    ],
}

SYSTEM_PROMPT = """\
You write Relational Logic exercises, with full worked proofs, for the Fitch \
system taught in Chapter 10 of "Introduction to Logic". Consult that chapter \
with file_search before answering, and follow it exactly — its rules, its \
restrictions, and the phrasing of its own Exercise 10.x list.

LANGUAGE. Connectives ¬ ∧ ∨ ⇒ ⇔ only, written with those Unicode symbols. \
Quantifiers ∀ and ∃, each written immediately before its variable and followed \
by a period: ∀x.φ, ∃y.φ. Variables x, y, z. Object constants and placeholders a, b, c, d and \
short lowercase names (jack, jill) — never reuse a variable letter as a \
placeholder, so a line introduced by Universal Elimination reads p(c), not \
p(x). Relation constants p, q, r with one or two \
arguments, or short lowercase names (loves, hates). Premises and the goal must \
be closed sentences: no free variables.

RULES. These are the entire system — the eleven propositional rules of the \
earlier chapter plus the five quantifier rules of Chapter 10. There is NO False \
Introduction, NO False Elimination, and NO ex falso: a contradiction never \
licenses an arbitrary conclusion. Each line carries a rule id:
{rules}

QUANTIFIER RESTRICTIONS, which the chapter is strict about:
  ue  the term substituted in must be ground.
  ei  the term being generalized must be ground — never generalize a variable \
bound by a quantifier already in the sentence.
  ee  needs BOTH ∃ν.φ and the universally quantified implication ∀ν.(φ ⇒ ψ), \
and ν must not occur free in ψ. There is no version with an existential in the \
antecedent.
  ui  generalizes a placeholder, and the placeholder must be arbitrary: never \
generalize a name that occurs in a premise, or in an assumption that is still \
open at that line.
  dc  applies only when the exercise fixes a finite list of object constants, \
and then every instance must be cited.

THE EXISTENTIAL PATTERN. The chapter's way of using an existential premise is: \
assume its scope for a fresh placeholder, derive the target inside that \
subproof, close it with Implication Introduction, generalize the placeholder \
with Universal Introduction, then discharge with Existential Elimination \
against the original existential. Most exercises with an ∃ premise use it.

THE MISTAKE THAT SPOILS MOST PROOFS: citing into a closed subproof. A subproof \
ends as soon as a later line has a smaller depth, and from then on every line \
inside it is unreachable; only the implication that ii discharged it into \
survives. If you need a line from a closed subproof, reiterate it while the \
subproof is still open, or open a new one.

NEGATION. Without ex falso, a contradiction becomes a conclusion through \
Negation Introduction: to prove ¬φ, build φ ⇒ ψ and φ ⇒ ¬ψ as two SEPARATE \
subproofs and apply ni; to prove φ, do the same with ¬φ and then ne.

PROOF FORMAT. "proof" is a list of lines numbered from 1 in the order given. \
Each line has "formula", "rule", "depth", "refs" (1-based line numbers, empty \
when unused) and "subref" ([assumption line, consequent line], for ii only, \
null otherwise). "depth" starts at 0, only ever increases by one at a time, and \
a line deeper than the previous line must have rule "assume". The last line \
must be the goal at depth 0. Every premise appears as its own "premise" line, \
in the order listed. A line may cite an earlier line only at the same depth or \
in an enclosing subproof that is still open.

EXERCISE STYLE. "prompt" reads exactly like the chapter's own exercises: \
"Given <premises>, use the Fitch System to prove <goal>." — or, when the \
exercise fixes the domain, "Consider a language with just two object constants \
- a and b. Given ..., use the Fitch System to prove ...". With no premises, \
"Use the Fitch System to prove <goal>.". List those fixed constants in \
"constants", and leave it empty otherwise.

Every exercise must be a genuine logical entailment (or valid outright when \
there are no premises), and the proof must be correct line by line under the \
restrictions above. Before writing a proof, satisfy yourself that no \
interpretation makes the premises true and the goal false; if one does, discard \
the exercise and write a different one. Do not repeat or lightly rename the \
chapter's own exercises. Vary the shape of the problems across a set: mix \
universal and existential premises, one- and two-place relations, nested \
quantifiers, negated quantifiers, and the occasional fixed finite domain for \
Domain Closure.""".format(
    rules="\n".join(f"  {rid:8} {desc}"
                    for rid, desc in RULE_NOTES.items()))

STEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["formula", "rule", "depth", "refs", "subref"],
    "properties": {
        "formula": {"type": "string"},
        "rule": {"type": "string", "enum": sorted(RULES)},
        "depth": {"type": "integer"},
        "refs": {"type": "array", "items": {"type": "integer"},
                 "description": "1-based line numbers; empty when unused."},
        "subref": {"type": ["array", "null"], "items": {"type": "integer"},
                   "description": "[assumption line, consequent line] for ii."},
    },
}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["prompt", "premises", "goal", "constants", "hint",
                             "rules_used", "proof"],
                "properties": {
                    "prompt": {"type": "string"},
                    "premises": {"type": "array", "items": {"type": "string"}},
                    "goal": {"type": "string"},
                    "constants": {"type": "array", "items": {"type": "string"},
                                  "description": "Object constants the exercise "
                                                 "restricts the language to; "
                                                 "empty if it does not."},
                    "hint": {"type": "string"},
                    "rules_used": {"type": "array",
                                   "items": {"type": "string",
                                             "enum": sorted(RULES)}},
                    "proof": {"type": "array", "items": STEP_SCHEMA},
                },
            },
        }
    },
}


# --- talking to the API -----------------------------------------------------

class GeneratorError(RuntimeError):
    """The API call failed, or came back as something unusable."""


# 429 and 5xx are worth waiting out; anything else is our mistake, not theirs.
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRIES = 4


def _call(api_key, model, vector_store_id, prompt):
    payload = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": prompt,
        "tools": [{"type": "file_search",
                   "vector_store_ids": [vector_store_id]}],
        "text": {"format": {"type": "json_schema", "name": "ch10_exercises",
                            "strict": True, "schema": SCHEMA}},
    }
    for attempt in range(RETRIES):
        try:
            response = requests.post(
                API_URL, headers={"Authorization": f"Bearer {api_key}",
                                  "Content-Type": "application/json"},
                json=payload, timeout=600)
        except requests.RequestException as exc:
            if attempt == RETRIES - 1:
                raise GeneratorError(
                    f"Could not reach the OpenAI API: {exc}") from exc
            time.sleep(2 ** attempt * 5)
            continue
        if response.status_code in RETRY_STATUS and attempt < RETRIES - 1:
            time.sleep(2 ** attempt * 5)
            continue
        break
    if response.status_code >= 400:
        raise GeneratorError(
            f"OpenAI API returned {response.status_code}: "
            f"{response.text[:500]}")

    data = response.json()
    text = _output_text(data)
    if not text:
        raise GeneratorError(f"No text in the response: {json.dumps(data)[:500]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeneratorError(f"Response was not JSON: {text[:500]}") from exc


def _output_text(data):
    """Pull the assistant's text out of a Responses API payload."""
    if data.get("output_text"):
        return data["output_text"]
    chunks = []
    for item in data.get("output", []):
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text":
                chunks.append(part.get("text", ""))
    return "".join(chunks)


# --- checking ---------------------------------------------------------------

def problems(question):
    """Every complaint ch10_checker has about one question."""
    try:
        return cc.check_proof(question.get("premises") or [],
                              question.get("goal") or "",
                              question.get("proof") or [],
                              question.get("constants") or [])
    except (cc.FormulaError, KeyError, TypeError, IndexError, ValueError) as exc:
        return [f"the question is malformed: {exc}"]


def shape(premises, goal, loose=False):
    """A canonical form of an argument, blind to the names it happens to use.

    Variables, relation constants and object constants are renumbered in order
    of first appearance, so "∃y.∀x.p(x,y) ⊢ ∀x.∃y.p(x,y)" and
    "∃x.∀y.r(x,y) ⊢ ∀y.∃x.r(x,y)" come out the same — which is what makes a
    renamed copy of a chapter exercise recognizable. With loose=True the
    arguments of each relation are also sorted, which additionally catches a
    copy made by transposing the arguments of a two-place relation.
    """
    names = {}

    def tag(kind, name):
        key = (kind, name)
        if key not in names:
            names[key] = f"{kind}{len(names)}"
        return names[key]

    def term(node, bound):
        kind = "v" if node[1] in bound else "c"
        return (tag(kind, node[1]),
                tuple(term(a, bound) for a in node[2]))

    def walk(node, bound):
        head = node[0]
        if head == "rel":
            args = tuple(term(a, bound) for a in node[2])
            return ("rel", tag("R", node[1]),
                    tuple(sorted(args)) if loose else args)
        if head in ("all", "exists"):
            return (head, tag("v", node[1]), walk(node[2], bound | {node[1]}))
        if head == "not":
            return ("not", walk(node[1], bound))
        if head in ("and", "or"):
            return (head, tuple(walk(a, bound) for a in node[1]))
        return (head, walk(node[1], bound), walk(node[2], bound))

    try:
        parsed = [cc.parse(p) for p in premises] + [cc.parse(goal)]
    except cc.FormulaError:
        return None
    return tuple(walk(node, frozenset()) for node in parsed)


CHAPTER_SHAPES = {shape(p, g) for p, g in CHAPTER_ARGUMENTS} - {None}
# Looser, to catch a chapter exercise copied with its arguments transposed.
CHAPTER_SHAPES_LOOSE = {shape(p, g, loose=True)
                        for p, g in CHAPTER_ARGUMENTS} - {None}


# --- the generation loop ----------------------------------------------------

def _ask_prompt(count, difficulty, avoid):
    want = f"Write {count} new exercise{'s' if count != 1 else ''}"
    if difficulty:
        want += (f", aimed at {difficulty} difficulty — a proof of "
                 f"{cc.TARGET_LINES[difficulty]}")
    lines = [
        want + ", each with a complete worked proof.",
        "",
        "The chapter's own exercises, for style — do not reproduce them:",
        *(f"  - {ex}" for ex in CHAPTER_EXERCISES),
    ]
    if avoid:
        lines += ["", "Also avoid these, already generated:",
                  *(f"  - {ex}" for ex in avoid)]
    lines += ["", "The JSON shape, shown with a proof from the chapter:",
              json.dumps(EXAMPLE, ensure_ascii=False, indent=2)]
    return "\n".join(lines)


def _repair_prompt(question, complaints):
    return "\n".join([
        "This exercise did not pass the structural check. Fix the proof, or "
        "replace the exercise with a correct one of the same shape. Return it "
        "in the same JSON format, as a single question.",
        "",
        json.dumps(question, ensure_ascii=False, indent=2),
        "",
        "Complaints:",
        *(f"  - {c}" for c in complaints),
    ])


def generate(count=1, difficulty=None, api_key=None, model=MODEL,
             vector_store_id=None, verbose=False, existing=()):
    """Return a list of questions that pass the structural check."""
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise GeneratorError("OPENAI_API_KEY is not set.")
    vector_store_id = vector_store_id or VECTOR_STORE_ID
    if not vector_store_id:
        raise GeneratorError(
            "No vector store. Run openai_vector_store.py on the chapter and "
            "set CH10_VECTOR_STORE_ID to the id it prints.")

    def log(msg):
        if verbose:
            print(msg, file=sys.stderr)

    kept, avoid, seen = [], [], set()
    for question in existing:                 # do not repeat what is on file
        seen.add(shape(question.get("premises") or [],
                       question.get("goal") or ""))
        avoid.append(question.get("prompt", ""))
    # Ask for a few extra, since some candidates are dropped.
    batch = _call(api_key, model, vector_store_id,
                  _ask_prompt(count + 2, difficulty, avoid))
    for question in batch.get("questions", []):
        if len(kept) >= count:
            break
        complaints = problems(question)
        for _ in range(REPAIR_ATTEMPTS if complaints else 0):
            log(f"repairing {question.get('prompt')!r}: {complaints[0]}")
            fixed = _call(api_key, model, vector_store_id,
                          _repair_prompt(question, complaints))
            candidates = fixed.get("questions") or []
            if not candidates:
                break
            question = candidates[0]
            complaints = problems(question)
            if not complaints:
                break
        if complaints:
            log(f"dropped {question.get('prompt')!r}: {complaints[0]}")
            continue
        premises = question.get("premises") or []
        goal = question.get("goal") or ""
        signature = shape(premises, goal)
        if (signature in seen or signature in CHAPTER_SHAPES
                or shape(premises, goal, loose=True) in CHAPTER_SHAPES_LOOSE):
            log(f"dropped {question.get('prompt')!r}: it is a renaming of an "
                f"exercise already in the set")
            continue
        seen.add(signature)
        question["difficulty"] = cc.difficulty(question["proof"])
        question["chapter"] = 10
        kept.append(question)
        avoid.append(question["prompt"])
    return kept


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--count", type=int, default=1)
    ap.add_argument("--difficulty", choices=cc.DIFFICULTIES)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--store", default=None, help="vector store id")
    ap.add_argument("-o", "--out", help="write the questions to this JSON file")
    ap.add_argument("-a", "--append", action="store_true",
                    help="add to --out instead of replacing it")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    existing = []
    if args.append and args.out and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as fh:
            existing = json.load(fh)

    try:
        questions = generate(args.count, args.difficulty, model=args.model,
                             vector_store_id=args.store,
                             verbose=not args.quiet, existing=existing)
    except GeneratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(existing + questions, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {len(questions)} new question(s) to {args.out} "
              f"({len(existing) + len(questions)} in total)")
    else:
        print(text)
    return 0 if questions else 1


if __name__ == "__main__":
    sys.exit(main())
