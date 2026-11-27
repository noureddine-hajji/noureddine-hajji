"""« Ce que regarde le jury » (owner, 2026-11-27): the search page's filter on the weights a formation's jury gives to the five
fields of its Parcoursup fiche (« Critères généraux d'évaluation »), as the LIVE fiche prints them (grilles.py, core.fiche_champ).

- The weights are PUBLISHED values (one per field, the five summing to 100 on every verified grid); a field the grid does not
  list weighs 0 (the jury does not count it). Never a score, a ranking or a chance: a filter only, the list is never sorted by it.
- Three levels per field, « Peu », « Moyen », « Beaucoup », cut by a FIXED rule measured on the grids of the fiches' campaign (never
  typed): the two cut points a < b, multiples of 5 (read at a glance: « moins de 15 % »), that bring the three bands nearest to a
  third each (lower limit in, upper out); the heavy round values (5, 10, 20 %) stay whole in one band. Each field has its own cut points: they differ a lot (engagement:
  half the grids give it 5 % or less; results: half give 30 % or more).
- A formation whose fiche publishes no verified grid has no level: the page says how many such formations a ticked level leaves out.
Red team `redteam_jury.py` (JU1-JU8).
"""
from __future__ import annotations

# (key, the field as the fiche prints it, the page's words)
CHAMPS = (("res", "Résultats scolaires", "Résultats scolaires"),
          ("eng", "Engagement et activités", "Engagement et activités"),
          ("mot", "Motivation", "Motivation"),
          ("se", "Savoir-être", "Savoir-être"),
          ("met", "Méthodes de travail", "Méthodes de travail"))
LEVELS = ("peu", "moyen", "beaucoup")


def weights(con) -> dict[str, list[int]]:
    """{code: [weight of each field of CHAMPS]} for every formation with a verified grid (a field not listed = 0)."""
    try:
        rows = con.execute("""SELECT c.cod_aff_form, c.champ, c.poids FROM core.fiche_champ c
            JOIN core.fiche_grille g ON g.cod_aff_form = c.cod_aff_form AND g.grille""").fetchall()
    except Exception:  # noqa: BLE001 - a warehouse built without the fiches: no grid, no filter
        return {}
    idx = {name: i for i, (_, name, _) in enumerate(CHAMPS)}
    out: dict[str, list[int]] = {}
    for cod, champ, poids in rows:
        if champ in idx and poids is not None:
            out.setdefault(cod, [0] * len(CHAMPS))[idx[champ]] = int(poids)
    return out


STEP = 5                                 # cut points are multiples of 5 %
MIN_BAND = 0.10                          # no band under a tenth of the grids (else the field gets no filter)


def cuts(values: list[int]) -> tuple[int, int] | None:
    """The fixed rule: cut points a < b, multiples of STEP in ]0, 100[, minimising the largest gap of the three bands
    (v < a, a <= v < b, v >= b) to a third; ties: the smallest a, then the smallest b. None when no pair leaves every band at
    least MIN_BAND of the values."""
    n = len(values)
    if n == 0:
        return None
    srt = sorted(values)
    grid = list(range(STEP, 100, STEP))
    below = {}
    k = 0
    for v in grid:                      # below[v] = how many values are < v
        while k < n and srt[k] < v:
            k += 1
        below[v] = k
    best = None
    for i, a in enumerate(grid):
        for b in grid[i + 1:]:
            parts = (below[a], below[b] - below[a], n - below[b])
            if min(parts) < MIN_BAND * n:
                continue
            gap = max(abs(p / n - 1 / 3) for p in parts)
            if best is None or gap < best[0] - 1e-12:
                best = (gap, a, b)
    return (best[1], best[2]) if best else None


def level(v: int | None, c: tuple[int, int] | list | None) -> str | None:
    """The level of a weight (lower limit in, upper out); twin `juryLevel` in app.js."""
    if v is None or not c:
        return None
    return "peu" if v < c[0] else "moyen" if v < c[1] else "beaucoup"


def labels(c: tuple[int, int]) -> dict[str, str]:
    a, b = c
    return {"peu": f"moins de {a} %", "moyen": f"de {a} à {b - 1} %" if b - 1 > a else f"{a} %", "beaucoup": f"{b} % ou plus"}


def meta(con) -> dict:
    """What the page reads (META.jury): every field with its cut points, its bands' words and counts, the grids' campaign."""
    w = weights(con)
    try:
        session = con.execute("SELECT max(session) FROM core.fiche_grille WHERE grille").fetchone()[0]
    except Exception:  # noqa: BLE001
        session = None
    champs = []
    for i, (key, name, words) in enumerate(CHAMPS):
        vals = [x[i] for x in w.values()]
        c = cuts(vals)
        if c is None:
            continue
        n = {lv: sum(1 for v in vals if level(v, c) == lv) for lv in LEVELS}
        champs.append({"key": key, "champ": name, "titre": words, "cuts": list(c), "labels": labels(c), "n": n})
    return {"n_grilles": len(w), "session": session, "champs": champs} if champs else {"n_grilles": 0, "session": None, "champs": []}
