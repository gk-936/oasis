def step(run: dict, title_part: str) -> dict:
    """Look a demo step up by (a fragment of) its title instead of by position."""
    hits = [s for s in run["steps"] if title_part.lower() in s["title"].lower()]
    assert len(hits) == 1, f"expected exactly one demo step matching {title_part!r}, got {[s['title'] for s in run['steps']]}"
    return hits[0]


def status(run: dict, title_part: str) -> str:
    return step(run, title_part)["outcome"]["status"]
