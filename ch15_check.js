/* Check the Chapter 15 questions with the editor's own rules.
 *
 * Chapter 15's proofs use Induction and the equality rules, which only the
 * browser checker (static/fitch.js) knows, so this runs that file under Node
 * instead of keeping a second copy of the rules in Python. seed_questions.py
 * calls it before writing anything:
 *
 *     node ch15_check.js ch15_questions.json
 *
 * Every line of every proof must hold, the proof must open with the premises
 * and close on the goal outside any subproof. Problems are printed one per
 * line as "<question number>: <what is wrong>" and the exit status is 1; a
 * clean bank prints nothing and exits 0.
 */

const fs = require("fs");
const path = require("path");

// fitch.js is a browser script: it hangs its API on window and only builds
// the editor when the page has one, which this stand-in never does.
global.window = global;
global.document = { readyState: "complete", querySelector: () => null };
require(path.join(__dirname, "static", "fitch.js"));
const F = global.Fitch;

function problems(question) {
  const premises = question.premises.map(F.parse);
  const goal = F.parse(question.goal);
  const own = F.vocabulary(premises.concat([goal]));
  const objects = own.objects.concat(
    (question.constants || []).filter((n) => own.objects.indexOf(n) === -1));
  const language = { objects: objects, functions: own.functions, arity: own.arity };

  const lines = question.proof.map((step, i) => ({
    id: i + 1, depth: step.depth || 0, rule: step.rule, formula: F.parse(step.formula),
    refIds: (step.refs || []).slice(),
    subRef: step.subref ? { fromId: step.subref[0], toId: step.subref[1] } : null,
  }));
  F.analyze(lines);

  const out = [];
  premises.forEach((p, i) => {
    const line = lines[i];
    if (!line || line.rule !== "premise" || line.depth || !F.same(line.formula, p)) {
      out.push("line " + (i + 1) + " should be the premise " + F.show(p));
    }
  });
  lines.forEach((line, i) => {
    if (line.rule === "premise") return;
    const result = F.checkLine(line, lines, premises, language);
    if (!result.ok) out.push("line " + (i + 1) + ": " + result.msg);
  });
  const last = lines[lines.length - 1];
  if (!last || last.depth || !F.same(last.formula, goal)) {
    out.push("the proof does not end on the goal " + F.show(goal));
  }
  return out;
}

const file = process.argv[2] || path.join(__dirname, "ch15_questions.json");
const bank = JSON.parse(fs.readFileSync(file, "utf8"));
let failed = false;
bank.forEach((question, i) => {
  let found;
  try { found = problems(question); }
  catch (e) { found = ["could not be read: " + e.message]; }
  found.forEach((msg) => { failed = true; console.log((i + 1) + ": " + msg); });
});
process.exit(failed ? 1 : 0);
