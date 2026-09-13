"""A Fitch proof checker for the Relational Logic system of Chapter 10.

fitch_checker.py covers Chapter 5: propositional formulas and eleven rules. This
module is its relational counterpart. It parses the language of Chapter 10 —
relation constants applied to terms, and the quantifiers ∀ and ∃ — and applies
the same eleven rules plus the five the chapter adds: Universal Elimination,
Universal Introduction, Existential Introduction, Existential Elimination, and
Domain Closure, each with the restriction the chapter places on it.

Relational Logic has no truth table, so there is no countermodel search here and
no `entails`. What there is instead is enough: the Fitch system is sound, so a
proof every line of which passes this checker is a proof, and its conclusion is
entailed by its premises. Validity is established by the proof, not checked
alongside it.

The public surface mirrors fitch_checker:

    parse(src)                   -> AST, or raise FormulaError
    show(ast)                    -> canonical string with minimal parentheses
    check_proof(premises, goal, steps, constants=None) -> list of problems
    difficulty(steps)            -> "easy" | "medium" | "hard"
    render_proof(steps)          -> the proof as indented text

A step is a dict, as in fitch_checker:

    {"formula": "∀x.p(x)", "rule": "ui", "depth": 0,
     "refs": [3],             # 1-based line numbers
     "subref": [4, 6]}        # 1-based [assumption, conclusion], for "ii" only
"""

import re

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
    "ue": "Universal Elimination",
    "ui": "Universal Introduction",
    "ei": "Existential Introduction",
    "ee": "Existential Elimination",
    "dc": "Domain Closure",
}

QUANTIFIER_RULES = ("ue", "ui", "ei", "ee", "dc")

NOT, AND, OR, IMP, IFF = "¬", "∧", "∨", "⇒", "⇔"
ALL, EXISTS = "∀", "∃"

# The browser editor writes quantifiers the way the Stanford tool does — AX: p(X)
# for every X, EX: p(X) for some X, variables uppercase. Accepting that spelling
# here is what lets a proof built in the editor be checked by this module.
_QUANT = re.compile(r"(?:([AE])([A-Z][A-Za-z0-9_]*)|([∀∃])\s*([A-Za-z][A-Za-z0-9_]*))\s*[:.]")

# The chapter's variables are the tail of the alphabet; everything else that
# appears without a quantifier over it is an object constant or a placeholder.
VARIABLE_LETTERS = set("uvwxyz")


class FormulaError(ValueError):
    """A formula that does not parse under the chapter's grammar."""


# --- formulas ---------------------------------------------------------------
#
# ASTs are tuples, so `==` is structural identity.
#
#   ("rel", name, (term, ...))          p, p(x), loves(jack, y)
#   ("not", x) | ("and"|"or", (args,))  | ("imp"|"iff", a, b)
#   ("all"|"exists", var, body)
#
# and a term is ("t", name, (term, ...)) — zero arguments for a constant, a
# placeholder, or a variable.

_PUNCT = {NOT, AND, OR, IMP, IFF, ALL, EXISTS, "(", ")", ",", "."}
_ALIASES = {
    "~": NOT, "!": NOT, "-": NOT,
    "&": AND, "^": AND,
    "|": OR, "+": OR,
    "→": IMP, "⊃": IMP,
    "↔": IFF, "≡": IFF,
    "@": ALL, "#": EXISTS,
}
_MULTI = [("<=>", IFF), ("<->", IFF), ("=>", IMP), ("->", IMP),
          ("/\\", AND), ("&&", AND), ("\\/", OR), ("||", OR),
          ("forall", ALL), ("exists", EXISTS)]


def _tokenize(src):
    tokens, i = [], 0
    while i < len(src):
        if src[i].isspace():
            i += 1
            continue
        quant = _QUANT.match(src, i)
        if quant:
            sign = quant.group(1) or quant.group(3)
            var = quant.group(2) or quant.group(4)
            tokens.append(ALL if sign in ("A", ALL) else EXISTS)
            tokens.append(("name", var))
            tokens.append(".")
            i = quant.end()
            continue
        for text, op in _MULTI:  # longest match first
            if src.startswith(text, i):
                tokens.append(op)
                i += len(text)
                break
        else:
            ch = src[i]
            if ch in _PUNCT:
                tokens.append(ch)
            elif ch in _ALIASES:
                tokens.append(_ALIASES[ch])
            elif ch.isalpha() or ch == "_":
                name = ""
                while i < len(src) and (src[i].isalnum() or src[i] == "_"):
                    name += src[i]
                    i += 1
                tokens.append(("name", name))
                continue
            else:
                raise FormulaError(f'unexpected character "{ch}"')
            i += 1
    return tokens


def parse(src):
    """Parse `src` under the grammar of Chapter 10.

    A quantifier is a prefix binding as tightly as ¬, so ∀x.p(x) ∧ ∀x.q(x) is a
    conjunction of two quantified sentences, exactly as the chapter writes it,
    and a wider scope is written with parentheses: ∀x.(p(x) ∧ q(x)).
    """
    tokens = _tokenize(src)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def expect(tok, what):
        nonlocal pos
        if peek() != tok:
            raise FormulaError(f"expected {what}")
        pos += 1

    def arguments():
        """Parse ( t, t, ... ) after a name, or return None if there is none."""
        nonlocal pos
        if peek() != "(":
            return None
        pos += 1
        args = [term()]
        while peek() == ",":
            pos += 1
            args.append(term())
        expect(")", ")")
        return tuple(args)

    def term():
        nonlocal pos
        tok = peek()
        if not (isinstance(tok, tuple) and tok[0] == "name"):
            raise FormulaError("expected a term")
        pos += 1
        return ("t", tok[1], arguments() or ())

    def unary():
        nonlocal pos
        tok = peek()
        if tok is None:
            raise FormulaError("the formula ends too early")
        if tok == NOT:
            pos += 1
            return ("not", unary())
        if tok in (ALL, EXISTS):
            pos += 1
            var = peek()
            if not (isinstance(var, tuple) and var[0] == "name"):
                raise FormulaError(f"{tok} must be followed by a variable")
            pos += 1
            if peek() == ".":
                pos += 1
            return ("all" if tok == ALL else "exists", var[1], unary())
        if tok == "(":
            pos += 1
            node = iff()
            expect(")", ")")
            return node
        if isinstance(tok, tuple) and tok[0] == "name":
            pos += 1
            return ("rel", tok[1], arguments() or ())
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


_PREC = {"rel": 5, "not": 4, "all": 4, "exists": 4,
         "and": 3, "or": 2, "imp": 1, "iff": 0}


def show_term(term):
    name, args = term[1], term[2]
    if not args:
        return name
    return f"{name}({','.join(show_term(a) for a in args)})"


def show(node, parent_prec=-1):
    """Render a formula with the fewest parentheses that keep it unambiguous."""
    kind = node[0]
    if kind == "rel":
        name, args = node[1], node[2]
        return name if not args else \
            f"{name}({','.join(show_term(a) for a in args)})"
    if kind == "not":
        return NOT + show(node[1], _PREC["not"])
    if kind in ("all", "exists"):
        sign = ALL if kind == "all" else EXISTS
        out = f"{sign}{node[1]}.{show(node[2], _PREC[kind])}"
        return f"({out})" if _PREC[kind] < parent_prec else out
    prec = _PREC[kind]
    if kind in ("and", "or"):
        glue = f" {AND if kind == 'and' else OR} "
        out = glue.join(show(a, prec) for a in node[1])
    elif kind == "imp":
        out = f"{show(node[1], prec + 0.5)} {IMP} {show(node[2], prec)}"
    else:
        out = f"{show(node[1], prec + 0.5)} {IFF} {show(node[2], prec + 0.5)}"
    return f"({out})" if prec < parent_prec else out


def _not(node):
    return ("not", node)


# --- names, substitution, matching ------------------------------------------

def term_names(term, out=None):
    """Every name occurring in a term, including function names."""
    out = set() if out is None else out
    out.add(term[1])
    for arg in term[2]:
        term_names(arg, out)
    return out


def free_names(node, bound=frozenset(), out=None):
    """Names occurring in `node` outside the scope of a quantifier binding them.

    Object constants and placeholders are free by this definition; a variable
    under its own quantifier is not.
    """
    out = set() if out is None else out
    kind = node[0]
    if kind == "rel":
        for arg in node[2]:
            for name in term_names(arg):
                if name not in bound:
                    out.add(name)
    elif kind in ("all", "exists"):
        free_names(node[2], bound | {node[1]}, out)
    elif kind == "not":
        free_names(node[1], bound, out)
    elif kind in ("and", "or"):
        for arg in node[1]:
            free_names(arg, bound, out)
    else:
        free_names(node[1], bound, out)
        free_names(node[2], bound, out)
    return out


def _looks_like_variable(name):
    """Both conventions at once: the chapter's lowercase x, y, z and the
    editor's uppercase X, Y, Z."""
    return name[:1].isupper() or (len(name) == 1 and name in VARIABLE_LETTERS)


def open_variables(node):
    """Free names that look like variables — the mark of an open sentence."""
    return {n for n in free_names(node) if _looks_like_variable(n)}


class CaptureError(ValueError):
    """A substitution that would put a term under a quantifier binding it."""


def _subst_term(term, name, value):
    if term[1] == name and not term[2]:
        return value
    return ("t", term[1], tuple(_subst_term(a, name, value) for a in term[2]))


def subst(node, name, value, bound=frozenset()):
    """Replace free occurrences of the 0-ary term `name` by the term `value`.

    Raises CaptureError if a quantifier along the way binds a name that `value`
    carries, since the result would say something else entirely.
    """
    kind = node[0]
    if kind == "rel":
        return ("rel", node[1],
                tuple(_subst_term(a, name, value) for a in node[2]))
    if kind in ("all", "exists"):
        if node[1] == name:
            return node                      # shadowed: nothing free to replace
        if node[1] in term_names(value) and name in free_names(node[2], {node[1]}):
            raise CaptureError(f"{show_term(value)} would be captured by "
                               f"{node[1]}")
        return (kind, node[1], subst(node[2], name, value, bound | {node[1]}))
    if kind == "not":
        return ("not", subst(node[1], name, value, bound))
    if kind in ("and", "or"):
        return (kind, tuple(subst(a, name, value, bound) for a in node[1]))
    return (kind, subst(node[1], name, value, bound),
            subst(node[2], name, value, bound))


def match(pattern, target, var):
    """Find the term that `var` stands for, turning `pattern` into `target`.

    Returns the term, or None when `var` does not occur free in `pattern` and
    the two sides are already identical. Raises ValueError when no single term
    works, which is the usual way a bad Universal Elimination is caught.
    """
    found = []

    def walk_term(p, t, bound):
        if p[1] == var and not p[2] and var not in bound:
            found.append(t)
            return
        if p[1] != t[1] or len(p[2]) != len(t[2]):
            raise ValueError(f"{show_term(p)} does not line up with "
                             f"{show_term(t)}")
        for a, b in zip(p[2], t[2]):
            walk_term(a, b, bound)

    def walk(p, t, bound):
        if p[0] != t[0]:
            raise ValueError(f"{show(p)} does not line up with {show(t)}")
        if p[0] == "rel":
            if p[1] != t[1] or len(p[2]) != len(t[2]):
                raise ValueError(f"{show(p)} does not line up with {show(t)}")
            for a, b in zip(p[2], t[2]):
                walk_term(a, b, bound)
        elif p[0] in ("all", "exists"):
            if p[1] != t[1]:
                raise ValueError(f"{show(p)} binds {p[1]}, {show(t)} binds "
                                 f"{t[1]}")
            walk(p[2], t[2], bound | {p[1]})
        elif p[0] == "not":
            walk(p[1], t[1], bound)
        elif p[0] in ("and", "or"):
            if len(p[1]) != len(t[1]):
                raise ValueError(f"{show(p)} does not line up with {show(t)}")
            for a, b in zip(p[1], t[1]):
                walk(a, b, bound)
        else:
            walk(p[1], t[1], bound)
            walk(p[2], t[2], bound)

    walk(pattern, target, frozenset())
    if not found:
        return None
    first = found[0]
    if any(other != first for other in found[1:]):
        raise ValueError(f"{var} would have to stand for two different terms")
    return first


def _instance_of(body, var, target):
    """The term `var` takes to make `body` into `target`, or raise ValueError."""
    term = match(body, target, var)
    if term is None:
        if body != target:
            raise ValueError(f"{show(body)} is not {show(target)}")
        return None
    try:
        if subst(body, var, term) != target:
            raise ValueError(f"substituting {show_term(term)} for {var} in "
                             f"{show(body)} does not give {show(target)}")
    except CaptureError as exc:
        raise ValueError(str(exc)) from exc
    return term


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
    """Tag every line with its subproof, and that subproof's ancestors."""
    root = {"id": 0, "parent": None, "depth": 0, "start": 0,
            "end": len(lines) - 1, "chain": {0}, "assumption": None}
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
                     "chain": parent["chain"] | {next_id},
                     "assumption": line.formula}
            next_id += 1
            stack.append(block)
        line.block = stack[-1]
    while len(stack) > 1:
        stack[-1]["end"] = len(lines) - 1
        stack.pop()
    return errors


def _open_names(line, premise_nodes):
    """Names that are not arbitrary at `line`: the premises' and the open
    assumptions'. Universal Introduction may not generalize any of them."""
    names = set()
    for node in premise_nodes:
        names |= free_names(node)
    block = line.block
    while block is not None:
        if block["assumption"] is not None:
            names |= free_names(block["assumption"])
        block = block["parent"]
    return names


def _check_quantifier_rule(line, cited, premise_nodes, constants):
    f, rule = line.formula, line.rule

    if rule == "ue":
        if len(cited) != 1 or cited[0][0] != "all":
            return "Universal Elimination cites one universally quantified line"
        var, body = cited[0][1], cited[0][2]
        try:
            term = _instance_of(body, var, f)
        except ValueError as exc:
            return f"this is not an instance of {show(cited[0])}: {exc}"
        if term is not None and term[1] in _bound_anywhere(body):
            return (f"{show_term(term)} is not a ground term here")
        return None

    if rule == "ui":
        if f[0] != "all":
            return "Universal Introduction concludes a universally quantified line"
        if len(cited) != 1:
            return "Universal Introduction cites one line"
        var, body = f[1], f[2]
        try:
            term = _instance_of(body, var, cited[0])
        except ValueError as exc:
            return f"{show(cited[0])} is not an instance of {show(f)}: {exc}"
        if term is None:
            return None                       # vacuous generalization
        if term[2]:
            return (f"Universal Introduction generalizes a placeholder, not the "
                    f"compound term {show_term(term)}")
        blocked = _open_names(line, premise_nodes)
        if term[1] in blocked:
            return (f"{term[1]} is not arbitrary here — it occurs in a premise "
                    f"or in an assumption that is still open")
        return None

    if rule == "ei":
        if f[0] != "exists":
            return "Existential Introduction concludes an existentially " \
                   "quantified line"
        if len(cited) != 1:
            return "Existential Introduction cites one line"
        var, body = f[1], f[2]
        try:
            term = _instance_of(body, var, cited[0])
        except ValueError as exc:
            return f"{show(cited[0])} is not an instance of {show(f)}: {exc}"
        if term is not None and term[1] in _bound_anywhere(body):
            return f"{show_term(term)} is not a ground term here"
        return None

    if rule == "ee":
        if len(cited) != 2:
            return "Existential Elimination cites an existential and a " \
                   "universally quantified implication"
        for existential, universal in (cited, cited[::-1]):
            if existential[0] != "exists" or universal[0] != "all":
                continue
            var, scope = existential[1], existential[2]
            uvar, imp_node = universal[1], universal[2]
            if imp_node[0] != "imp":
                continue
            try:
                antecedent = subst(imp_node[1], uvar, ("t", var, ()))
            except CaptureError:
                continue
            if antecedent != scope:
                continue
            if imp_node[2] != f:
                return (f"the implication concludes {show(imp_node[2])}, not "
                        f"{show(f)}")
            if uvar in free_names(imp_node[2]) or var in free_names(f):
                return (f"{uvar} occurs free in the conclusion, which "
                        f"Existential Elimination does not allow")
            return None
        return (f"the cited lines are not ∃{'ν'}.φ and ∀ν.(φ ⇒ ψ) with the same "
                f"φ")

    if rule == "dc":
        if f[0] != "all":
            return "Domain Closure concludes a universally quantified line"
        if not constants:
            return ("Domain Closure applies only when the exercise fixes the "
                    "object constants of the language")
        var, body = f[1], f[2]
        needed = {}
        for name in constants:
            try:
                needed[name] = subst(body, var, ("t", name, ()))
            except CaptureError as exc:
                return str(exc)
        missing = [show(inst) for inst in needed.values() if inst not in cited]
        if missing:
            return f"no line gives the instance {missing[0]}"
        extra = [show(c) for c in cited if c not in needed.values()]
        if extra:
            return f"{extra[0]} is not an instance over {', '.join(constants)}"
        return None

    return f"unknown rule {rule!r}"


def _bound_anywhere(node, out=None):
    """Every variable a quantifier binds inside `node`."""
    out = set() if out is None else out
    kind = node[0]
    if kind in ("all", "exists"):
        out.add(node[1])
        _bound_anywhere(node[2], out)
    elif kind == "not":
        _bound_anywhere(node[1], out)
    elif kind in ("and", "or"):
        for arg in node[1]:
            _bound_anywhere(arg, out)
    elif kind != "rel":
        _bound_anywhere(node[1], out)
        _bound_anywhere(node[2], out)
    return out


def _check_rule(line, cited, sub, premise_nodes, constants):
    """Return an error message for one line, or None."""
    f, rule = line.formula, line.rule

    if rule == "assume":
        return None

    if rule in QUANTIFIER_RULES:
        return _check_quantifier_rule(line, cited, premise_nodes, constants)

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
        if line.refs[0] == line.refs[1]:
            return "the two implications have to be different lines"
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
        both = {("imp", cited[0][1], cited[0][2]),
                ("imp", cited[0][2], cited[0][1])}
        if f not in both:
            return "that is not one direction of the cited biconditional"
        return None

    return f"unknown rule {rule!r}"


def check_proof(premises, goal, steps, constants=None):
    """Validate a whole proof. Returns [] when it is correct.

    `premises` and `goal` are formula strings, `steps` the list of line dicts,
    and `constants` the object constants the exercise restricts the language to
    — needed only by Domain Closure.
    """
    problems = []
    if not steps:
        return ["the proof is empty"]
    constants = list(constants or [])

    try:
        premise_nodes = [parse(p) for p in premises]
        goal_node = parse(goal)
    except FormulaError as exc:
        return [f"the problem itself does not parse: {exc}"]

    for label, node in [("the goal", goal_node)] + \
            [(f"premise {show(p)}", p) for p in premise_nodes]:
        loose = open_variables(node)
        if loose:
            problems.append(f"{label} is not a closed sentence: "
                            f"{', '.join(sorted(loose))} is free")
    if problems:
        return problems

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
                problems.append(f"line {n}: cites line {ref}, which does not "
                                f"exist")
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
                problems.append(f"line {n}: lines {start}-{end} are not one "
                                f"subproof")
                continue
            if block["end"] >= line.index or \
                    block["parent"]["id"] not in line.block["chain"]:
                problems.append(f"line {n}: subproof {start}-{end} is not in "
                                f"scope here")
                continue
            sub = (head.formula, tail.formula)

        if line.rule == "premise":
            if line.depth != 0:
                problems.append(f"line {n}: premises belong at the outermost "
                                f"level")
            elif line.formula not in premise_nodes:
                problems.append(f"line {n}: {show(line.formula)} is not one of "
                                f"the premises")
            continue

        try:
            message = _check_rule(line, cited, sub, premise_nodes, constants)
        except (ValueError, IndexError, TypeError) as exc:
            message = f"the rule does not apply ({exc})"
        if message:
            problems.append(f"line {n} ({RULES[line.rule]}): {message}")

    last = lines[-1]
    if last.depth != 0:
        problems.append("the proof has to end at the outermost level, not "
                        "inside a subproof")
    if last.formula != goal_node:
        problems.append(f"the last line is {show(last.formula)}, not the goal "
                        f"{show(goal_node)}")

    used = {ln.formula for ln in lines if ln.rule == "premise"}
    for node in premise_nodes:
        if node not in used:
            problems.append(f"premise {show(node)} is never stated as a line")

    return problems


# --- difficulty and rendering -----------------------------------------------

EASY_MAX = 9
MEDIUM_MAX = 19

DIFFICULTIES = ("easy", "medium", "hard")

TARGET_LINES = {
    "easy": "at most 9 lines",
    "medium": "between 10 and 19 lines",
    "hard": "20 lines or more",
}


def difficulty(steps):
    """Band a problem by the length of its proof."""
    n = len(steps)
    if n <= EASY_MAX:
        return "easy"
    if n <= MEDIUM_MAX:
        return "medium"
    return "hard"


def render_proof(steps):
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
        out.append(f"{str(i).rjust(width)}. {bars}{formula}".ljust(52) + label)
    return "\n".join(out)
