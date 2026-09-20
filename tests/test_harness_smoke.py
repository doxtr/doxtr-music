"""Unit tests for the test-harness machinery (no full Sphinx build)."""

from __future__ import annotations

import features
import assertions
from assertions import AssertType, ASSERTION_DESCRIPTIONS, check_assertions


def test_smoke_feature_registered():
    feat = features.FEATURE_REGISTRY["smoke"]
    assert feat.sub_tests, "smoke feature must have at least one sub-test"
    st = feat.sub_tests[0]
    assert st.name == "provenance_meta"
    assert st.status == features.FeatureStatus.COMPLETE
    assert st.formats == ["html"]
    # Format-keyed model: html key populated, no latex/epub keys yet.
    assert "html" in st.expected_markers
    assert "latex" not in st.expected_markers
    assert "epub" not in st.expected_markers


def test_meta_tag_assertion_passes_on_meta():
    html = '<html><head><meta name="doxtr-music" content="x"/></head><body></body></html>'
    results = check_assertions(html, [AssertType.META_TAG_PRESENT])
    assert len(results) == 1
    assert results[0].passed is True


def test_meta_tag_assertion_fails_without_meta():
    html = "<html><head></head><body></body></html>"
    results = check_assertions(html, [AssertType.META_TAG_PRESENT])
    assert results[0].passed is False


def test_unknown_assertion_string_is_tolerated():
    # A sub-test may name an assertion string that is not a valid AssertType.
    # The runner parses assertion strings with AssertType(name) and skips
    # unknown ones (parse-and-skip). Verify that contract holds here.
    from test_runner import _evaluate_subtest
    from features import FeatureSubTest, FeatureStatus

    st = FeatureSubTest(
        name="tolerant",
        description="unknown assertion string is skipped",
        rst_file=None,
        formats=["html"],
        expected_markers={},
        assertions={"html": ["THIS_IS_NOT_A_REAL_ASSERTION"]},
        status=FeatureStatus.COMPLETE,
    )
    # No markers and only an unknown (skipped) assertion → SKIPPED, not error.
    result = _evaluate_subtest(st, "html", "<html></html>", 20, assertions_only=False)
    assert result.status.value == "skipped"


def test_every_reserved_assert_type_is_constructible():
    # All members (including reserved) must be constructible and describable.
    for member in AssertType:
        assert member in ASSERTION_DESCRIPTIONS, f"missing description for {member}"
        # AssertType(value) round-trips without KeyError/ValueError.
        assert AssertType(member.value) is member
