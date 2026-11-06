"""The level test a new account takes at sign-up.

A short test, dealt from its own bank, that decides where on the ladder
someone starts. Most of it is multiple choice about the material — which rule,
which sentence is equivalent, which premises entail what — answered in a
minute each. The last questions are short Fitch proofs, built in the same
editor as practice: a level ladder of proofs is only fairly placed by a proof.
They are kept to a handful of lines, since a hard practice proof runs to
twenty and would make the test an afternoon.

    Deal TEST_SIZE questions: multiple choice by MIX, then proofs by FITCH_MIX.
    Spread the multiple choice over as many topics as the bank allows.
    Never deal an inactive question.
    Score by difficulty (WEIGHTS) and place by the share of points (PLACEMENTS).

A proof is marked here with `fitch_checker`, the server's copy of the
editor's rules, so a finished proof in the browser is right here too, and a
proof the browser claims is finished but is not, is not.

The placement is a start level for `progress.py`: every level up to it is
open, every level below it counts as cleared. Skipping the test leaves the
ladder exactly as it was, starting at Chapter 5 easy.

Everything here is pure, like `progress.py`. `firestore_db` stores the bank and
the user's test; this module only decides what to deal and what a score means.
"""

import random

import fitch_checker
import progress

# How many questions a test deals, and how many it must have to run at all.
TEST_SIZE = 5
MIN_SIZE = 3

# How a test of TEST_SIZE is split. The multiple choice (MIX) comes first and
# the Fitch proofs (FITCH_MIX) last; a proof is harder than a question on the
# same band, so it is the proofs that tell the top of the field apart.
MIX = {"easy": 2, "medium": 1}
FITCH_MIX = {"medium": 1, "hard": 1}

# The two kinds of question. A document with no kind is multiple choice, which
# is what the whole bank was before proofs joined it.
CHOICE, FITCH = "choice", "fitch"

# A submitted proof longer than this is refused unread. The proofs in the
# bank run to eight lines; this only stops a pasted novel being checked.
MAX_PROOF_LINES = 60

# Points per correct answer. A hard question is worth more than an easy one,
# so getting the hard one right is what moves someone up a placement.
WEIGHTS = {"easy": 1, "medium": 2, "hard": 3}

# Share of the points needed for each placement, lowest first, and the level
# it starts you at. Beginner is the ladder as it is without a test.
PLACEMENTS = (
    (0.0, "Beginner", (5, "easy")),
    (0.4, "Intermediate", (5, "medium")),
    (0.7, "Advanced", (5, "hard")),
    (0.9, "Expert", (10, "easy")),
)

# The fields of a question it is safe to send to the browser. The answer, the
# worked proof and the explanation stay on the server until it is submitted.
PUBLIC_FIELDS = ("id", "kind", "topic", "chapter", "difficulty", "prompt",
                 "choices", "premises", "goal")


def is_active(question):
    """Inactive questions are kept in the bank but never dealt."""
    return question.get("active", True) is not False


def kind(question):
    return FITCH if question.get("kind") == FITCH else CHOICE


def usable(question):
    """Can this question be dealt and marked? Guards against a bad document.

    A proof question has to come with a worked proof the checker accepts,
    which is also what shows its premises and goal parse and are provable.
    """
    if question.get("difficulty") not in WEIGHTS or not question.get("prompt"):
        return False
    if kind(question) == FITCH:
        premises, goal = question.get("premises"), question.get("goal")
        if not (isinstance(premises, list) and isinstance(goal, str)
                and isinstance(question.get("proof"), list)):
            return False
        return not fitch_checker.check_proof(premises, goal, question["proof"])
    choices = question.get("choices") or []
    answer = question.get("answer")
    return (len(choices) >= 2
            and isinstance(answer, int) and 0 <= answer < len(choices))


def select(bank, rng=None):
    """Deal a test from the bank: multiple choice easiest first, then proofs.

    Each band of each kind gets its share of MIX or FITCH_MIX, preferring a
    topic not dealt yet. A band that is short is made up from the others of
    the same kind, easiest first; proofs the bank cannot supply are made up
    with multiple choice, so a bank without proofs still deals a full test.
    Returns [] when fewer than MIN_SIZE active questions exist, since a
    two-question test places nobody fairly.
    """
    rng = rng or random.Random()
    pool = [q for q in bank if is_active(q) and usable(q)]
    if len(pool) < MIN_SIZE:
        return []

    by_band = {(k, band): [] for k in (CHOICE, FITCH) for band in progress.BANDS}
    for question in pool:
        by_band[kind(question), question["difficulty"]].append(question)
    for questions in by_band.values():
        rng.shuffle(questions)

    topics = set()

    def take(into, k, band, count):
        for _ in range(count):
            left = by_band[k, band]
            if not left:
                return
            fresh = [q for q in left if q.get("topic") not in topics]
            question = (fresh or left)[0]
            left.remove(question)
            into.append(question)
            topics.add(question.get("topic"))

    def deal(k, mix, size):
        dealt = []
        for band in progress.BANDS:
            take(dealt, k, band, mix.get(band, 0))
        for band in progress.BANDS:       # top up a short band, easiest first
            take(dealt, k, band, size - len(dealt))
        return dealt

    proofs = deal(FITCH, FITCH_MIX, sum(FITCH_MIX.values()))
    choices = deal(CHOICE, MIX, TEST_SIZE - len(proofs))

    order = {band: i for i, band in enumerate(progress.BANDS)}
    choices.sort(key=lambda q: order[q["difficulty"]])
    proofs.sort(key=lambda q: order[q["difficulty"]])
    return choices + proofs


def public(question):
    """A question as the browser sees it: no answer, no explanation."""
    out = {key: question.get(key) for key in PUBLIC_FIELDS}
    out["kind"] = kind(question)
    return out


def mark_proof(question, steps):
    """(correct, problems, steps kept) for a submitted proof.

    `steps` is what the editor sends: a list of {formula, rule, depth, refs,
    subref}. Anything else, or a proof past MAX_PROOF_LINES, is wrong and not
    kept. A proof is right when the checker finds no problem with it.
    """
    if not isinstance(steps, list) or not steps:
        return False, ["no proof was submitted"], None
    if len(steps) > MAX_PROOF_LINES or not all(isinstance(s, dict) for s in steps):
        return False, ["that is not a proof the editor could have built"], None
    kept = [{"formula": str(s.get("formula", ""))[:200],
             "rule": str(s.get("rule", ""))[:12],
             "depth": s.get("depth", 0),
             "refs": s.get("refs") or [],
             **({"subref": s["subref"]} if s.get("subref") else {})}
            for s in steps]
    if all(s["rule"] == "premise" for s in kept):
        return False, ["the proof was not started"], kept
    problems = fitch_checker.check_proof(
        question["premises"], question["goal"], kept)
    return not problems, problems, kept


def worked_rows(question):
    """A proof question's worked proof as rows for the result screen."""
    rows = []
    for n, step in enumerate(question["proof"], 1):
        if step.get("subref"):
            cites = "%d-%d" % tuple(step["subref"])
        else:
            cites = ", ".join(str(r) for r in step.get("refs") or [])
        rows.append({"n": n, "depth": int(step.get("depth", 0)),
                     "formula": fitch_checker.show(fitch_checker.parse(step["formula"])),
                     "rule": fitch_checker.RULES.get(step["rule"], step["rule"]),
                     "cites": cites})
    return rows


def score(questions, answers):
    """Mark a test. `answers` maps question id to the chosen index, or, for a
    proof question, to the proof's steps.

    An unanswered question, an answer that is not a choice, or a proof the
    checker does not accept, is wrong. Returns the points earned and possible,
    how many were right, and the marking of each question for the result
    screen.
    """
    answers = answers or {}
    earned = possible = right = 0
    marked = []
    for question in questions:
        weight = WEIGHTS[question["difficulty"]]
        given = answers.get(question["id"])
        if kind(question) == FITCH:
            correct, problems, chosen = mark_proof(question, given)
        else:
            problems = None
            try:
                chosen = int(given)
            except (TypeError, ValueError):
                chosen = None
            correct = chosen == question["answer"]
        possible += weight
        if correct:
            earned += weight
            right += 1
        mark = {"id": question["id"], "correct": correct, "chosen": chosen}
        if problems is not None:
            mark["problems"] = problems
        marked.append(mark)
    return {"earned": earned, "possible": possible, "right": right,
            "total": len(questions), "marked": marked}


def place(earned, possible):
    """The placement a score earns: (name, (chapter, band))."""
    share = earned / possible if possible else 0.0
    name, start = PLACEMENTS[0][1], PLACEMENTS[0][2]
    for threshold, label, level in PLACEMENTS:
        if share >= threshold:
            name, start = label, level
    return name, start


def start_of(profile):
    """The start level a profile's finished level test earned, or None.

    None for a test that was skipped, never taken, or holds a level the ladder
    no longer has, so a stale record never opens anything by accident.
    """
    test = (profile or {}).get("level_test") or {}
    if test.get("status") != "done":
        return None
    placement = test.get("placement") or {}
    start = (placement.get("chapter"), placement.get("band"))
    return start if progress.rank(*start) is not None else None


def opened_by(start):
    """The levels a start level opens, for the result screen to list."""
    if start is None:
        return [progress.LEVELS[0]]
    top = progress.rank(*start)
    return list(progress.LEVELS[:top + 1])
