"""The level ladder: which chapters and difficulty bands a user has opened up.

Practice is gated so nobody meets Chapter 10's quantifier rules before the
propositional ones are solid, and nobody meets a twenty-line proof before a
six-line one. The rule is the same everywhere:

    Clear a level by solving TO_CLEAR distinct questions in it.
    A band opens when the band before it in the same chapter is cleared.
    A chapter opens when every band of the chapter before it is cleared.

So Chapter 5 easy is the only level open to a new account, and Chapter 10 is
reached by clearing all three of Chapter 5's bands — TO_CLEAR * 3 questions.
There is deliberately one number to turn: the bank is small at the moment, so
TO_CLEAR is meant to keep pace with it. (If the next chapter should instead
open on a bare count of solves anywhere in the one before it, that is the
`cleared` test below, and nothing else.)

The level test a new account takes at sign-up can start someone higher up.
Its result is a *start* level, a (chapter, band) pair: every level up to and
including it is open, and every level below it counts as cleared, so the rule
above carries on from there. A start of None is an account that skipped the
test or never took it, which is exactly the ladder as it was.

Accuracy is not part of the rule yet. `counts` already carries how many
questions were opened alongside how many were solved, so a ratio can join
`cleared` without touching anything that calls it.

Everything here is pure: it takes the counts `firestore_db.progress_counts`
builds and answers questions about them. Nothing in this module reads or
writes.
"""

# How many distinct questions clear one level. Raise it as the bank grows.
TO_CLEAR = 10

# The three difficulty bands, easiest first. Both checkers publish the same
# three as DIFFICULTIES; this is the order they are climbed in.
BANDS = ("easy", "medium", "hard")

# The chapters in teaching order. A new chapter belongs here and in app.CHAPTERS.
CHAPTER_ORDER = (5, 10)

# Every level in climbing order, so "above" and "below" mean something.
LEVELS = tuple((chapter, band) for chapter in CHAPTER_ORDER for band in BANDS)


def rank(chapter, band):
    """Where a level sits in LEVELS, or None if it is not a level."""
    try:
        return LEVELS.index((int(chapter), band))
    except (TypeError, ValueError):
        return None


def placed_out(start, chapter, band):
    """Did the level test start this user above that level?"""
    if start is None:
        return False
    here, top = rank(chapter, band), rank(*start)
    return here is not None and top is not None and here < top


def placed_in(start, chapter, band):
    """Is that level at or below the one the level test started them at?"""
    if start is None:
        return False
    here, top = rank(chapter, band), rank(*start)
    return here is not None and top is not None and here <= top


def solved(counts, chapter, band=None):
    """How many questions of `chapter` (and `band`, if named) are solved."""
    bands = counts.get(int(chapter)) or {}
    if band is None:
        return sum((cell or {}).get("solved", 0) for cell in bands.values())
    return (bands.get(band) or {}).get("solved", 0)


def cleared(counts, chapter, band=None, start=None):
    """Is that level — or, with no band, that whole chapter — cleared?

    A level the level test placed someone above counts as cleared.
    """
    if band is None:
        return all(cleared(counts, chapter, b, start) for b in BANDS)
    return solved(counts, chapter, band) >= TO_CLEAR or \
        placed_out(start, chapter, band)


def is_unlocked(counts, chapter, band=None, start=None):
    """Can this user practice here yet?

    An unknown chapter or band is not a level, so it is never unlocked; that
    keeps a hand-typed URL from opening anything by accident. `start` is the
    level the level test placed them at, if any.
    """
    chapter = int(chapter)
    if chapter not in CHAPTER_ORDER:
        return False
    if band is not None and band not in BANDS:
        return False
    if placed_in(start, chapter, band or BANDS[0]):
        return True

    position = CHAPTER_ORDER.index(chapter)
    if position and not cleared(counts, CHAPTER_ORDER[position - 1],
                                start=start):
        return False
    if band is None:
        return True

    step = BANDS.index(band)
    return step == 0 or cleared(counts, chapter, BANDS[step - 1], start)


def ladder(counts, labels=None, start=None):
    """The whole map, ready for the dashboard to lay out.

    One entry per chapter, each carrying its three bands in order with the
    progress made, whether it is open, and the sentence that says why not.
    """
    labels = labels or {}
    out = []

    for position, chapter in enumerate(CHAPTER_ORDER):
        open_chapter = is_unlocked(counts, chapter, start=start)
        previous = CHAPTER_ORDER[position - 1] if position else None
        levels = []

        for step, band in enumerate(BANDS):
            cell = (counts.get(chapter) or {}).get(band) or {}
            done = solved(counts, chapter, band)
            open_band = is_unlocked(counts, chapter, band, start)
            skipped = placed_out(start, chapter, band)

            if skipped and done < TO_CLEAR:
                note = "Placed out by your level test."
            elif not open_chapter:
                note = "Clear Chapter %d first." % previous
            elif not open_band:
                note = "Solve %d %s question%s to unlock this." % (
                    TO_CLEAR, BANDS[step - 1], "" if TO_CLEAR == 1 else "s")
            elif done >= TO_CLEAR:
                note = "Cleared."
            elif step + 1 < len(BANDS):
                note = "%d more to unlock %s." % (TO_CLEAR - done, BANDS[step + 1])
            elif position + 1 < len(CHAPTER_ORDER):
                note = "%d more to unlock Chapter %d." % (
                    TO_CLEAR - done, CHAPTER_ORDER[position + 1])
            else:
                note = "%d more to clear this chapter." % (TO_CLEAR - done)

            levels.append({
                "chapter": chapter,
                "band": band,
                "solved": done,
                "need": TO_CLEAR,
                "seen": cell.get("seen", 0),
                "unlocked": open_band,
                "cleared": done >= TO_CLEAR or skipped,
                # Capped, because solving a fourth question at a cleared level
                # should not overrun the bar. A placed-out level is full too:
                # there is nothing left to do there.
                "percent": 100 if skipped or not TO_CLEAR
                else min(100, round(100 * done / TO_CLEAR)),
                "note": note,
            })

        out.append({
            "number": chapter,
            "label": labels.get(chapter, "Chapter %d" % chapter),
            "unlocked": open_chapter,
            "cleared": cleared(counts, chapter, start=start),
            "solved": solved(counts, chapter),
            "requires": previous if not open_chapter else None,
            "levels": levels,
        })

    return out


def locked_message(counts, chapter, band, start=None):
    """Why this level is shut, phrased for a flash message."""
    chapter = int(chapter)
    if chapter not in CHAPTER_ORDER or band not in BANDS:
        return "That is not a level you can practice."
    if not is_unlocked(counts, chapter, start=start):
        previous = CHAPTER_ORDER[CHAPTER_ORDER.index(chapter) - 1]
        return ("Chapter %d is locked. Clear every level of Chapter %d first — "
                "%d questions in each band." % (chapter, previous, TO_CLEAR))
    step = BANDS.index(band)
    return ("The %s questions of Chapter %d are locked. Solve %d %s one%s "
            "first." % (band, chapter, TO_CLEAR, BANDS[step - 1],
                        "" if TO_CLEAR == 1 else "s"))
