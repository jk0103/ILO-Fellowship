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

More candidates are asked for than are wanted, and a batch that comes up short
is asked again. Whatever survives beyond the count is returned too rather than
thrown away: verifying it cost nothing, and the caller can bank it.

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
# gpt-4.1 could not hold a twenty-line relational proof together —
# a hard run would spend a dozen repair calls and keep nothing.
MODEL = os.environ.get("FITCH_MODEL", "gpt-6-astra")

# Vector store holding "Introduction to Logic - Chapter 10.html".
VECTOR_STORE_ID = os.environ.get(
    "CH10_VECTOR_STORE_ID", "vs_6aa3f2d8cd80819191a883102f447895"
)

REPAIR_ATTEMPTS = 2

# Extra repair rounds for the longer bands. A twenty-line proof has twenty
# chances to slip, so nearly every hard candidate needs repairing at least
# once; and regenerating one from scratch costs far more than mending it.
EXTRA_REPAIRS = {"medium": 1, "hard": 2}

# What actually makes a Chapter 10 proof long. Asking for a line count alone
# gets a short proof with extra premises bolted on, because a premise is a free
# line: it lengthens the proof without making the exercise any harder. Length
# in this system comes from subproofs, so that is what the recipe describes.
# The chapter's own exercises bear this out — almost every one of the sixteen
# has a single premise, and the long ones are long because of what they prove.
LENGTH_RECIPE = {
    "easy": "One premise and two or three rule applications, the way Exercises "
            "10.1 to 10.9 go.",
    "medium": "Proving an implication costs a subproof — assume the "
              "antecedent, reach the consequent, discharge it with Implication "
              "Introduction — and proving a universally quantified implication "
              "costs that subproof inside a Universal Introduction over an "
              "arbitrary name. Existential Elimination takes a universally "
              "quantified implication as its second input, which usually has to "
              "be built the same way. Or Elimination costs a subproof per "
              "disjunct.",
    "hard": "The expensive results are the negative ones — the pattern of "
            "Exercises 10.11 to 10.14, where ¬∀ and ¬∃ trade places. There is "
            "no ex falso here, so a negation is only ever reached by Negation "
            "Introduction on two implications that share an antecedent, and "
            "each of those implications is a subproof of its own. Nest that "
            "inside a Universal Introduction, or inside the implication an "
            "Existential Elimination needs, and the proof is long because the "
            "result is hard, not because it has been padded.",
}

# Said whatever band is asked for: the two ways of reaching a line count that
# are not worth reaching.
NO_PADDING = (
    "An exercise may have no premises at all — proving a law of quantifier "
    "logic outright, such as ⊢ ∀x.(p(x) ⇒ p(x)) or ⊢ ∀x.p(x) ⇒ ∃x.p(x) — and "
    "those are entirely subproof work, so they are often the longest kind. "
    "Never add a premise to reach a line count: every premise must be cited "
    "somewhere in the proof, and an exercise that needs a premise it never uses "
    "is a worse exercise, not a longer one."
)

# Candidates asked for beyond what is wanted. Zero: the batch is exactly what
# was asked for.
#
# This used to be 2, from when a batch of three was the only way to end up with
# one usable exercise. A model that verifies first try makes that a bad trade —
# the extras are most of the wait, because the whole batch is written in one
# completion and it is the output that takes the time. Over-asking did not save
# work either, only moved it: three written at once and two banked is the same
# total as three written one at a time, with the entire cost paid up front by
# whoever pressed the button first. Raise it again if the model starts missing.
ASK_EXTRA = 0

# Batches asked for before giving up. A batch that comes up short is asked
# again for the shortfall only; the model samples afresh each time, so a second
# ask is worth making rather than failing the request.
ATTEMPTS = 3

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


def padding(question):
    """Complaints about an exercise that is longer than it is hard.

    Difficulty is measured by proof length, and a premise costs a line without
    costing any work, so bolting premises on is the cheapest way to answer a
    request for a long proof. A premise no line ever cites is the tell: the
    argument is valid without it, so it is weight rather than difficulty. The
    checker has nothing to say about this — such a proof is perfectly sound —
    which is why it is asked separately.
    """
    proof = question.get("proof") or []
    cited = set()
    for step in proof:
        cited.update(step.get("refs") or [])
        first, last = (step.get("subref") or [None, None])[:2]
        if isinstance(first, int) and isinstance(last, int):
            cited.update(range(first, last + 1))

    out = []
    for i, step in enumerate(proof, 1):
        if step.get("rule") == "premise" and i not in cited:
            out.append(f"premise {i} ({step.get('formula')}) is never used, so "
                       f"it lengthens the proof without being part of it")
    return out


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

def _starter_bank():
    """The exercises that ship next to this module, if they are still there.

    `main()` writes this file and `seed_questions.py` loads it into Firestore.
    It is read here only to have a worked example of every band on hand before
    anything has been generated, so a missing or unreadable file is no more
    than a missed improvement.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "ch10_questions.json")
    try:
        with open(path, encoding="utf-8") as fh:
            bank = json.load(fh)
    except (OSError, ValueError):
        return []
    return bank if isinstance(bank, list) else []


STARTER = _starter_bank()


def _example_for(difficulty, existing):
    """A worked exercise to show as the JSON shape, in the band being asked for.

    The built-in example is a seven-line one, and the chapter's own exercises
    are shorter still, so a prompt for a hard exercise otherwise shows nothing
    but easy ones and gets an easy one back. When something in the band asked
    for is on hand — already generated, or in the starter bank — that is shown
    instead: it is verified, it is the right length, and it demonstrates what
    makes a proof that long here. The longest in band shows the most.
    """
    if not difficulty:
        return EXAMPLE

    best = None
    for question in list(existing) + STARTER:
        proof = question.get("proof") or []
        if not proof or cc.difficulty(proof) != difficulty:
            continue
        if best is not None and len(proof) <= len(best["proof"]):
            continue
        if problems(question):            # never show the model a broken proof
            continue
        best = question
    if best is None:
        return EXAMPLE

    proof = best["proof"]
    return {
        "prompt": best.get("prompt") or best.get("statement") or "",
        "premises": list(best.get("premises") or []),
        "goal": best.get("goal") or "",
        "constants": list(best.get("constants") or []),
        "hint": best.get("hint") or "",
        "rules_used": sorted({step["rule"] for step in proof}),
        "proof": proof,
    }


def _ask_prompt(count, difficulty, avoid, note=None, example=EXAMPLE):
    # A batch of one is now the usual case, so the sentence has to read for it.
    lines = [f"Write {count} new exercises, each with a complete worked proof."
             if count != 1 else
             "Write 1 new exercise, with a complete worked proof."]
    if difficulty:
        lines += [
            "",
            f"LENGTH. This is a {difficulty} exercise, so each proof must come "
            f"to {cc.TARGET_LINES[difficulty]}. That is the length of the whole "
            f'"proof" array — the premise lines and every assumption line count '
            f"towards it, not just the inferred ones. Choose an argument that "
            f"genuinely needs a proof that long; never pad a short one with "
            f"reiterations or detours.",
            "",
            f"WHAT MAKES A PROOF THAT LONG. Length here comes from subproofs, "
            f"not from premises. {LENGTH_RECIPE[difficulty]}",
            "",
            NO_PADDING,
        ]
    if note:
        lines += ["", note]
    lines += ["",
              "The chapter's own exercises, for style — do not reproduce them. "
              "Most are short; the length asked for above is what governs, not "
              "these:",
              *(f"  - {ex}" for ex in CHAPTER_EXERCISES)]
    if avoid:
        lines += ["", "Also avoid these, already generated:",
                  *(f"  - {ex}" for ex in avoid)]
    shown = len(example["proof"])
    lines += ["",
              f"The JSON shape, shown with a worked {cc.difficulty(example['proof'])}"
              f" exercise of {shown} lines:",
              json.dumps(example, ensure_ascii=False, indent=2)]
    return "\n".join(lines)


def _length_note(difficulty, off_band):
    """A nudge for the next batch, when the last one missed the band asked for.

    The difficulty of an exercise is the length of its verified proof, so a
    batch that came out in the wrong band is a batch of arguments that were too
    much or too little work. Saying so — with the lengths it actually returned
    — is more use to the model than asking again in the same words.
    """
    if not (difficulty and off_band):
        return None
    lengths = sorted(len(q["proof"]) for q in off_band)
    wanted = cc.DIFFICULTIES.index(difficulty)
    short = sum(1 for q in off_band
                if cc.DIFFICULTIES.index(q["difficulty"]) < wanted)
    if short * 2 >= len(off_band):
        miss, fix = "too short", (
            "Reach for arguments that genuinely need more work: more premises, "
            "a nested subproof, or a chain of several quantifier steps.")
    else:
        miss, fix = "too long", (
            "Reach for simpler arguments, settled in fewer steps.")
    return (f"The last attempt came back at {', '.join(str(n) for n in lengths)}"
            f" lines — {miss} for {difficulty}, which needs "
            f"{cc.TARGET_LINES[difficulty]}. {fix}")


def _repair_prompt(question, complaints):
    return "\n".join([
        "This exercise is fine but its proof does not check out. Return exactly "
        "one question: the SAME premises and the SAME goal, with the proof "
        "corrected. Do not substitute a different argument, and do not retreat "
        "to an easier one — a long proof with a broken line is worth more than "
        "a short proof of something else. Return it in the same JSON format.",
        "",
        json.dumps(question, ensure_ascii=False, indent=2),
        "",
        "Complaints:",
        *(f"  - {c}" for c in complaints),
    ])


def _same_argument(one, other):
    """Whether two candidates state the same exercise.

    Compared through the checker's own parser, so a repair that reprints
    "p ∧ q" as "p&q" still counts as the same argument while one that quietly
    swaps in a different — usually easier — exercise does not. A candidate
    whose formulas will not parse is not the same as anything; it is broken,
    and the checker drops it a moment later anyway.
    """
    def key(question):
        return (sorted(cc.show(cc.parse(p)) for p in question.get("premises") or []),
                cc.show(cc.parse(question.get("goal") or "")))
    try:
        return key(one) == key(other)
    except (cc.FormulaError, KeyError, TypeError, IndexError, ValueError):
        return False


def generate(count=1, difficulty=None, api_key=None, model=MODEL,
             vector_store_id=None, verbose=False, existing=(),
             attempts=ATTEMPTS):
    """Return the questions that passed the structural check.

    The first `count` of them are what was asked for. Anything after that is
    surplus — a batch that over-delivers, or a sound exercise that landed
    outside the band asked for. Verifying it cost nothing, so it is handed back
    rather than thrown away and `/api/questions/generate` banks it for the next
    request.

    `difficulty`, if given, is the band the caller asked for, and it is
    enforced: difficulty is the length of the verified proof, so a question
    that comes out in another band does not count towards `count` and the batch
    is asked again, told how far off the last one was. Such a question is still
    sound, so it is returned behind the in-band ones rather than dropped — a
    caller that ends up short gets a verified exercise instead of nothing, and
    the rest are banked under the band they really landed in.

    A batch that comes up short is asked again, up to `attempts` times, for the
    shortfall only.

    `existing` is the exercises already on file — either this module's own
    questions, or the rows `/generate` reads back from Firestore and its
    waiting area. Their shapes are compared against each candidate and their
    prose goes into the prompt's do-not-repeat list, which matters here because
    Chapter 10 has a small stock of arguments and will otherwise write the same
    one again.
    """
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

    kept, off_band, avoid, seen = [], [], [], set()
    for question in existing:                 # do not repeat what is on file
        seen.add(shape(question.get("premises") or [],
                       question.get("goal") or ""))
        # Straight from this module the prose is "prompt"; read back out of
        # Firestore it is "statement". Either names the same exercise.
        prose = question.get("prompt") or question.get("statement") or ""
        if prose:
            avoid.append(prose)

    repairs = REPAIR_ATTEMPTS + EXTRA_REPAIRS.get(difficulty, 0)
    # Show the model something of the right length, if anything on file is.
    example = _example_for(difficulty, existing)

    for attempt in range(max(1, int(attempts))):
        if len(kept) >= count:
            break
        # Only what is still missing: a batch that came up short is asked
        # again rather than padded out in advance.
        batch = _call(api_key, model, vector_store_id,
                      _ask_prompt(count - len(kept) + ASK_EXTRA, difficulty,
                                  avoid, _length_note(difficulty, off_band),
                                  example))
        candidates = batch.get("questions") or []
        if not candidates:
            log(f"batch {attempt + 1}: the model returned no questions")
            continue

        for question in candidates:
            complaints = problems(question)
            # A repair is another API call, so it is only worth paying for
            # while we are still short of the count. Spares are taken as they
            # come or not at all.
            if complaints and len(kept) < count:
                for _ in range(repairs):
                    log(f"repairing {question.get('prompt')!r}: {complaints[0]}")
                    fixed = _call(api_key, model, vector_store_id,
                                  _repair_prompt(question, complaints))
                    repaired = fixed.get("questions") or []
                    if not repaired:
                        break
                    # A repair must not quietly swap in a different exercise.
                    # Long proofs are the ones that need repairing, and the
                    # easiest way to satisfy the checker is to answer an easier
                    # question instead — which is how a request for a hard
                    # exercise comes back easy.
                    if not _same_argument(repaired[0], question):
                        log(f"dropped a repair of {question.get('prompt')!r}: "
                            f"it changed the exercise")
                        break
                    question = repaired[0]
                    complaints = problems(question)
                    if not complaints:
                        break
            if complaints:
                log(f"dropped {question.get('prompt')!r}: {complaints[0]}")
                continue

            weight = padding(question)
            if weight:
                log(f"dropped {question.get('prompt')!r}: {weight[0]}")
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
            # Difficulty is measured, never claimed: it is the length of the
            # proof that just passed the checker.
            question["difficulty"] = cc.difficulty(question["proof"])
            question["chapter"] = 10
            prose = question.get("prompt") or ""
            if prose:
                avoid.append(prose)

            if difficulty and question["difficulty"] != difficulty:
                # Sound, just not the band that was asked for. It does not
                # count towards `count`, so the loop asks again — but it is
                # verified work, so it is handed back at the end rather than
                # dropped, behind everything in band.
                log(f"off band: {prose!r} came out "
                    f"{question['difficulty']} ({len(question['proof'])} lines), "
                    f"not {difficulty}")
                off_band.append(question)
                continue
            kept.append(question)

        log(f"batch {attempt + 1}: {len(kept)} of {count} in band, "
            f"{len(off_band)} off band")

    # In band first, so a caller taking the first `count` gets what it asked
    # for. Better to hand back a verified question in the wrong band than
    # nothing, and the spares are banked under the band they really landed in.
    return kept + off_band


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--count", type=int, default=1)
    ap.add_argument("--difficulty", choices=cc.DIFFICULTIES)
    ap.add_argument("--attempts", type=int, default=ATTEMPTS,
                    help="batches to ask for before giving up")
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
                             vector_store_id=args.store, attempts=args.attempts,
                             verbose=not args.quiet, existing=existing)
    except GeneratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # generate() may hand back spares; the CLI was asked for -n and the server
    # is what banks the rest.
    if len(questions) > args.count:
        if not args.quiet:
            print(f"note: {len(questions) - args.count} spare question(s) "
                  f"verified and discarded", file=sys.stderr)
        questions = questions[:args.count]

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
