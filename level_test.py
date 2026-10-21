"""The level test a new account takes at sign-up.

A short multiple-choice test, dealt from its own bank, that decides where on
the ladder someone starts. A Fitch proof is the wrong thing to place people
with — a hard one runs to twenty lines — so the bank is questions about the
same material that can be answered in a minute each: which rule, which
sentence is equivalent, which premises entail what.

    Deal TEST_SIZE questions, mostly easy and medium with a hard one (MIX).
    Spread them over as many topics as the bank allows.
    Never deal an inactive question.
    Score by difficulty (WEIGHTS) and place by the share of points (PLACEMENTS).

The placement is a start level for `progress.py`: every level up to it is
open, every level below it counts as cleared. Skipping the test leaves the
ladder exactly as it was, starting at Chapter 5 easy.

Everything here is pure, like `progress.py`. `firestore_db` stores the bank and
the user's test; this module only decides what to deal and what a score means.
"""

import random

import progress

# How many questions a test deals, and how many it must have to run at all.
TEST_SIZE = 5
MIN_SIZE = 3

# How a test of TEST_SIZE is split across the bands. Mostly easy and medium,
# with a few hard ones, which is what tells the top of the field apart.
MIX = {"easy": 2, "medium": 2, "hard": 1}

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

# The fields of a question it is safe to send to the browser. The answer and
# its explanation stay on the server until the test is submitted.
PUBLIC_FIELDS = ("id", "topic", "difficulty", "prompt", "choices")


def is_active(question):
    """Inactive questions are kept in the bank but never dealt."""
    return question.get("active", True) is not False


def usable(question):
    """Can this question be dealt and marked? Guards against a bad document."""
    choices = question.get("choices") or []
    answer = question.get("answer")
    return (question.get("difficulty") in WEIGHTS
            and bool(question.get("prompt"))
            and len(choices) >= 2
            and isinstance(answer, int) and 0 <= answer < len(choices))


def select(bank, rng=None):
    """Deal a test from the bank: a list of questions, easiest first.

    Each band gets its share of MIX, preferring a topic not dealt yet, so five
    questions cover five topics when the bank has them. A band that is short is
    made up from the others, easy and medium before hard. Returns [] when fewer
    than MIN_SIZE active questions exist, since a two-question test places
    nobody fairly.
    """
    rng = rng or random.Random()
    pool = [q for q in bank if is_active(q) and usable(q)]
    if len(pool) < MIN_SIZE:
        return []

    by_band = {band: [] for band in progress.BANDS}
    for question in pool:
        by_band[question["difficulty"]].append(question)
    for questions in by_band.values():
        rng.shuffle(questions)

    dealt, topics = [], set()

    def take(band, count):
        for _ in range(count):
            left = by_band[band]
            if not left:
                return
            fresh = [q for q in left if q.get("topic") not in topics]
            question = (fresh or left)[0]
            left.remove(question)
            dealt.append(question)
            topics.add(question.get("topic"))

    for band in progress.BANDS:
        take(band, MIX.get(band, 0))
    # Top up a short band from the rest, easiest first.
    for band in progress.BANDS:
        take(band, TEST_SIZE - len(dealt))

    order = {band: i for i, band in enumerate(progress.BANDS)}
    dealt.sort(key=lambda q: order[q["difficulty"]])
    return dealt


def public(question):
    """A question as the browser sees it: no answer, no explanation."""
    return {key: question.get(key) for key in PUBLIC_FIELDS}


def score(questions, answers):
    """Mark a test. `answers` maps question id to the chosen index.

    An unanswered question, or an answer that is not a choice, is wrong.
    Returns the points earned and possible, how many were right, and the
    marking of each question for the result screen.
    """
    answers = answers or {}
    earned = possible = right = 0
    marked = []
    for question in questions:
        weight = WEIGHTS[question["difficulty"]]
        chosen = answers.get(question["id"])
        try:
            chosen = int(chosen)
        except (TypeError, ValueError):
            chosen = None
        correct = chosen == question["answer"]
        possible += weight
        if correct:
            earned += weight
            right += 1
        marked.append({"id": question["id"], "correct": correct,
                       "chosen": chosen})
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
