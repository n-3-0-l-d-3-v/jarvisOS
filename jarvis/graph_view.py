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

# Stable palette per domain family so colours don't shuffle between loads.
_PALETTE = [
    "#00d4ff", "#7a5cff", "#3ddc84", "#ffb703", "#ff6b6b",
    "#b388ff", "#4dd0e1", "#f06292", "#aed581", "#ffd54f",
    "#4fc3f7", "#ff8a65", "#9575cd", "#81c784", "#e57373",
]


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

    domains = sorted({(n.get("domain") or "other") for n in notes})
    colour_of = {d: _PALETTE[i % len(_PALETTE)] for i, d in enumerate(domains)}

    index_of = {}
    nodes = []
    for i, note in enumerate(notes):
        key = (note.get("folder_path", ""), note.get("filename", ""))
        index_of[key] = i
        note_domain = note.get("domain") or "other"
        nodes.append({
            "id": i,
            "title": note.get("title", "Untitled"),
            "domain": note_domain,
            "type": note.get("type", "concept"),
            "path": f"{key[0]}/{key[1]}",
            "colour": colour_of[note_domain],
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
        "domains": [{"domain": d, "colour": colour_of[d]} for d in domains],
        "stats": {"node_count": len(nodes), "edge_count": len(edges)},
    }
