"""Unit + security tests for :mod:`doxtr_music.safe_eval` (CHUNK-5-2).

The safe evaluator is the sole ``:filter:``/``:group-by:`` expression authority.
These tests lock the allow-list, the coercion table, the Missing-sentinel
semantics, the resource bounds, and prove the security matrix is rejected
without executing anything.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from doxtr_music import safe_eval as se
from doxtr_music.safe_eval import FilterError, MISSING, safe_eval


# --------------------------------------------------------------------------- #
# Positive: membership, boolean logic, comparisons, literals, coercion.
# --------------------------------------------------------------------------- #

def test_locked_example_numeric_string_coercion():
    # Exit criterion 1.
    assert safe_eval(
        '"rock" in tags and year > 1990',
        {"tags": ["rock"], "year": "1991"},
    ) is True


def test_list_membership_true_and_false():
    assert safe_eval('"rock" in tags', {"tags": ["rock", "pop"]}) is True
    assert safe_eval('"jazz" in tags', {"tags": ["rock", "pop"]}) is False


def test_not_in_membership():
    assert safe_eval('"jazz" not in tags', {"tags": ["rock"]}) is True
    assert safe_eval('"rock" not in tags', {"tags": ["rock"]}) is False


def test_substring_membership_on_string_value():
    # Documented: `x in <str>` is substring membership.
    assert safe_eval('"e" in level', {"level": "Beginner"}) is True
    assert safe_eval('"z" in level', {"level": "Beginner"}) is False


def test_bool_and_or_not():
    ns = {"tags": ["rock"], "year": "1991"}
    assert safe_eval('"rock" in tags or "pop" in tags', ns) is True
    assert safe_eval('"pop" in tags or "jazz" in tags', ns) is False
    assert safe_eval('not ("pop" in tags)', ns) is True
    assert safe_eval('"rock" in tags and not ("pop" in tags)', ns) is True


def test_comparisons_all_operators():
    ns = {"year": "1991"}
    assert safe_eval("year == 1991", ns) is True
    assert safe_eval("year != 2000", ns) is True
    assert safe_eval("year < 2000", ns) is True
    assert safe_eval("year <= 1991", ns) is True
    assert safe_eval("year > 1990", ns) is True
    assert safe_eval("year >= 1991", ns) is True


def test_multi_comparator_chain():
    # `1990 < year < 2000` is one Compare node and is allowed.
    assert safe_eval("1990 < year < 2000", {"year": "1991"}) is True
    assert safe_eval("1990 < year < 2000", {"year": "2005"}) is False


def test_list_tuple_set_literals():
    assert safe_eval('genre in ["rock", "pop"]', {"genre": "rock"}) is True
    assert safe_eval('genre in ("rock", "pop")', {"genre": "jazz"}) is False
    assert safe_eval('genre in {"rock", "pop"}', {"genre": "pop"}) is True


def test_true_false_none_are_constants_not_shadowable():
    # A metadata key named True/False/None cannot exist as a Name; these parse
    # as Constants. Presence test uses `== None`.
    assert safe_eval("missingkey == None", {}) is False  # Missing != None
    assert safe_eval("k == None", {"k": None}) is True    # explicit None value


def test_lexical_string_ordering():
    assert safe_eval('artist < "N"', {"artist": "Adele"}) is True
    assert safe_eval('artist > "N"', {"artist": "Zappa"}) is True


# --------------------------------------------------------------------------- #
# Missing-name semantics + negation trap.
# --------------------------------------------------------------------------- #

def test_unknown_name_excludes():
    # Exit criterion 2: a filter referencing a key some songs lack excludes them.
    assert safe_eval("year > 1990", {}) is False
    assert safe_eval('"rock" in tags', {}) is False


def test_not_missing_does_not_flip_to_include():
    # `not (year > 1990)` on a key-less namespace must be False (no include-flip).
    assert safe_eval("not (year > 1990)", {}) is False
    assert safe_eval("not year", {}) is False


def test_missing_composes_falsy_in_boolop():
    assert safe_eval("year and True", {}) is False
    assert safe_eval("year or False", {}) is False
    assert safe_eval("True or year", {}) is True


def test_missing_sentinel_is_falsy():
    assert bool(MISSING) is False


# --------------------------------------------------------------------------- #
# Coercion table (LOCKED).
# --------------------------------------------------------------------------- #

def test_numeric_string_vs_number():
    # A numeric-looking string literal coerces on comparison per the table.
    assert safe_eval('"1991" > 1990', {}) is True
    assert safe_eval("v > 1990", {"v": "1991"}) is True


def test_nonnumeric_string_vs_number_is_false():
    assert safe_eval("v > 100", {"v": "120 swing"}) is False
    assert safe_eval("v == 100", {"v": "abc"}) is False


def test_number_vs_number():
    assert safe_eval("v == 100", {"v": 100}) is True
    assert safe_eval("v < 100", {"v": 99}) is True


def test_in_on_missing_number_none_is_false():
    assert safe_eval('"x" in v', {"v": MISSING}) is False
    assert safe_eval('"x" in v', {"v": 5}) is False
    assert safe_eval('"x" in v', {"v": None}) is False


def test_equality_coercion_failure_is_false_not_raise():
    # str vs number where str is non-numeric -> False, no raise.
    assert safe_eval("v == 5", {"v": "hello"}) is False


def test_scalar_meta_truthiness_is_nonempty_string():
    # Documented: bare `featured` where value "true" is a non-empty str -> truthy.
    assert safe_eval("featured", {"featured": "true"}) is True
    assert safe_eval("featured", {"featured": ""}) is False


def test_diagnostics_collected_on_coercion_failure():
    diags: list = []
    assert safe_eval("v > 100", {"v": "not-a-number"}, diagnostics=diags) is False
    assert diags  # a coercion-failure note was recorded


# --------------------------------------------------------------------------- #
# Security matrix (Exit criterion 3): all raise FilterError, none execute.
# --------------------------------------------------------------------------- #

SECURITY_MATRIX = [
    "__import__('os')",
    "().__class__",
    "open('x')",
    "a.b",
    "tags[0]",
    "[x for x in y]",
    "(lambda: 1)()",
    'f"{x}"',
    "(x := 1)",
    "1 if a else b",
    "1+1",
    "1-1",
    "2*3",
    "6/2",
    "7//2",
    "7%2",
    '"a"*99999999',
    "[0]*99999999",
    "2**99",
    "-5",
    "+5",
    "a and (b for b in c)",
    "x.__class__.__mro__",
    "eval('1')",
    "exec('x=1')",
    "compile('1','<s>','eval')",
]


@pytest.mark.parametrize("expr", SECURITY_MATRIX)
def test_security_matrix_rejected(expr):
    with pytest.raises(FilterError):
        safe_eval(expr, {"a": "1", "b": "2", "c": ["x"], "tags": ["t"], "x": "v", "y": ["z"]})


def test_no_hang_on_repetition_attack():
    # These must reject immediately (BinOp forbidden), never allocate/hang.
    for expr in ('"a"*99999999', "[0]*99999999", "2**99999"):
        with pytest.raises(FilterError):
            safe_eval(expr, {})


# --------------------------------------------------------------------------- #
# Resource bounds.
# --------------------------------------------------------------------------- #

def test_node_count_cap_rejected():
    # A big OR chain of literals exceeds the node cap -> FilterError, no hang.
    expr = " or ".join(["a == 1"] * 300)
    with pytest.raises(FilterError):
        safe_eval(expr, {"a": "1"})


def test_depth_cap_rejected():
    # Deeply nested `not (not (...))` exceeds the depth cap.
    expr = "not (" * 60 + "a" + ")" * 60
    with pytest.raises(FilterError):
        safe_eval(expr, {"a": "1"})


# --------------------------------------------------------------------------- #
# Purity, determinism, no mutation, AST cache, AST-based no-eval check.
# --------------------------------------------------------------------------- #

def test_determinism_and_no_namespace_mutation():
    ns = {"tags": ["rock"], "year": "1991"}
    snapshot = {"tags": list(ns["tags"]), "year": ns["year"]}
    r1 = safe_eval('"rock" in tags and year > 1990', ns)
    r2 = safe_eval('"rock" in tags and year > 1990', ns)
    assert r1 is r2 is True
    assert ns == snapshot  # namespace untouched


def test_ast_cache_reuses_parsed_tree():
    expr = "year > 1990"
    safe_eval(expr, {"year": "2000"})
    assert expr in se._AST_CACHE
    first = se._AST_CACHE[expr]
    safe_eval(expr, {"year": "1980"})
    assert se._AST_CACHE[expr] is first  # same cached tree object


def test_no_sphinx_or_docutils_import_in_module():
    src = Path(inspect.getfile(se)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "sphinx" not in imported
    assert "docutils" not in imported


def test_ast_based_no_eval_exec_compile_in_source():
    # Exit criterion 4: AST-based (not substring) check that the module never
    # *calls* eval/exec/compile. Substring scanning would false-positive on the
    # module/function name "safe_eval".
    src = Path(inspect.getfile(se)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"eval", "exec", "compile"}
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in forbidden:
                offenders.append(func.id)
            if isinstance(func, ast.Attribute) and func.attr in forbidden:
                offenders.append(func.attr)
    assert offenders == [], f"forbidden call(s) present: {offenders}"


def test_filter_error_is_exception():
    assert issubclass(FilterError, Exception)


def test_syntax_error_raises_filter_error():
    with pytest.raises(FilterError):
        safe_eval("year > ", {"year": "1"})
    with pytest.raises(FilterError):
        safe_eval("", {})
