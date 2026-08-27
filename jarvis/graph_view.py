"""
Knowledge-graph data for the dashboard visualization.

Turns index.json into a nodes/edges graph the browser can lay out with a force
simulation. Edge weight reuses the linker's relatedness scoring, so the picture
matches the cross-links Jarvis actually writes into your notes.

Kept deliberately small: the graph is computed on request from the index (no
extra store to keep in sync), capped for legibility, and the layout itself runs
client-side.
"""

from jarvis.index_store import load_index
from jarvis.linker import find_related_notes

# Beyond a few hundred nodes a force graph turns into a hairball and stops
# communicating anything, so cap and keep only the strongest edges.
MAX_NODES = 220
MIN_EDGE_SCORE = 3
MAX_EDGES_PER_NODE = 4

# Categorical palette: domain is an IDENTITY encoding, so hues must be
# distinguishable under colour-vision deficiency, not merely pretty. These eight
# steps are validated against this dashboard's surface (#1c1c2e) — all pass the
# lightness band, chroma floor, CVD separation and 3:1 contrast checks. The
# previous ad-hoc palette failed the lightness band (colours were far too light
# for a dark surface).
#
# Eight is the ceiling: a generated 9th hue is indistinguishable from an
# existing one under CVD, so the tail folds into a neutral "Other" instead.
_PALETTE = [
    "#3987e5",  # blue
    "#d95926",  # orange
    "#199e70",  # aqua
    "#c98500",  # yellow
    "#d55181",  # magenta
    "#008300",  # green
    "#9085e9",  # violet
    "#e66767",  # red
]
_OTHER_COLOUR = "#8a8a99"  # neutral for the folded tail
_OTHER_LABEL = "other"
MAX_DOMAIN_COLOURS = len(_PALETTE)


def _unique_notes():
    seen = {}
    for note in load_index().get("notes", []):
        key = (note.get("folder_path", ""), note.get("filename", ""))
        if key not in seen:
            seen[key] = note
    return list(seen.values())


def build_graph(domain=None, max_nodes=MAX_NODES):
    """Return {"nodes": [...], "edges": [...], "domains": [...]}."""
    notes = _unique_notes()
    if domain:
        notes = [n for n in notes if n.get("domain") == domain]

    # Prefer better-connected notes when trimming: those with tags/subdomains
    # carry more signal than bare ones.
    def _richness(note):
        return (len(note.get("tags") or []), bool(note.get("subdomain")))

    notes.sort(key=_richness, reverse=True)
    notes = notes[:max_nodes]

    # Colour the largest domains; everything past the palette ceiling folds into
    # a single neutral "other" so no two domains share a hue.
    counts = {}
    for note in notes:
        key = note.get("domain") or _OTHER_LABEL
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts, key=lambda d: (-counts[d], d))
    coloured = ranked[:MAX_DOMAIN_COLOURS]
    colour_of = {d: _PALETTE[i] for i, d in enumerate(coloured)}

    def _colour(domain):
        return colour_of.get(domain, _OTHER_COLOUR)

    def _label(domain):
        return domain if domain in colour_of else _OTHER_LABEL

    domains = list(coloured) + ([_OTHER_LABEL] if len(ranked) > len(coloured) else [])

    index_of = {}
    nodes = []
    for i, note in enumerate(notes):
        key = (note.get("folder_path", ""), note.get("filename", ""))
        index_of[key] = i
        note_domain = note.get("domain") or _OTHER_LABEL
        nodes.append({
            "id": i,
            "title": note.get("title", "Untitled"),
            "domain": note_domain,
            "legend": _label(note_domain),
            "type": note.get("type", "concept"),
            "path": f"{key[0]}/{key[1]}",
            "colour": _colour(note_domain),
            "degree": 0,
        })

    edges = []
    seen_pairs = set()
    for note in notes:
        source_key = (note.get("folder_path", ""), note.get("filename", ""))
        source = index_of[source_key]
        related = find_related_notes(note, notes, max_results=MAX_EDGES_PER_NODE)
        for rel in related:
            if rel.get("score", 0) < MIN_EDGE_SCORE:
                continue
            target_key = (rel.get("folder_path", ""), rel.get("filename", ""))
            target = index_of.get(target_key)
            if target is None or target == source:
                continue
            pair = (min(source, target), max(source, target))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append({"source": pair[0], "target": pair[1],
                          "weight": rel["score"]})
            nodes[pair[0]]["degree"] += 1
            nodes[pair[1]]["degree"] += 1

    return {
        "nodes": nodes,
        "edges": edges,
        "domains": [{"domain": d, "colour": _colour(d)} for d in domains],
        "stats": {"node_count": len(nodes), "edge_count": len(edges)},
    }
