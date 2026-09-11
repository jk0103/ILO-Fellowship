"""Load the hand-written starter questions in seed_questions.json into Firestore.

Every proof is checked before it is written, so this is safe to re-run: the
document id is a fingerprint of the premises and goal, so a second run updates
the same five documents instead of adding more.

    python seed_questions.py            # verify and write
    python seed_questions.py --dry-run  # verify only
"""

import argparse
import json
import os
import sys

import fitch_checker as fc
import fitch_generator as gen
import firestore_db as store

SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "seed_questions.json")


def load():
    with open(SEED_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="check the proofs without writing to Firestore")
    args = parser.parse_args(argv)

    questions, failed = [], False
    for i, question in enumerate(load(), 1):
        problems = fc.check_proof(question["premises"], question["goal"],
                                  question["proof"])
        if problems:
            print(f"question {i}: {problems}", file=sys.stderr)
            failed = True
            continue
        question["line_count"] = len(question["proof"])
        question["difficulty"] = fc.difficulty(question["proof"])
        question["statement"] = gen.render_question(question)
        questions.append(question)
        print(f"{i}. [{question['difficulty']:6} {question['line_count']:2} lines] "
              f"{question['statement']}")

    if failed:
        print("\nSome proofs did not verify; nothing was written.", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"\n{len(questions)} verified. Nothing written (--dry-run).")
        return 0

    for question in questions:
        qid = store.save_question(question, source="seed")
        print(f"saved {qid}  {question['statement'][:60]}")
    print(f"\n{len(questions)} questions in Firestore.")
    print("counts:", store.question_counts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
