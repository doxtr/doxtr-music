"""Safe expression evaluator for ``song-list`` filtering (no ``eval``).

This module is **the** sanctioned expression-evaluation authority for the
extension (LOCKED, CHUNK-5-2). ``song-list``'s ``:filter:`` and any
``song-index`` ``:group-by:`` key-expression route through :func:`safe_eval`;
no other chunk re-implements expression parsing/evaluation.

Threat model
------------

Expressions originate from untrusted ``conf.py``/RST authors *and* from
untrusted included ``.cho`` content (song metadata flows verbatim into
``song_meta``). Arbitrary code execution must be impossible.

Design (LOCKED — AST allow-list interpreter, default-deny)
----------------------------------------------------------

We ``ast.parse(expr, mode="eval")`` and then *interpret* a strict allow-listed
subset of the AST. ``eval``/``exec``/``compile`` are never used. **The
allow-list is the sole safety authority**: any AST node type not explicitly
allowed is rejected with :class:`FilterError`. ``mode="eval"`` still parses
``ListComp``/``Lambda``/``JoinedStr``/``Attribute``/``Subscript``/``IfExp``/
``Slice``, so safety rests entirely on default-deny.

Allowed nodes (the complete set):

* ``Expression`` (the root)
* ``BoolOp`` — ``and`` / ``or``
* ``UnaryOp`` — ``not`` only
* ``Compare`` — ``== != < <= > >= in not in`` (multi-comparator like
  ``1990 < year < 2000`` is one ``Compare`` node and is allowed)
* ``Constant`` — str / num / bool / None
* ``Name`` — resolved from the per-song namespace only
* ``List`` / ``Tuple`` / ``Set`` literals

Everything else is rejected, notably ``BinOp`` (**no arithmetic at all** — this
removes the string/list repetition and huge-power DoS class), ``UnaryOp`` with
``-``/``+``, ``Call``, ``Attribute`` (blocks dunder traversal),
``Subscript``/``Slice``, ``IfExp`` (ternary), comprehensions, ``Lambda``,
``NamedExpr`` (walrus), ``JoinedStr``/``FormattedValue`` (f-strings),
``Starred``, generators/``await``/``yield``.

This module is pure: it imports no Sphinx/Docutils and has no side effects.
"""

from __future__ import annotations

import ast
from typing import Any, Optional

__all__ = ["safe_eval", "FilterError", "Missing", "MISSING"]


class FilterError(Exception):
    """Raised for a parse error or a rejected (non-allow-listed) expression.

    CHUNK-5-3 catches this and surfaces it as a Sphinx warning per its policy.
    A coercion/type failure during comparison does **not** raise — it evaluates
    to ``False`` (see the coercion table in the module doc).
    """


class _Missing:
    """Falsy sentinel for an unknown name (LOCKED).

    Any ``Compare``/``in`` touching a :class:`_Missing` evaluates to ``False``;
    ``not Missing`` is ``False`` (does **not** flip exclude→include);
    ``Missing and/or ...`` composes as a falsy value.
    """

    _instance: "Optional[_Missing]" = None

    def __new__(cls) -> "_Missing":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "Missing"


#: The single falsy sentinel instance for unknown names.
MISSING = _Missing()
#: Public alias (the class-like name used in docs/tests).
Missing = _Missing

# Resource bounds (LOCKED). With no BinOp the only DoS surface is AST size and
# interpreter recursion depth.
_MAX_NODES = 500
_MAX_DEPTH = 50

# AST node types the interpreter is willing to walk. Default-deny: anything not
# listed here is a FilterError.
_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Constant,
    ast.Name,
    ast.List,
    ast.Tuple,
    ast.Set,
    # Operator/context marker nodes that are children of the above and carry no
    # behaviour of their own; validated structurally by their parent handlers.
    ast.And,
    ast.Or,
    ast.Not,
    ast.Load,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)

# Per-expression parsed-AST cache. Resolve runs single-process (no threading),
# so an unbounded dict is fine and keeps repeated filters cheap.
_AST_CACHE: dict = {}


def _validate(tree: ast.AST) -> None:
    """Reject any non-allow-listed node and enforce node-count/depth caps.

    Raises :class:`FilterError` on the first violation.
    """

    node_count = 0

    def walk(node: ast.AST, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > _MAX_NODES:
            raise FilterError("expression too large (node cap exceeded)")
        if depth > _MAX_DEPTH:
            raise FilterError("expression too deeply nested (depth cap exceeded)")
        if not isinstance(node, _ALLOWED_NODES):
            raise FilterError(
                f"disallowed expression element: {type(node).__name__}"
            )
        # UnaryOp is allowed only with the `not` operator.
        if isinstance(node, ast.UnaryOp) and not isinstance(node.op, ast.Not):
            raise FilterError("only the `not` unary operator is allowed")
        for child in ast.iter_child_nodes(node):
            walk(child, depth + 1)

    walk(tree, 0)


def _parse(expr: str) -> ast.Expression:
    """Parse + validate ``expr`` (cached). Raises :class:`FilterError`."""

    cached = _AST_CACHE.get(expr)
    if cached is not None:
        return cached
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise FilterError(f"could not parse expression: {exc}") from exc
    _validate(tree)
    _AST_CACHE[expr] = tree
    return tree


def _as_number(value: Any):
    """Return an int/float for a numeric ``value`` or a fully-numeric string.

    Returns ``None`` when ``value`` cannot be coerced (the caller treats that as
    a failed comparison → ``False``). ``bool`` is intentionally *not* treated as
    a number here (bools only participate in equality).
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _compare_pair(left: Any, op: ast.AST, right: Any, diagnostics) -> bool:
    """Evaluate a single ``left <op> right`` comparison per the coercion table.

    Any coercion/type failure → ``False`` (never raises). ``diagnostics`` (if
    provided) collects human-readable notes about silent coercion failures so
    CHUNK-5-3 can warn.
    """

    # Anything touching a Missing sentinel yields Missing (falsy), so a bare
    # comparison excludes the song AND `not <compare>` does not flip to include
    # (the negation trap is closed): `not MISSING` is False, not True.
    if isinstance(left, _Missing) or isinstance(right, _Missing):
        return MISSING

    # Membership operators.
    if isinstance(op, (ast.In, ast.NotIn)):
        result = _membership(left, right, diagnostics)
        return (not result) if isinstance(op, ast.NotIn) else result

    # Equality operators: `== None` presence test, else direct/`coerced` equality.
    if isinstance(op, (ast.Eq, ast.NotEq)):
        equal = _equals(left, right, diagnostics)
        return (not equal) if isinstance(op, ast.NotEq) else equal

    # Ordering operators: <, <=, >, >=.
    return _ordering(left, op, right, diagnostics)


def _membership(left: Any, right: Any, diagnostics) -> bool:
    """``x in <list>`` = list membership; ``x in <str>`` = substring; else False."""

    if isinstance(right, (list, tuple, set)):
        return left in right
    if isinstance(right, str):
        # substring membership (documented): "a" in "Beginner" -> True
        if not isinstance(left, str):
            left = str(left)
        return left in right
    # Missing / number / None on the right -> not iterable for membership.
    if diagnostics is not None:
        diagnostics.append(
            f"`in` right-hand side is not a list/str ({type(right).__name__}); "
            f"treated as no match"
        )
    return False


def _equals(left: Any, right: Any, diagnostics) -> bool:
    """Equality with `== None` presence semantics and numeric-string coercion."""

    # `== None` is a presence/None test (value equal to the None constant).
    if left is None or right is None:
        return left is right or (left is None and right is None)

    # bool participates only in exact equality (avoid 1 == True surprises here:
    # a metadata value is a str/list, never a Python bool, so exact match is fine).
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right

    # If both sides are numbers-or-numeric-strings, compare numerically.
    ln, rn = _as_number(left), _as_number(right)
    if ln is not None and rn is not None:
        return ln == rn

    # str vs str -> lexical equality; anything else -> direct equality.
    if isinstance(left, str) and isinstance(right, str):
        return left == right

    # Mixed numeric/str where one side is not numeric -> coercion failure.
    if (isinstance(left, str) and isinstance(right, (int, float))) or (
        isinstance(right, str) and isinstance(left, (int, float))
    ):
        if diagnostics is not None:
            diagnostics.append(
                f"equality coercion failed between {left!r} and {right!r}; "
                f"treated as not equal"
            )
        return False

    return left == right


def _ordering(left: Any, op: ast.AST, right: Any, diagnostics) -> bool:
    """<, <=, >, >= with numeric-string coercion; failure -> False."""

    ln, rn = _as_number(left), _as_number(right)
    if ln is not None and rn is not None:
        lo, ro = ln, rn
    elif isinstance(left, str) and isinstance(right, str):
        # Neither is numeric -> lexical ordering.
        lo, ro = left, right
    else:
        if diagnostics is not None:
            diagnostics.append(
                f"ordering coercion failed between {left!r} and {right!r}; "
                f"treated as no match"
            )
        return False

    if isinstance(op, ast.Lt):
        return lo < ro
    if isinstance(op, ast.LtE):
        return lo <= ro
    if isinstance(op, ast.Gt):
        return lo > ro
    if isinstance(op, ast.GtE):
        return lo >= ro
    return False  # pragma: no cover - exhaustive above


def _eval_node(node: ast.AST, namespace: dict, diagnostics) -> Any:
    """Interpret one allow-listed node. Returns a Python value or MISSING."""

    if isinstance(node, ast.Expression):
        return _eval_node(node.body, namespace, diagnostics)

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        # True/False/None are Constant nodes, never Name — a metadata key
        # cannot shadow them. Unknown name -> falsy Missing sentinel.
        return namespace.get(node.id, MISSING)

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(elt, namespace, diagnostics) for elt in node.elts]

    if isinstance(node, ast.Set):
        return {_eval_node(elt, namespace, diagnostics) for elt in node.elts}

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if not _truthy(_eval_node(value, namespace, diagnostics)):
                    return False
            return True
        # Or
        for value in node.values:
            if _truthy(_eval_node(value, namespace, diagnostics)):
                return True
        return False

    if isinstance(node, ast.UnaryOp):
        # Only `not` reaches here (validated). `not Missing` -> False (no flip).
        operand = _eval_node(node.operand, namespace, diagnostics)
        if isinstance(operand, _Missing):
            return False
        return not _truthy(operand)

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, namespace, diagnostics)
        for op, comparator_node in zip(node.ops, node.comparators):
            right = _eval_node(comparator_node, namespace, diagnostics)
            outcome = _compare_pair(left, op, right, diagnostics)
            # Missing propagates through the chain so `not` cannot flip it.
            if isinstance(outcome, _Missing):
                return MISSING
            if not outcome:
                return False
            # Chained comparison: the right operand becomes the next left.
            left = right
        return True

    # Should be unreachable: _validate rejects anything else.
    raise FilterError(  # pragma: no cover - defensive
        f"unsupported expression element: {type(node).__name__}"
    )


def _truthy(value: Any) -> bool:
    """Truthiness with Missing collapsing to False."""

    if isinstance(value, _Missing):
        return False
    return bool(value)


def safe_eval(
    expr: str,
    namespace: dict,
    diagnostics: Optional[list] = None,
) -> bool:
    """Evaluate ``expr`` against ``namespace`` and return its truthiness.

    Deterministic and side-effect-free: the same ``(expr, namespace)`` always
    returns the same bool, and ``namespace`` is never mutated. A parse error or
    a rejected (non-allow-listed) node raises :class:`FilterError`; a
    coercion/type failure inside a comparison never raises — it evaluates the
    comparison to ``False``. Never uses ``eval``/``exec``/``compile``.

    :param expr: the filter expression (e.g. ``'"rock" in tags and year > 1990'``).
    :param namespace: the per-song entry dict (plain str/list values, plus the
        5-1 back-refs ``id``/``docname``); no callables, no builtins.
    :param diagnostics: optional list; when supplied, human-readable notes about
        silent coercion failures are appended for CHUNK-5-3 to surface as warnings.
    :returns: the truthiness of the evaluated expression.
    :raises FilterError: on parse error or a disallowed expression element.
    """

    tree = _parse(expr)
    result = _eval_node(tree, namespace, diagnostics)
    return _truthy(result)
