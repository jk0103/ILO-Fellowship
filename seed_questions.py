"""Load the starter questions that ship as JSON into Firestore.

Chapter 5 comes from `seed_questions.json` (hand-written), Chapter 10 from
`ch10_questions.json` (written by `ch10_generator.py` and kept in the repo).
Every proof is checked with that chapter's own checker before it is written, so
this is safe to re-run: the document id is a fingerprint of the premises and
goal, so a second run updates the same documents instead of adding more.

    python seed_questions.py                   # Chapter 5, verify and write
    python seed_questions.py --chapter 10      # Chapter 10
    python seed_questions.py --chapter all     # both
    python seed_questions.py --dry-run         # verify only
    python seed_questions.py --level-test      # the level test's own bank

The level test's questions are multiple choice, not proofs, so they come from
`level_test_questions.json` and are checked for shape instead: a known band, a
prompt, at least two choices, an answer that is one of them, and an id no other
question uses. The id is the document id, so re-running updates in place.
"""

import argparse
import json
import os
import sys

import fitch_checker as fc
import fitch_generator as gen
import ch10_checker as cc
import firestore_db as store
import level_test

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _ch5(question):
    """Check one Chapter 5 question and fill in what the store wants."""
    problems = fc.check_proof(question["premises"], question["goal"],
                              question["proof"])
    if problems:
        return problems
    question["difficulty"] = fc.difficulty(question["proof"])
    # Chapter 5's JSON has no prose; the generator renders it from the argument.
    question["statement"] = gen.render_question(question)
    return []


def _ch10(question):
    """The same for Chapter 10, whose questions carry their own prose."""
    problems = cc.check_proof(question["premises"], question["goal"],
                              question["proof"],
                              question.get("constants") or [])
    if problems:
        return problems
    question["difficulty"] = cc.difficulty(question["proof"])
    question["statement"] = question.get("prompt") or question.get("statement", "")
    return []


CHAPTERS = {
    5: {"file": "seed_questions.json", "prepare": _ch5},
    10: {"file": "ch10_questions.json", "prepare": _ch10},
}


def prepare(chapter):
    """Return (questions, failed) for one chapter, checking every proof."""
    spec = CHAPTERS[chapter]
    path = os.path.join(BASE_DIR, spec["file"])
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    print(f"Chapter {chapter}  ({spec['file']})")
    questions, failed = [], False
    for i, question in enumerate(raw, 1):
        problems = spec["prepare"](question)
        if problems:
            print(f"  question {i}: {problems}", file=sys.stderr)
            failed = True
            continue
        question["chapter"] = chapter
        question["line_count"] = len(question["proof"])
        questions.append(question)
        print(f"  {i:2}. [{question['difficulty']:6} "
              f"{question['line_count']:2} lines] {question['statement']}")
    return questions, failed


def prepare_level_test():
    """Return (questions, failed) for the level test's bank."""
    path = os.path.join(BASE_DIR, "level_test_questions.json")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    print("Level test  (level_test_questions.json)")
    questions, failed, seen = [], False, set()
    for i, question in enumerate(raw, 1):
        qid = question.get("id")
        if not qid or qid in seen:
            print(f"  question {i}: missing or repeated id {qid!r}",
                  file=sys.stderr)
            failed = True
            continue
        seen.add(qid)
        if not level_test.usable(question) or not question.get("topic"):
            print(f"  question {i} ({qid}): needs a topic, a known difficulty, "
                  f"a prompt, two or more choices and an answer among them",
                  file=sys.stderr)
            failed = True
            continue
        questions.append(question)
        flag = "" if level_test.is_active(question) else "  (inactive)"
        print(f"  {i:2}. [{question['difficulty']:6} {question['topic']:16}] "
              f"{question['prompt'][:52]}{flag}")
    return questions, failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chapter", default="5", choices=["5", "10", "all"],
                        help="which chapter's starter questions to load "
                             "(default: 5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="check the proofs without writing to Firestore")
    parser.add_argument("--level-test", action="store_true",
                        help="load the level test's bank instead of proofs")
    args = parser.parse_args(argv)

    if args.level_test:
        questions, failed = prepare_level_test()
        print()
        if failed:
            print("Some questions are malformed; nothing was written.",
                  file=sys.stderr)
            return 1
        if args.dry_run:
            print(f"{len(questions)} checked. Nothing written (--dry-run).")
            return 0
        for question in questions:
            store.save_level_test_question(question)
        print(f"{len(questions)} level-test questions written.")
        return 0

    wanted = sorted(CHAPTERS) if args.chapter == "all" else [int(args.chapter)]

    questions, failed = [], False
    for chapter in wanted:
        batch, batch_failed = prepare(chapter)
        questions.extend(batch)
        failed = failed or batch_failed
        print()

    if failed:
        print("Some proofs did not verify; nothing was written.", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"{len(questions)} verified. Nothing written (--dry-run).")
        return 0

    for question in questions:
        qid = store.save_question(question, source="seed")
        print(f"saved {qid}  [ch{question['chapter']}] "
              f"{question['statement'][:56]}")

    print(f"\n{len(questions)} questions written.")
    for chapter in wanted:
        print(f"  chapter {chapter}:", store.question_counts(chapter=chapter))
    return 0


if __name__ == "__main__":
    sys.exit(main())
