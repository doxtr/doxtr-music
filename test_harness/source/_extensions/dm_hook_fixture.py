"""Harness fixture: an ``html_visit`` plugin hook for the CHUNK-5-4 feature.

Placed on the harness ``_extensions`` path so the ``plugin_hooks`` feature's
``conf_override`` can reference it as the dotted-string config value
``doxtr_music_html_visit = "dm_hook_fixture.inject_hook"`` (importlib resolution,
never eval).

The hook appends a sentinel marker to ``translator.body``. doxtr-music invokes
it INSIDE a copy-neutral ``.doxtr-hook`` wrapper (see
``doxtr_music/builders/html.py``), so the injected text must not leak into the
copy-safe lyric stream. The sentinel text ``DMHOOKSENTINEL`` and the
``data-dm-hook="visited"`` attribute are what the ``HOOK_INJECTED_HTML``
assertion looks for.
"""

from __future__ import annotations


def inject_hook(node, translator):
    """Append a sentinel span during HTML translation of a song node.

    Signature matches the LOCKED ``html_visit(node, translator) -> None``
    contract. The caller has already opened the ``.doxtr-hook`` copy-neutral
    wrapper, so this markup is stripped from the copyable lyric stream.
    """
    translator.body.append(
        '<span data-dm-hook="visited">DMHOOKSENTINEL</span>'
    )
