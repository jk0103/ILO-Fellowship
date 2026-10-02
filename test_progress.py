"""Offline tests for the level ladder. No key, no network, no Firestore.

`progress.py` is pure, so the whole gating rule can be checked against
hand-written counts. What matters is the shape of the ladder, not the number
in TO_CLEAR — these tests read it rather than assuming 3, so raising it as the
bank grows does not break them.

Run:  python3 test_progress.py
"""

import progress as p

checks = []


def check(label, condition):
    checks.append((label, bool(condition)))
    print("%-48s %s" % (label, "PASS" if condition else "FAIL"))


def counts(**bands):
    """Counts from a spec like counts(c5_easy=3): chapter, band, solves."""
    out = {}
    for key, solved in bands.items():
        chapter, band = key.split("_")
        out.setdefault(int(chapter[1:]), {})[band] = {
            "solved": solved, "seen": solved, "attempts": solved}
    return out


N = p.TO_CLEAR
FIRST, SECOND = p.CHAPTER_ORDER[0], p.CHAPTER_ORDER[1]

# --- a new account ----------------------------------------------------------
blank = {}
check("first chapter's easy band is open", p.is_unlocked(blank, FIRST, "easy"))
check("medium is shut to start", not p.is_unlocked(blank, FIRST, "medium"))
check("hard is shut to start", not p.is_unlocked(blank, FIRST, "hard"))
check("second chapter is shut to start", not p.is_unlocked(blank, SECOND))
check("second chapter's easy band is shut too",
      not p.is_unlocked(blank, SECOND, "easy"))

# --- one band short ---------------------------------------------------------
almost = counts(**{"c%d_easy" % FIRST: N - 1})
check("one short does not open medium", not p.is_unlocked(almost, FIRST, "medium"))

# --- easy cleared -----------------------------------------------------------
easy_done = counts(**{"c%d_easy" % FIRST: N})
check("clearing easy opens medium", p.is_unlocked(easy_done, FIRST, "medium"))
check("clearing easy leaves hard shut", not p.is_unlocked(easy_done, FIRST, "hard"))
check("clearing easy leaves the next chapter shut",
      not p.is_unlocked(easy_done, SECOND))

# Solving past the bar keeps it open and does not skip a level.
over = counts(**{"c%d_easy" % FIRST: N + 5})
check("extra easy solves do not open hard", not p.is_unlocked(over, FIRST, "hard"))
check("extra easy solves do not open the next chapter",
      not p.is_unlocked(over, SECOND))

# --- the whole first chapter ------------------------------------------------
mid_done = counts(**{"c%d_easy" % FIRST: N, "c%d_medium" % FIRST: N})
check("clearing medium opens hard", p.is_unlocked(mid_done, FIRST, "hard"))
check("hard still unfinished keeps the next chapter shut",
      not p.is_unlocked(mid_done, SECOND))

all_done = counts(**{"c%d_easy" % FIRST: N, "c%d_medium" % FIRST: N,
                     "c%d_hard" % FIRST: N})
check("clearing every band clears the chapter", p.cleared(all_done, FIRST))
check("a cleared chapter opens the next one", p.is_unlocked(all_done, SECOND))
check("the next chapter starts at easy",
      p.is_unlocked(all_done, SECOND, "easy")
      and not p.is_unlocked(all_done, SECOND, "medium"))

# --- nonsense is never a level ----------------------------------------------
check("an unknown chapter is shut", not p.is_unlocked(blank, 7, "easy"))
check("an unknown band is shut", not p.is_unlocked(blank, FIRST, "trivial"))
check("a string chapter still resolves", p.is_unlocked(blank, str(FIRST), "easy"))

# --- the shape the dashboard renders ----------------------------------------
board = p.ladder(easy_done, {FIRST: "Chapter %d — propositional" % FIRST})
check("ladder has one entry per chapter", len(board) == len(p.CHAPTER_ORDER))
check("ladder keeps chapter order", [c["number"] for c in board]
      == list(p.CHAPTER_ORDER))
check("ladder has three levels per chapter",
      all(len(c["levels"]) == len(p.BANDS) for c in board))
check("ladder uses the label it is given", "propositional" in board[0]["label"])
check("ladder falls back to a plain label", board[1]["label"] ==
      "Chapter %d" % SECOND)
check("cleared level is marked cleared", board[0]["levels"][0]["cleared"])
check("cleared level's bar is full", board[0]["levels"][0]["percent"] == 100)
check("empty level's bar is empty", board[0]["levels"][1]["percent"] == 0)
check("a shut level says what opens it",
      "unlock" in board[0]["levels"][2]["note"])
check("a shut chapter names the one before it", board[1]["requires"] == FIRST)
check("every level carries its own address",
      all(level["chapter"] == c["number"] and level["band"] in p.BANDS
          for c in board for level in c["levels"]))

# The bar never overruns, whatever the count.
flooded = p.ladder(over)
check("an over-solved level's bar is capped",
      flooded[0]["levels"][0]["percent"] == 100)

# --- messages ---------------------------------------------------------------
check("a locked chapter's message names the chapter before it",
      str(FIRST) in p.locked_message(blank, SECOND, "easy"))
check("a locked band's message names the band before it",
      "easy" in p.locked_message(blank, FIRST, "medium"))
check("nonsense gets a message too, not a crash",
      p.locked_message(blank, 7, "easy"))

failed = [label for label, ok in checks if not ok]
print("\n%d/%d passed" % (len(checks) - len(failed), len(checks)))
if failed:
    print("FAILED:", ", ".join(failed))
    raise SystemExit(1)
