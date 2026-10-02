"""A Fitch proof checker, kept in step with the browser checker in static/fitch.js.

The browser is where students build proofs, and it can only validate what is in
front of it. This module is the server-side counterpart: it parses formulas with
the same grammar, applies the same eleven rules with the same scope rules, and
so accepts exactly the proofs the editor accepts. That lets the app store a
model-written proof only after confirming a student could really have built it.

The public surface is:

    parse(src)                    -> AST, or raise FormulaError
    show(ast)                     -> canonical string with minimal parentheses
    check_proof(premises, goal, steps)  -> list of human-readable problems
    difficulty(steps)             -> "easy" | "medium" | "hard"
    entails(premises, goal)       -> True if the argument is valid at all

A proof is a list of steps, each a dict:

    {"formula": "p ⇒ q", "rule": "ii", "depth": 1,
     "refs": [2, 3],          # 1-based line numbers
     "subref": [4, 6]}        # 1-based [assumption, conclusion], for "ii" only
"""

import itertools

# Rule ids and labels, matching the RULES table in static/fitch.js.
RULES = {
    "premise": "Premise",
    "assume": "Assumption",
    "reit": "Reiteration",
    "ai": "And Introduction",
    "ae": "And Elimination",
    "oi": "Or Introduction",
    "oe": "Or Elimination",
    "ni": "Negation Introduction",
    "ne": "Negation Elimination",
    "ii": "Implication Introduction",
    "ie": "Implication Elimination",
    "bi": "Biconditional Introduction",
    "be": "Biconditional Elimination",
}

NOT, AND, OR, IMP, IFF = "¬", "∧", "∨", "⇒", "⇔"


class FormulaError(ValueError):
    """A formula that does not parse under the chapter's grammar."""


# --- formulas ---------------------------------------------------------------
#
# ASTs are tuples so they hash and compare structurally, which makes `==` the
# same test as the key()/same() pair in the browser checker.
#
#   ("atom", name) | ("not", x) | ("and"|"or", (args...)) | ("imp"|"iff", a, b)

_OPS = {NOT, AND, OR, IMP, IFF, "(", ")"}
# The browser tokenizer accepts several spellings per connective; mirror it so a
# formula typed into the editor and one written by the model normalise alike.
_ALIASES = {
    "~": NOT, "!": NOT, "-": NOT,
    "&": AND, "^": AND,
    "|": OR, "+": OR,
    "→": IMP, "⊃": IMP,
    "↔": IFF, "≡": IFF,
}
_MULTI = [("<=>", IFF), ("<->", IFF), ("=>", IMP), ("->", IMP),
          ("/\\", AND), ("&&", AND), ("\\/", OR), ("||", OR)]


def _tokenize(src):
    tokens, i = [], 0
    while i < len(src):
        if src[i].isspace():
            i += 1
            continue
        for text, op in _MULTI:  # longest match first, so "<=>" never reads as "<"
            if src.startswith(text, i):
                tokens.append(op)
                i += len(text)
                break
        else:
            ch = src[i]
            if ch in _OPS:
                tokens.append(ch)
            elif ch in _ALIASES:
                tokens.append(_ALIASES[ch])
            elif ch.isalpha():
                name = ""
                while i < len(src) and (src[i].isalnum() or src[i] == "_"):
                    name += src[i]
                    i += 1
                tokens.append(("atom", name))
                continue
            else:
                raise FormulaError(f'unexpected character "{ch}"')
            i += 1
    return tokens


def parse(src):
    """Parse `src` under the grammar in static/fitch.js.

    ∧ and ∨ flatten into n-ary nodes at the same parenthesis level, ⇒ is right
    associative, and ⇔ does not chain — all as in the browser.
    """
    tokens = _tokenize(src)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def unary():
        nonlocal pos
        tok = peek()
        if tok is None:
            raise FormulaError("the formula ends too early")
        if tok == NOT:
            pos += 1
            return ("not", unary())
        if tok == "(":
            pos += 1
            node = iff()
            if peek() != ")":
                raise FormulaError("missing )")
            pos += 1
            return node
        if isinstance(tok, tuple):
            pos += 1
            return tok
        raise FormulaError(f'unexpected "{tok}"')

    def nary(op, below, tag):
        nonlocal pos
        args = [below()]
        while peek() == op:
            pos += 1
            args.append(below())
        return args[0] if len(args) == 1 else (tag, tuple(args))

    def conj():
        return nary(AND, unary, "and")

    def disj():
        return nary(OR, conj, "or")

    def imp():
        nonlocal pos
        node = disj()
        if peek() == IMP:
            pos += 1
            return ("imp", node, imp())  # right associative
        return node

    def iff():
        nonlocal pos
        node = imp()
        if peek() == IFF:
            pos += 1
            return ("iff", node, imp())  # not chainable
        return node

    node = iff()
    if pos < len(tokens):
        raise FormulaError("unexpected text after the formula")
    return node


_PREC = {"atom": 5, "not": 4, "and": 3, "or": 2, "imp": 1, "iff": 0}


def show(node, parent_prec=-1):
    """Render a formula with the fewest parentheses that keep it unambiguous."""
    kind = node[0]
    if kind == "atom":
        return node[1]
    if kind == "not":
        return NOT + show(node[1], _PREC["not"])
    prec = _PREC[kind]
    if kind in ("and", "or"):
        glue = f" {AND if kind == 'and' else OR} "
        out = glue.join(show(a, prec) for a in node[1])
    elif kind == "imp":
        # Right associative, so the left side needs parens at equal precedence.
        out = f"{show(node[1], prec + 0.5)} {IMP} {show(node[2], prec)}"
    else:
        out = f"{show(node[1], prec + 0.5)} {IFF} {show(node[2], prec + 0.5)}"
    return f"({out})" if prec < parent_prec else out


def show_statement(node):
    """Render a formula for an exercise statement, not for a proof line.

    show() drops every parenthesis precedence allows, which is right inside a
    proof where the reader is already tracking the connectives. In the statement
    of a problem the chapter is more generous, writing (p ⇒ (q ⇒ r)) rather than
    p ⇒ q ⇒ r, so here the operands of ⇒ and ⇔ keep their brackets whenever they
    are compound.
    """
    kind = node[0]
    if kind == "atom":
        return node[1]
    if kind == "not":
        inner = node[1]
        body = show_statement(inner)
        return NOT + (body if inner[0] in ("atom", "not") else f"({body})")
    if kind in ("and", "or"):
        glue = f" {AND if kind == 'and' else OR} "
        prec = _PREC[kind]
        parts = []
        for arg in node[1]:
            text = show_statement(arg)
            parts.append(f"({text})" if _PREC[arg[0]] < prec else text)
        return glue.join(parts)

    def side(arg):
        text = show_statement(arg)
        return text if arg[0] in ("atom", "not") else f"({text})"

    op = IMP if kind == "imp" else IFF
    return f"{side(node[1])} {op} {side(node[2])}"


def _not(node):
    return ("not", node)


# --- semantics --------------------------------------------------------------

def atoms(node):
    if node[0] == "atom":
        return {node[1]}
    if node[0] in ("and", "or"):
        return set().union(*(atoms(a) for a in node[1]))
    return set().union(*(atoms(a) for a in node[1:]))


def _value(node, world):
    kind = node[0]
    if kind == "atom":
        return world[node[1]]
    if kind == "not":
        return not _value(node[1], world)
    if kind == "and":
        return all(_value(a, world) for a in node[1])
    if kind == "or":
        return any(_value(a, world) for a in node[1])
    left, right = _value(node[1], world), _value(node[2], world)
    return (not left) or right if kind == "imp" else left == right


def countermodel(premises, goal):
    """A world where every premise holds and the goal fails, or None.

    Fitch is sound and complete for propositional logic, so "no countermodel"
    is exactly "provable in this system".
    """
    names = sorted(set().union(*(atoms(n) for n in list(premises) + [goal])))
    for bits in itertools.product([False, True], repeat=len(names)):
        world = dict(zip(names, bits))
        if all(_value(p, world) for p in premises) and not _value(goal, world):
            return world
    return None


def entails(premises, goal):
    return countermodel(premises, goal) is None


# --- proofs -----------------------------------------------------------------

class _Line:
    def __init__(self, index, step):
        self.index = index
        self.depth = int(step.get("depth", 0))
        self.rule = step.get("rule")
        self.refs = [int(r) for r in (step.get("refs") or [])]
        sub = step.get("subref")
        self.subref = (int(sub[0]), int(sub[1])) if sub else None
        self.formula = parse(step["formula"])
        self.block = None


def _blocks(lines):
    """Tag every line with the block it lives in, plus that block's ancestors.

    A block is a subproof. `chain` is the set of block ids visible from inside
    it, which is exactly what citation scope needs.
    """
    root = {"id": 0, "parent": None, "depth": 0, "start": 0,
            "end": len(lines) - 1, "chain": {0}}
    stack, next_id, errors = [root], 1, []
    for i, line in enumerate(lines):
        while line.depth < stack[-1]["depth"]:
            stack[-1]["end"] = i - 1
            stack.pop()
        if line.depth > stack[-1]["depth"]:
            if line.rule != "assume":
                errors.append(f"line {i + 1}: an indented block has to start "
                              f"with an assumption")
            if line.depth > stack[-1]["depth"] + 1:
                errors.append(f"line {i + 1}: indentation jumps by more than one")
            parent = stack[-1]
            block = {"id": next_id, "parent": parent, "depth": line.depth,
                     "start": i, "end": len(lines) - 1,
                     "chain": parent["chain"] | {next_id}}
            next_id += 1
            stack.append(block)
        line.block = stack[-1]
    while len(stack) > 1:
        stack[-1]["end"] = len(lines) - 1
        stack.pop()
    return errors


def _check_rule(line, cited, sub):
    """Return an error message for one line, or None. Mirrors checkLine()."""
    f, rule = line.formula, line.rule

    if rule == "assume":
        return None

    if rule == "reit":
        if len(cited) != 1 or cited[0] != f:
            return "Reiteration repeats one line exactly"
        return None

    if rule == "ai":
        if f[0] != "and" or len(f[1]) != len(cited) or any(
                a != c for a, c in zip(f[1], cited)):
            return "the conjuncts do not match the cited lines"
        return None

    if rule == "ae":
        if len(cited) != 1 or cited[0][0] != "and" or f not in cited[0][1]:
            return "this is not a conjunct of the cited line"
        return None

    if rule == "oi":
        if len(cited) != 1 or f[0] != "or" or cited[0] not in f[1]:
            return "the cited line is not one of these disjuncts"
        return None

    if rule == "oe":
        if len(cited) < 3 or cited[0][0] != "or":
            return "Or Elimination cites a disjunction and one case per disjunct"
        pool = list(cited[1:])
        for disjunct in cited[0][1]:
            hit = next((i for i, c in enumerate(pool)
                        if c[0] == "imp" and c[1] == disjunct and c[2] == f), None)
            if hit is None:
                return f"no case proves {show(f)} from {show(disjunct)}"
            pool.pop(hit)
        if pool:
            return "there are more cases cited than disjuncts"
        return None

    if rule == "ni":
        if len(cited) != 2 or f[0] != "not":
            return "Negation Introduction needs two implications"
        x, y = cited

        def clash(p, q):
            return (p[0] == "imp" and q[0] == "imp"
                    and p[1] == f[1] and q[1] == f[1]
                    and (q[2] == _not(p[2]) or p[2] == _not(q[2])))

        if not clash(x, y) and not clash(y, x):
            return "the cited implications do not contradict"
        return None

    if rule == "ne":
        if len(cited) != 1 or cited[0][0] != "not" or cited[0][1][0] != "not" \
                or cited[0][1][1] != f:
            return "Negation Elimination needs a double negation"
        return None

    if rule == "ii":
        if sub is None or cited:
            return "Implication Introduction cites one subproof"
        if f[0] != "imp" or sub[0] != f[1] or sub[1] != f[2]:
            return (f"that subproof discharges to "
                    f"{show(('imp', sub[0], sub[1]))}")
        return None

    if rule == "ie":
        if len(cited) != 2:
            return "Implication Elimination cites two lines"
        x, y = cited

        def fires(imp_node, antecedent):
            return (imp_node[0] == "imp" and imp_node[1] == antecedent
                    and imp_node[2] == f)

        if not fires(x, y) and not fires(y, x):
            return "the cited lines do not yield this"
        return None

    if rule == "bi":
        if len(cited) != 2 or f[0] != "iff":
            return "Biconditional Introduction needs two implications"
        forward, backward = ("imp", f[1], f[2]), ("imp", f[2], f[1])
        if set(cited) != {forward, backward}:
            return "the cited implications do not run both ways"
        return None

    if rule == "be":
        if len(cited) != 1 or cited[0][0] != "iff":
            return "Biconditional Elimination needs a biconditional"
        both = {("imp", cited[0][1], cited[0][2]), ("imp", cited[0][2], cited[0][1])}
        if f not in both:
            return "that is not one direction of the cited biconditional"
        return None

    return f"unknown rule {rule!r}"


def check_proof(premises, goal, steps):
    """Validate a whole proof. Returns [] when it is correct.

    `premises` and `goal` are formula strings; `steps` is the list described in
    the module docstring. Every message names a line so the model can be told
    what to repair.
    """
    problems = []
    if not steps:
        return ["the proof is empty"]

    try:
        premise_nodes = [parse(p) for p in premises]
        goal_node = parse(goal)
    except FormulaError as exc:
        return [f"the problem itself does not parse: {exc}"]

    lines = []
    for i, step in enumerate(steps):
        try:
            lines.append(_Line(i, step))
        except FormulaError as exc:
            problems.append(f"line {i + 1}: {exc}")
        except (KeyError, TypeError, IndexError, ValueError) as exc:
            problems.append(f"line {i + 1}: malformed step ({exc})")
    if problems:
        return problems

    problems.extend(_blocks(lines))

    for line in lines:
        n = line.index + 1
        if line.rule not in RULES:
            problems.append(f"line {n}: unknown rule {line.rule!r}")
            continue

        cited, bad = [], False
        for ref in line.refs:
            if not 1 <= ref <= len(lines):
                problems.append(f"line {n}: cites line {ref}, which does not exist")
                bad = True
                break
            target = lines[ref - 1]
            if target.index >= line.index:
                problems.append(f"line {n}: cites line {ref}, which comes later")
                bad = True
                break
            if target.block["id"] not in line.block["chain"]:
                problems.append(f"line {n}: line {ref} sits in a subproof that "
                                f"has already closed")
                bad = True
                break
            cited.append(target.formula)
        if bad:
            continue

        sub = None
        if line.subref:
            start, end = line.subref
            if not (1 <= start <= len(lines) and 1 <= end <= len(lines)):
                problems.append(f"line {n}: cites a subproof that does not exist")
                continue
            head, tail = lines[start - 1], lines[end - 1]
            block = head.block
            if block["id"] == 0 or block["start"] != head.index \
                    or tail.block["id"] != block["id"] or tail.index < head.index:
                problems.append(f"line {n}: lines {start}-{end} are not one subproof")
                continue
            if block["end"] >= line.index or block["parent"]["id"] not in line.block["chain"]:
                problems.append(f"line {n}: subproof {start}-{end} is not in scope here")
                continue
            sub = (head.formula, tail.formula)

        if line.rule == "premise":
            if line.depth != 0:
                problems.append(f"line {n}: premises belong at the outermost level")
            elif line.formula not in premise_nodes:
                problems.append(f"line {n}: {show(line.formula)} is not one of "
                                f"the premises")
            continue

        message = _check_rule(line, cited, sub)
        if message:
            problems.append(f"line {n} ({RULES[line.rule]}): {message}")

    last = lines[-1]
    if last.depth != 0:
        problems.append("the proof has to end at the outermost level, not inside "
                        "a subproof")
    if last.formula != goal_node:
        problems.append(f"the last line is {show(last.formula)}, not the goal "
                        f"{show(goal_node)}")

    # Every premise should actually be stated; a proof that silently skips one
    # is still valid, but it means the problem was easier than advertised.
    used = {ln.formula for ln in lines if ln.rule == "premise"}
    for node in premise_nodes:
        if node not in used:
            problems.append(f"premise {show(node)} is never stated as a line")

    return problems


# --- difficulty -------------------------------------------------------------

EASY_MAX = 8        # at most 8 lines
MEDIUM_MAX = 16     # at most 16 lines


def difficulty(steps):
    """Band a problem by the length of its proof."""
    n = len(steps)
    if n <= EASY_MAX:
        return "easy"
    if n <= MEDIUM_MAX:
        return "medium"
    return "hard"


DIFFICULTIES = ("easy", "medium", "hard")

TARGET_LINES = {
    "easy": "at most 8 lines",
    "medium": "between 9 and 16 lines",
    "hard": "17 lines or more",
}


def render_proof(steps, premises=None, goal=None):
    """Format a proof as indented text, the way the chapter prints one."""
    width = len(str(len(steps)))
    out = []
    for i, step in enumerate(steps, 1):
        bars = "│ " * int(step.get("depth", 0))
        refs = step.get("refs") or []
        sub = step.get("subref")
        label = RULES.get(step.get("rule"), step.get("rule"))
        if sub:
            label += f": {sub[0]}-{sub[1]}"
        elif refs:
            label += ": " + ", ".join(str(r) for r in refs)
        formula = show(parse(step["formula"]))
        out.append(f"{str(i).rjust(width)}. {bars}{formula}".ljust(46) + label)
    return "\n".join(out)
