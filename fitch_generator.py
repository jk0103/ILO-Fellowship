"""Generate Fitch exercises, with worked proofs, using the GPT API.

The model is grounded on "Introduction to Logic - Chapter 5" through a
file_search vector store, so the problems it writes stay inside the rule set the
chapter teaches and read like the Exercise 5.x list at the end of it.

Nothing the model returns is trusted. Every candidate is checked locally by
fitch_checker: the argument must be valid, and the proof must pass the same
checker the browser editor runs. A proof that fails is handed back to the model
with the checker's complaints and one repair attempt. Only what survives is
returned, and its difficulty comes from the length of the verified proof, not
from the model's opinion.

CLI:
    export OPENAI_API_KEY=...
    python fitch_generator.py -n 5 --difficulty medium
"""

import argparse
import json
import os
import sys

import requests

import fitch_checker as fc

API_URL = "https://api.openai.com/v1/responses"
MODEL = os.environ.get("FITCH_MODEL", "gpt-4.1")

# Vector store holding "Introduction to Logic - Chapter 5.html".
VECTOR_STORE_ID = os.environ.get(
    "FITCH_VECTOR_STORE_ID", "vs_6a956ea0021c819190453d08895c1dfc"
)

REPAIR_ATTEMPTS = 2   # how many times one bad proof is sent back for repair


class GeneratorError(RuntimeError):
    """The API call failed, or came back as something unusable."""


# The chapter's own exercises: the style reference, and the do-not-repeat list.
CHAPTER_EXERCISES = [
    "Given p and q and (p ∧ q ⇒ r), use the Fitch system to prove r.",
    "Given (p ∧ q), use the Fitch system to prove (q ∨ r).",
    "Given p ⇒ q and q ⇔ r, use the Fitch system to prove p ⇒ r.",
    "Given p ⇒ q and m ⇒ p ∨ q, use the Fitch system to prove m ⇒ q.",
    "Given p ⇒ (q ⇒ r), use the Fitch system to prove (p ⇒ q) ⇒ (p ⇒ r).",
    "Use the Fitch system to prove p ⇒ (q ⇒ p).",
    "Use the Fitch system to prove (p ⇒ (q ⇒ r)) ⇒ ((p ⇒ q) ⇒ (p ⇒ r)).",
    "Use the Fitch system to prove (¬p ⇒ q) ⇒ ((¬p ⇒ ¬q) ⇒ p).",
    "Given p, use the Fitch system to prove ¬¬p.",
    "Given p ⇒ q, use the Fitch system to prove ¬q ⇒ ¬p.",
    "Given p ⇒ q, use the Fitch system to prove ¬p ∨ q.",
    "Use the Fitch system to prove ((p ⇒ q) ⇒ p) ⇒ p.",
    "Given ¬(p ∨ q), use the Fitch system to prove (¬p ∧ ¬q).",
    "Use the Fitch system to prove the tautology (p ∨ ¬p).",
]

# A verified proof, shown to the model so the JSON shape is unambiguous.
EXAMPLE = {
    "premises": [],
    "goal": "((p ⇒ q) ∧ (q ⇒ r)) ⇒ (p ⇒ r)",
    "hint": "Two nested conditional proofs; take the premise apart with And Elimination.",
    "proof": [
        {"formula": "(p ⇒ q) ∧ (q ⇒ r)", "rule": "assume", "depth": 1},
        {"formula": "p", "rule": "assume", "depth": 2},
        {"formula": "p ⇒ q", "rule": "ae", "depth": 2, "refs": [1]},
        {"formula": "q", "rule": "ie", "depth": 2, "refs": [3, 2]},
        {"formula": "q ⇒ r", "rule": "ae", "depth": 2, "refs": [1]},
        {"formula": "r", "rule": "ie", "depth": 2, "refs": [5, 4]},
        {"formula": "p ⇒ r", "rule": "ii", "depth": 1, "subref": [2, 6]},
        {"formula": "((p ⇒ q) ∧ (q ⇒ r)) ⇒ (p ⇒ r)", "rule": "ii", "depth": 0,
         "subref": [1, 7]},
    ],
}

SYSTEM_PROMPT = """\
You write propositional logic exercises, with full worked proofs, for the Fitch \
system taught in the chapter you have been given. Consult that chapter with \
file_search before answering.

CONNECTIVES: only ¬ ∧ ∨ ⇒ ⇔, written with those Unicode symbols. \
ATOMS: only the single letters p, q, r, s, m. No quantifiers or predicates.

RULES. These eleven are the entire system. There is NO False Introduction, NO \
False Elimination, and NO ex falso — a contradiction never licenses an \
arbitrary conclusion. Each line of a proof carries a rule id:

  premise  a premise, at depth 0
  assume   an assumption; it opens a subproof and is the first line of it
  reit     "refs":[i]        repeat line i verbatim
  ai       "refs":[i,j,...]  from the conjuncts, in order, infer the conjunction
  ae       "refs":[i]        from a conjunction infer one conjunct
  oi       "refs":[i]        from φ infer any disjunction with φ as a disjunct
  oe       "refs":[d,c1,c2]  from a disjunction and one implication per disjunct,
                             all sharing the same consequent, infer it
  ni       "refs":[i,j]      from φ ⇒ ψ and φ ⇒ ¬ψ infer ¬φ
  ne       "refs":[i]        from ¬¬φ infer φ
  ii       "subref":[a,b]    discharge the subproof opened at a, whose line b is
                             the consequent, into (assumption ⇒ line b)
  ie       "refs":[i,j]      from φ ⇒ ψ and φ infer ψ
  bi       "refs":[i,j]      from φ ⇒ ψ and ψ ⇒ φ infer φ ⇔ ψ
  be       "refs":[i]        from φ ⇔ ψ infer either direction

PROOF FORMAT. "proof" is a list of lines, numbered from 1 in the order given. \
Each line has "formula", "rule", "depth", and either "refs" (1-based line \
numbers) or, for ii only, "subref": [assumption line, consequent line]. \
"depth" is the subproof nesting level; it starts at 0, only ever increases by \
one at a time, and a line whose depth is greater than the previous line's must \
have rule "assume". The last line must be at depth 0 and must be the goal. \
Every premise must appear as its own "premise" line. A line may cite an earlier \
line only if that line is at the same depth or in an enclosing subproof that is \
still open — never inside a subproof that has already closed.

THE CENTRAL PATTERN. Without ex falso, a contradiction is turned into a \
conclusion through Negation Introduction. To prove ¬φ: build φ ⇒ ψ and φ ⇒ ¬ψ \
as two separate subproofs, then apply ni. To prove φ: do the same with ¬φ to \
get ¬¬φ, then apply ne. This is how the chapter proves everything that needs \
reductio, and most non-trivial proofs will use it.

THE MISTAKE THAT SPOILS MOST PROOFS: citing into a closed subproof. A subproof \
ends as soon as a later line has a smaller depth, and from that moment every \
line inside it is permanently unreachable. The only thing that survives is the \
implication the ii line discharged it into. So the two subproofs the ni pattern \
needs are two SEPARATE subproofs, each of which opens by assuming φ again:

  1. p ⇒ q                     premise
  2. │ ¬q                      assume            <- opens subproof A
  3. │ │ p                     assume            <- opens subproof B
  4. │ │ ¬q                    reit: 2           (line 2 is still open, so this is fine)
  5. │ p ⇒ ¬q                  ii: subref [3,4]  <- B closes; lines 3-4 are now dead
  6. │ ¬p                      ni: [1,5]         (cites 5, not anything inside B)
  7. ¬q ⇒ ¬p                   ii: subref [2,6]

Note line 6 cites the discharged implication on line 5, never line 3 or 4. If \
you find yourself wanting a line from a subproof that has closed, open a new \
subproof and assume it again, or reiterate it while the subproof is still open.

Before writing any proof, check the argument on a truth table. If any \
assignment makes all the premises true and the goal false, discard the exercise \
and write a different one — no proof of it exists.

Every exercise must be a genuine logical consequence of its premises (or a \
tautology when there are none), and the proof you give must be complete and \
correct line by line. Do not repeat or lightly rename the chapter's own \
exercises. Vary the shape of the problems across a set."""

STEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["formula", "rule", "depth", "refs", "subref"],
    "properties": {
        "formula": {"type": "string"},
        "rule": {"type": "string", "enum": sorted(fc.RULES)},
        "depth": {"type": "integer"},
        "refs": {"type": "array", "items": {"type": "integer"},
                 "description": "1-based line numbers; empty when unused."},
        "subref": {"type": ["array", "null"],
                   "items": {"type": "integer"},
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
                "required": ["premises", "goal", "hint", "proof"],
                "properties": {
                    "premises": {"type": "array", "items": {"type": "string"}},
                    "goal": {"type": "string"},
                    "hint": {"type": "string"},
                    "proof": {"type": "array", "items": STEP_SCHEMA},
                },
            },
        }
    },
}


# --- talking to the API -----------------------------------------------------

def _call(api_key, model, vector_store_id, prompt):
    payload = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": prompt,
        "tools": [{"type": "file_search", "vector_store_ids": [vector_store_id]}],
        "text": {"format": {"type": "json_schema", "name": "fitch_exercises",
                            "strict": True, "schema": SCHEMA}},
    }
    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=payload, timeout=300,
        )
    except requests.RequestException as exc:
        raise GeneratorError(f"Could not reach the OpenAI API: {exc}") from exc

    if response.status_code != 200:
        raise GeneratorError(
            f"OpenAI API returned {response.status_code}: {response.text[:500]}")

    body = response.json()
    text = "".join(
        part.get("text", "")
        for item in body.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    if not text:
        raise GeneratorError("The API returned no text.")
    try:
        return json.loads(text)["questions"]
    except (ValueError, KeyError) as exc:
        raise GeneratorError(f"Could not read the API response: {exc}") from exc


def _clean(question):
    """Normalise one candidate, or return None if it is not even shaped right."""
    if not isinstance(question, dict) or not question.get("goal"):
        return None
    steps = []
    for step in question.get("proof") or []:
        out = {"formula": step.get("formula", ""),
               "rule": step.get("rule", ""),
               "depth": int(step.get("depth") or 0)}
        if step.get("refs"):
            out["refs"] = [int(r) for r in step["refs"]]
        if step.get("subref"):
            out["subref"] = [int(n) for n in step["subref"]]
        steps.append(out)
    return {
        "premises": [p for p in (question.get("premises") or []) if p.strip()],
        "goal": question["goal"].strip(),
        "hint": (question.get("hint") or "").strip(),
        "proof": steps,
    }


def _faults(question):
    """Everything wrong with a candidate, as messages fit to send back."""
    problems = []
    try:
        premises = [fc.parse(p) for p in question["premises"]]
        goal = fc.parse(question["goal"])
    except fc.FormulaError as exc:
        return [f"The problem statement does not parse: {exc}"]

    world = fc.countermodel(premises, goal)
    if world is not None:
        shown = ", ".join(f"{k}={'true' if v else 'false'}"
                          for k, v in sorted(world.items()))
        # No proof can exist, so there is nothing to repair.
        return [f"The argument is invalid: it fails when {shown}."]

    statement = render_question(question)
    if any(statement.replace(" ", "") == e.replace(" ", "")
           for e in CHAPTER_EXERCISES):
        problems.append("This duplicates an exercise already in the chapter.")

    problems.extend(fc.check_proof(question["premises"], question["goal"],
                                   question["proof"]))
    return problems


def _repair_prompt(question, problems):
    return (
        "This exercise is fine but its proof does not check out. Return exactly "
        "one question: the same premises and goal, with the proof corrected.\n\n"
        f"Premises: {question['premises'] or '(none)'}\n"
        f"Goal: {question['goal']}\n\n"
        "The proof you gave:\n"
        + json.dumps(question["proof"], ensure_ascii=False, indent=1)
        + "\n\nThe checker reports:\n"
        + "\n".join(f"- {p}" for p in problems)
        + "\n\nRemember: there is no ex falso, so a contradiction only yields a "
          "conclusion through Negation Introduction on two implications that "
          "share an antecedent; and once a subproof has closed, nothing inside "
          "it can be cited again — only the implication it was discharged into. "
          "If you need an assumption a second time, open a second subproof and "
          "assume it again."
    )


def _ask_prompt(count, difficulty, avoid):
    prompt = [f"Write {count} new Fitch exercises, each with a complete proof."]
    if difficulty:
        prompt.append(
            f"Aim for {difficulty} difficulty: a proof of "
            f"{fc.TARGET_LINES[difficulty]}. Difficulty here is measured purely "
            f"by how many lines the proof takes."
        )
    prompt.append("Here is the exact shape expected, for one question:\n"
                  + json.dumps(EXAMPLE, ensure_ascii=False, indent=1))
    prompt.append("The chapter already ends with these. Do not repeat them:\n"
                  + "\n".join(f"- {e}" for e in CHAPTER_EXERCISES))
    if avoid:
        prompt.append("Already accepted for this set; produce different ones:\n"
                      + "\n".join(f"- {a}" for a in avoid))
    return "\n\n".join(prompt)


# --- the public entry point -------------------------------------------------

def render_question(question):
    """The exercise as prose, phrased the way the chapter phrases Exercise 5.x."""
    premises = question.get("premises") or []
    goal = fc.show_statement(fc.parse(question["goal"]))
    if premises:
        given = " and ".join(fc.show_statement(fc.parse(p)) for p in premises)
        return f"Given {given}, use the Fitch system to prove {goal}."
    return f"Use the Fitch system to prove the tautology {goal}."


def generate(count=1, difficulty=None, api_key=None, model=MODEL,
             vector_store_id=VECTOR_STORE_ID, attempts=3, on_reject=None):
    """Return up to `count` verified questions, each with a checked proof.

    `difficulty`, if given, is a target band; a question whose verified proof
    lands in a different band is kept anyway but labelled by its real length,
    and the shortfall is re-requested. Every returned question carries
    "difficulty", "line_count" and "statement".
    """
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise GeneratorError("OPENAI_API_KEY is not set.")
    if difficulty and difficulty not in fc.DIFFICULTIES:
        raise GeneratorError(f"Unknown difficulty {difficulty!r}.")

    kept, seen, off_band = [], set(), []

    def reject(question, problems):
        if on_reject:
            on_reject(question, problems)

    def accept(question):
        question["line_count"] = len(question["proof"])
        question["difficulty"] = fc.difficulty(question["proof"])
        question["statement"] = render_question(question)
        return question

    for attempt in range(attempts):
        if len(kept) >= count:
            break
        wanted = count - len(kept)
        avoid = [q["statement"] for q in kept] + [q["statement"] for q in off_band]
        raw = _call(api_key, model, vector_store_id,
                    _ask_prompt(wanted if attempt == 0 else wanted + 1,
                                difficulty, avoid))

        for candidate in raw:
            question = _clean(candidate)
            if question is None:
                continue

            problems = _faults(question)
            for _ in range(REPAIR_ATTEMPTS):
                if not problems or problems[0].startswith("The argument is invalid"):
                    break
                reject(question, problems)
                repaired = _call(api_key, model, vector_store_id,
                                 _repair_prompt(question, problems))
                fixed = _clean(repaired[0]) if repaired else None
                if not fixed:
                    break
                # A repair must not quietly change the problem.
                if (fixed["goal"] != question["goal"]
                        or fixed["premises"] != question["premises"]):
                    break
                fixed["hint"] = fixed["hint"] or question["hint"]
                question, problems = fixed, _faults(fixed)

            if problems:
                reject(question, problems)
                continue

            question = accept(question)
            if question["statement"] in seen:
                continue
            seen.add(question["statement"])

            if difficulty and question["difficulty"] != difficulty:
                off_band.append(question)   # correct, just not the band asked for
                continue
            kept.append(question)
            if len(kept) == count:
                return kept

    # Better to hand back a verified question in the wrong band than nothing.
    return (kept + off_band)[:count] if kept or off_band else []


# --- CLI --------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--count", type=int, default=5)
    parser.add_argument("-d", "--difficulty", choices=fc.DIFFICULTIES)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--vector-store", default=VECTOR_STORE_ID)
    parser.add_argument("--proofs", action="store_true", help="print the proofs")
    parser.add_argument("--json", metavar="PATH")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    def report(question, problems):
        if args.verbose:
            print(f"[retry] {question.get('goal')!r}: {problems[0]}",
                  file=sys.stderr)

    try:
        questions = generate(args.count, args.difficulty, model=args.model,
                             vector_store_id=args.vector_store,
                             attempts=args.attempts, on_reject=report)
    except GeneratorError as exc:
        parser.error(str(exc))

    for i, question in enumerate(questions, 1):
        print(f"Exercise 5.{i}: {question['statement']}"
              f"   [{question['difficulty']}, {question['line_count']} lines]")
        if args.proofs:
            print(fc.render_proof(question["proof"]))
            print()

    if len(questions) < args.count:
        print(f"warning: {len(questions)} of {args.count} survived verification",
              file=sys.stderr)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(questions, fh, ensure_ascii=False, indent=2)
    return 0 if questions else 1


if __name__ == "__main__":
    sys.exit(main())
