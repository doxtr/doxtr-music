# Config override for the ``multi_singer`` harness feature (CHUNK-4-2).
#
# Sets a GLOBAL singer-color map. The RST fixture's per-song ``:singer-colors:``
# then OVERRIDES singer ``A`` per-id (global #999999 -> per-song #1a53a1) and
# adds singer ``B`` (#e07b00), proving the three-tier merge (global ⊕ per-song)
# and per-id override. The final rendered colors are the per-song values, which
# also win over the per-song :chord-color: #cc0000 typography (singer wins on
# color; typography font/size still apply).
doxtr_music_singer_colors = {
    "A": "#999999",
}
