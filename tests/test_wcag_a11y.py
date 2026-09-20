"""Unit tests for CHUNK-4-3 WCAG 2.1 AA accessibility (HTML + EPUB).

Covers the a11y ARIA builders, the visible non-color singer cue, the EPUB
chord↔word hidden alternative, and the resolved-color contrast validation
(warn-not-fail). Rendering-level DOM checks are exercised by the harness
feature ``wcag_a11y``; these tests pin the pure helpers + the contrast policy
without a full Sphinx build.
"""

from __future__ import annotations

import pytest

from doxtr_music import a11y


# ---------------------------------------------------------------------------
# ARIA accessible-name builders
# ---------------------------------------------------------------------------

def test_chord_aria_label_has_no_word_suffix():
    # HTML relies on DOM proximity -> no ", word: ..." (avoids duplicate read).
    assert a11y.chord_aria_label("G") == "Chord: G"
    assert a11y.chord_aria_label("F#m7b5") == "Chord: F#m7b5"


def test_roman_aria_label():
    assert a11y.roman_aria_label("IV") == "Roman numeral: IV"


def test_epub_chord_word_alt_includes_word_when_known():
    # EPUB <pre> has no positional order -> the word IS spelled out.
    assert a11y.epub_chord_word_alt("G", "Amazing") == "Chord: G, word: Amazing"
    assert a11y.epub_chord_word_alt("G", "") == "Chord: G"


# ---------------------------------------------------------------------------
# Visible non-color singer cue (WCAG 1.4.1) + SR-only label
# ---------------------------------------------------------------------------

def test_singer_visible_cue_is_a_visible_badge():
    assert a11y.singer_visible_cue("A") == "A:"
    assert a11y.singer_visible_cue("  B  ") == "B:"
    assert a11y.singer_visible_cue("") == ""


def test_singer_sr_label_is_layered_affordance():
    assert a11y.singer_sr_label("A") == "Singer A"
    assert a11y.singer_sr_label("") == ""


def test_visually_hidden_style_avoids_position_absolute():
    # The EPUB_PRE_FALLBACK gate forbids position:absolute anywhere in the
    # EPUB song markup, so the hidden-text technique must not use it.
    assert "position:absolute" not in a11y.VISUALLY_HIDDEN_STYLE
    assert "clip-path" in a11y.VISUALLY_HIDDEN_STYLE


# ---------------------------------------------------------------------------
# WCAG 2.1 contrast math (mirrors the core wcag_contrast shape)
# ---------------------------------------------------------------------------

def test_parse_hex_color_forms():
    assert a11y.parse_hex_color("#000000") == (0, 0, 0)
    assert a11y.parse_hex_color("fff") == (255, 255, 255)
    assert a11y.parse_hex_color("#12345678") == (0x12, 0x34, 0x56)  # alpha drop
    assert a11y.parse_hex_color("rebeccapurple") is None  # named -> not hex
    assert a11y.parse_hex_color("") is None


def test_contrast_ratio_black_on_white_is_21():
    ratio = a11y.wcag_contrast_ratio("#000000", "#ffffff")
    assert ratio == pytest.approx(21.0, abs=0.01)


def test_contrast_ratio_identical_is_one():
    assert a11y.wcag_contrast_ratio("#777", "#777") == pytest.approx(1.0)


def test_contrast_ratio_non_hex_is_none():
    assert a11y.wcag_contrast_ratio("red", "#fff") is None


# ---------------------------------------------------------------------------
# Size-aware large-text threshold
# ---------------------------------------------------------------------------

def test_size_is_large_thresholds():
    assert a11y.size_is_large("18pt") is True
    assert a11y.size_is_large("17.9pt") is False
    assert a11y.size_is_large("14pt", bold=True) is True
    assert a11y.size_is_large("2em") is False  # non-pt -> normal (stricter)
    assert a11y.size_is_large(None) is False


# ---------------------------------------------------------------------------
# Contrast validation (warn-not-fail) over resolved node colors
# ---------------------------------------------------------------------------

class _FakeNode(dict):
    """Minimal SongNode stand-in: dict attrs + a findall that yields nothing.

    ``check_song_contrast`` reads ``song_node['typography']`` and walks
    SingerSpanNodes; with no singer runs, ``findall`` returns an empty list.
    """

    def findall(self, cls):
        return iter(())


def _song_with_typography(typo):
    node = _FakeNode()
    node["typography"] = typo
    return node


def test_contrast_warns_on_sub_aa_color():
    warnings = []
    # #999999 on #ffffff ~ 2.85:1 (sub-AA for normal text).
    node = _song_with_typography({"chord": {"color": "#999999"}})
    warned = a11y.check_song_contrast(node, warn=warnings.append)
    assert warned and warned[0][0] == "chord"
    assert any("Low contrast" in w for w in warnings)


def test_contrast_no_warn_on_aa_color():
    warnings = []
    # #595959 on #ffffff ~ 7:1 (passes AA normal).
    node = _song_with_typography({"lyrics": {"color": "#595959"}})
    warned = a11y.check_song_contrast(node, warn=warnings.append)
    assert warned == []
    assert warnings == []


def test_contrast_skips_non_hex_color():
    warnings = []
    node = _song_with_typography({"chord": {"color": "rebeccapurple"}})
    warned = a11y.check_song_contrast(node, warn=warnings.append)
    # Non-hex color -> ratio unknown -> skipped (no warning, warn-not-fail).
    assert warned == []
    assert warnings == []


def test_contrast_size_aware_large_text_passes_at_lower_ratio():
    warnings = []
    # #949494 on #ffffff ~ 2.98:1: fails normal (4.5) but passes large (3.0)?
    # Use a color that is >=3.0 but <4.5 to prove the size-aware branch.
    # #949494 ~ 2.98 (still <3); use #8a8a8a ~ 3.28:1.
    node = _song_with_typography({"chord": {"color": "#8a8a8a", "size": "20pt"}})
    warned = a11y.check_song_contrast(node, warn=warnings.append)
    assert warned == []  # large-text 3:1 threshold satisfied
    # Same color at normal size warns.
    warnings2 = []
    node2 = _song_with_typography({"chord": {"color": "#8a8a8a", "size": "12pt"}})
    warned2 = a11y.check_song_contrast(node2, warn=warnings2.append)
    assert warned2 and warnings2


def test_contrast_never_raises_and_is_warn_only():
    # Missing typography -> no colors -> no warnings, no exception.
    node = _FakeNode()
    assert a11y.check_song_contrast(node, warn=lambda m: None) == []
