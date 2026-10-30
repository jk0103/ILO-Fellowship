"""Offline tests for the level test. No key, no network, no Firestore.

`level_test.py` is pure, so dealing, marking and placing can all be checked
against a hand-built bank — and against the real one in
`level_test_questions.json`, which has to be able to deal a full test. The
ladder's side of it, a start level opening the levels below it, is checked
here too, through `progress.py`.

Run:  python3 test_level_test.py
"""

import json
import os
import random

import level_test as lt
import progress as p

checks = []


def check(label, condition):
    checks.append((label, bool(condition)))
    print("%-56s %s" % (label, "PASS" if condition else "FAIL"))


def question(qid, band, topic, active=True, answer=0):
    return {"id": qid, "difficulty": band, "topic": topic, "active": active,
            "prompt": "Q " + qid, "choices": ["a", "b", "c", "d"],
            "answer": answer}


# A two-line proof: p, then p ∨ q by Or Introduction.
PROOF = [{"formula": "p", "rule": "premise", "depth": 0, "refs": []},
         {"formula": "p ∨ q", "rule": "oi", "depth": 0, "refs": [1]}]


def proof_question(qid, band, active=True, proof=PROOF):
    return {"id": qid, "kind": "fitch", "difficulty": band,
            "topic": "fitch-proof", "active": active,
            "prompt": "Prove p ∨ q from p.", "premises": ["p"], "goal": "p ∨ q",
            "proof": proof}


TOPICS = ["connectives", "entailment", "fitch-rules", "quantifiers",
          "quantifier-rules"]
CHOICES = [question("%s%d" % (band[0], i), band, TOPICS[i % len(TOPICS)])
           for band in p.BANDS for i in range(6)]
PROOFS = [proof_question("f%s%d" % (band[0], i), band)
          for band in p.BANDS for i in range(3)]
BANK = CHOICES + PROOFS
N_PROOFS = sum(lt.FITCH_MIX.values())

# --- dealing ----------------------------------------------------------------
test = lt.select(BANK, random.Random(1))
choices = [q for q in test if lt.kind(q) == lt.CHOICE]
proofs = [q for q in test if lt.kind(q) == lt.FITCH]
check("a test deals TEST_SIZE questions", len(test) == lt.TEST_SIZE)
check("a test keeps the mix of bands",
      all(sum(q["difficulty"] == b for q in choices) == n
          for b, n in lt.MIX.items())
      and all(sum(q["difficulty"] == b for q in proofs) == n
              for b, n in lt.FITCH_MIX.items()))
check("the last questions are the proofs",
      len(proofs) == N_PROOFS and test[-N_PROOFS:] == proofs)
check("mostly easy and medium, few hard",
      sum(q["difficulty"] == "hard" for q in test) < lt.TEST_SIZE / 2)
check("easiest first, within each kind",
      all([p.BANDS.index(q["difficulty"]) for q in part]
          == sorted(p.BANDS.index(q["difficulty"]) for q in part)
          for part in (choices, proofs)))
check("no question twice", len({q["id"] for q in test}) == len(test))
check("topics are spread when the bank allows",
      len({q["topic"] for q in choices}) == len(choices))

only_choice = lt.select(CHOICES, random.Random(3))
check("a bank without proofs still deals a full test",
      len(only_choice) == lt.TEST_SIZE
      and all(lt.kind(q) == lt.CHOICE for q in only_choice))
bad_proof = [proof_question("bad", "hard", proof=PROOF[:1])]
check("a proof question whose worked proof fails is never dealt",
      not lt.usable(bad_proof[0])
      and all(q["id"] != "bad" for q in lt.select(CHOICES + bad_proof)))

draws = [{q["id"] for q in lt.select(BANK, random.Random(seed))}
         for seed in range(20)]
check("different draws deal different tests", len(set(map(frozenset, draws))) > 1)

inactive = [dict(q, active=False) if q["difficulty"] == "hard" or i % 2 else q
            for i, q in enumerate(BANK)]
check("inactive questions are never dealt",
      all(q["active"] is not False for seed in range(50)
          for q in lt.select(inactive, random.Random(seed))))

no_hard = [q for q in BANK if q["difficulty"] != "hard"]
short = lt.select(no_hard, random.Random(2))
check("a band with nothing is made up from the others",
      len(short) == lt.TEST_SIZE and all(q["difficulty"] != "hard" for q in short))

check("too small a bank deals no test",
      lt.select(BANK[:lt.MIN_SIZE - 1]) == [])
check("inactive questions do not count towards the minimum",
      lt.select([dict(q, active=False) for q in BANK]) == [])
broken = [dict(q, answer=9) for q in CHOICES]
check("a question whose answer is not a choice is never dealt",
      lt.select(broken) == [])

# --- what the browser sees --------------------------------------------------
shown = lt.public(dict(BANK[0], explanation="because"))
check("the browser never sees the answer", "answer" not in shown)
check("the browser never sees the explanation", "explanation" not in shown)
check("the browser sees prompt and choices",
      shown["prompt"] and shown["choices"] == ["a", "b", "c", "d"])
shown = lt.public(PROOFS[0])
check("the browser sees a proof's premises and goal",
      shown["kind"] == lt.FITCH and shown["premises"] == ["p"]
      and shown["goal"] == "p ∨ q")
check("the browser never sees the worked proof", "proof" not in shown)

# --- marking ----------------------------------------------------------------
dealt = [question("e", "easy", "x", answer=1), question("m", "medium", "y"),
         question("h", "hard", "z", answer=3)]
full = sum(lt.WEIGHTS[q["difficulty"]] for q in dealt)

perfect = lt.score(dealt, {"e": 1, "m": 0, "h": 3})
check("all right earns every point", perfect["earned"] == full == perfect["possible"])
check("all right counts every question", perfect["right"] == perfect["total"] == 3)
blank = lt.score(dealt, {})
check("unanswered questions are wrong", blank["earned"] == 0 and blank["right"] == 0)
check("answers may arrive as strings", lt.score(dealt, {"e": "1"})["right"] == 1)
check("nonsense answers are wrong, not a crash",
      lt.score(dealt, {"e": "B", "m": None, "h": [3]})["right"] == 0)
only_hard = lt.score(dealt, {"h": 3})
check("a hard question is worth more than an easy one",
      only_hard["earned"] > lt.score(dealt, {"e": 1})["earned"])
check("each question is marked for the review",
      [m["correct"] for m in only_hard["marked"]] == [False, False, True])

pq = proof_question("f", "hard")
right_proof = lt.score([pq], {"f": PROOF})
check("a correct proof is right", right_proof["right"] == 1
      and right_proof["marked"][0]["problems"] == [])
check("a correct proof is kept for the record",
      right_proof["marked"][0]["chosen"][1]["formula"] == "p ∨ q")
wrong = lt.score([pq], {"f": [dict(PROOF[0]), dict(PROOF[1], formula="q ∨ p")]})
check("a proof that ends on the wrong sentence is wrong",
      wrong["right"] == 0 and wrong["marked"][0]["problems"])
forged = lt.score([pq], {"f": [{"formula": "p ∨ q", "rule": "premise",
                                "depth": 0, "refs": []}]})
check("a made-up premise is wrong", forged["right"] == 0)
check("an unfinished proof is wrong",
      lt.score([pq], {"f": PROOF[:1]})["right"] == 0)
check("no proof is wrong", lt.score([pq], {})["right"] == 0)
untouched = lt.score([pq], {"f": PROOF[:1]})["marked"][0]["problems"]
check("an untouched proof says it was not started",
      untouched == ["the proof was not started"])
rows = lt.worked_rows(pq)
check("a worked proof is sent as rows",
      [r["formula"] for r in rows] == ["p", "p ∨ q"]
      and rows[1]["rule"] == "Or Introduction" and rows[1]["cites"] == "1")
check("nonsense proofs are wrong, not a crash",
      all(lt.score([pq], {"f": junk})["right"] == 0 for junk in (
          "p ∨ q", 3, [1, 2], [{"formula": "((("}], [{"depth": "x"}],
          [{"formula": "p", "rule": "premise", "refs": "12"}],
          PROOF * lt.MAX_PROOF_LINES)))

# --- placing ----------------------------------------------------------------
check("nothing right is the bottom placement",
      lt.place(0, full) == (lt.PLACEMENTS[0][1], lt.PLACEMENTS[0][2]))
check("the bottom placement starts where a new account does",
      lt.PLACEMENTS[0][2] == p.LEVELS[0])
check("full marks is the top placement",
      lt.place(full, full) == (lt.PLACEMENTS[-1][1], lt.PLACEMENTS[-1][2]))
check("placements climb as the score does",
      [p.rank(*lt.place(n, 100)[1]) for n in range(0, 101, 5)]
      == sorted(p.rank(*lt.place(n, 100)[1]) for n in range(0, 101, 5)))
check("every placement is a level on the ladder",
      all(p.rank(*level) is not None for _, _, level in lt.PLACEMENTS))
check("an empty test places at the bottom", lt.place(0, 0)[1] == p.LEVELS[0])

# The worked example: a high score opens easy and medium.
easy_medium = [level for _, name, level in lt.PLACEMENTS
               if name == "Intermediate"][0]
check("Intermediate opens Chapter 5 easy and medium",
      lt.opened_by(easy_medium) == [(5, "easy"), (5, "medium")])

# --- the profile ------------------------------------------------------------
done = {"level_test": {"status": "done",
                       "placement": {"chapter": 5, "band": "hard"}}}
check("a finished test gives a start level", lt.start_of(done) == (5, "hard"))
check("a skipped test gives none",
      lt.start_of({"level_test": {"status": "skipped"}}) is None)
check("a profile with no test gives none", lt.start_of({}) is None)
check("a placement the ladder lacks gives none",
      lt.start_of({"level_test": {"status": "done", "placement":
                                  {"chapter": 7, "band": "easy"}}}) is None)

# --- the ladder, from a start level -----------------------------------------
N = p.TO_CLEAR
FIRST, SECOND = p.CHAPTER_ORDER[0], p.CHAPTER_ORDER[1]
nothing = {}

start = (FIRST, "medium")
check("a start level opens itself", p.is_unlocked(nothing, FIRST, "medium", start))
check("a start level opens the levels below it",
      p.is_unlocked(nothing, FIRST, "easy", start))
check("a start level leaves the level above it shut",
      not p.is_unlocked(nothing, FIRST, "hard", start))
check("levels below the start count as cleared",
      p.cleared(nothing, FIRST, "easy", start)
      and not p.cleared(nothing, FIRST, "medium", start))
check("clearing the start level opens the next as usual",
      p.is_unlocked({FIRST: {"medium": {"solved": N}}}, FIRST, "hard", start))
check("no start level is the ladder as it was",
      not p.is_unlocked(nothing, FIRST, "medium", None))

top = (FIRST, "hard")
check("placed at hard, the next chapter waits for hard to be cleared",
      not p.is_unlocked(nothing, SECOND, "easy", top))
check("clearing hard opens the next chapter without the skipped bands",
      p.is_unlocked({FIRST: {"hard": {"solved": N}}}, SECOND, "easy", top))

expert = (SECOND, "easy")
check("a start in a later chapter opens that chapter",
      p.is_unlocked(nothing, SECOND, "easy", expert)
      and p.is_unlocked(nothing, SECOND, start=expert))
check("and every level of the chapters before it",
      all(p.is_unlocked(nothing, FIRST, b, expert) for b in p.BANDS))

board = p.ladder(nothing, start=start)
easy_card = board[0]["levels"][0]
check("a placed-out level is shown as cleared", easy_card["cleared"])
check("a placed-out level says why", "level test" in easy_card["note"])
check("a placed-out level's bar is full", easy_card["percent"] == 100)
check("the start level is open and not cleared",
      board[0]["levels"][1]["unlocked"] and not board[0]["levels"][1]["cleared"])
check("a shut level's message still names what opens it",
      "medium" in p.locked_message(nothing, FIRST, "hard", start))

# --- the shipped bank -------------------------------------------------------
path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "level_test_questions.json")
with open(path, encoding="utf-8") as fh:
    shipped = json.load(fh)
check("every shipped question can be dealt and marked",
      all(lt.usable(q) for q in shipped))
check("every shipped question has a topic", all(q.get("topic") for q in shipped))
check("shipped ids are unique", len({q["id"] for q in shipped}) == len(shipped))
check("the shipped bank deals a full test",
      all(len(lt.select(shipped, random.Random(s))) == lt.TEST_SIZE
          for s in range(20)))
positions = {q["answer"] for q in shipped if lt.kind(q) == lt.CHOICE}
check("shipped answers are not all in one position", len(positions) > 1)
check("the shipped bank ends every test on proofs",
      all(all(lt.kind(q) == lt.FITCH
              for q in lt.select(shipped, random.Random(s))[-N_PROOFS:])
          for s in range(20)))

failed = [label for label, ok in checks if not ok]
print("\n%d/%d passed" % (len(checks) - len(failed), len(checks)))
if failed:
    print("FAILED:", ", ".join(failed))
    raise SystemExit(1)
