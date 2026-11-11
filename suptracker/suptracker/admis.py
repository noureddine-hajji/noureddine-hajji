"""Who the admits are: néo-bacheliers and the other admits (owner's request, 2026-11-10).

SIES publishes, per formation and campaign, the admits (`acc_tot`), the néo-bachelier admits (`acc_neobac`: they passed the
bac that year) and the other admits (`acc_at`: already holding the bac or another route, e.g. reorientation or a return to
studies). SIES does not split the other admits further. On the real exports `acc_tot = acc_neobac + acc_at` on every row of
2024 and 2025, and on all but 21 (2022) and 15 (2023) rows, where the two counts miss the total by one or two.

Rules (fixed, from published counts only, never a chance):
  * the formation page shows the two published counts; the bar is drawn only when they add up to the published total;
  * a list labels a formation "Majorité d'admis hors néo-bacheliers" when, in the campaign shown, the counts add up, there are
    at least MIN_ADMIS admits and the other admits outnumber the néo-bacheliers (a tie is not a majority).
The mention and bac-series shares SIES publishes cover the néo-bachelier admits only: the page says so.
"""
from __future__ import annotations

MIN_ADMIS = 10


def coherent(tot, neo, at) -> bool:
    return tot is not None and neo is not None and at is not None and tot == neo + at


def autres_majoritaires(tot, neo, at) -> bool:
    return coherent(tot, neo, at) and tot >= MIN_ADMIS and at > neo


def repartition(rec: dict) -> dict | None:
    """The formation page's block: the published counts and the published share of néo-bacheliers."""
    tot, neo, at = rec.get("acc_tot"), rec.get("acc_neobac"), rec.get("acc_at")
    if not tot:
        return None
    return {"session": rec.get("session"), "admis": tot, "admis_neobac": neo, "admis_autres": at,
            "pct_neobac": rec.get("pct_neobac"), "coherent": coherent(tot, neo, at),
            "autres_majoritaires": autres_majoritaires(tot, neo, at), "min_admis": MIN_ADMIS}


def flags(con, keys) -> dict:
    """(cod_aff_form, session) -> autres_majoritaires; one query per campaign (read-only connection, no temp table)."""
    by: dict[int, set] = {}
    for c, s in keys:
        if c is not None and s is not None:
            by.setdefault(int(s), set()).add(str(c))
    out = {}
    for s, cods in by.items():
        for c, t, n, a in con.execute("""SELECT cod_aff_form, acc_tot, acc_neobac, acc_at FROM core.formation_year
                WHERE session = ? AND list_contains(?, cod_aff_form)""", [s, sorted(cods)]).fetchall():
            out[(c, s)] = autres_majoritaires(t, n, a)
    return out


def mark(con, items: list[dict], session: int | None = None, only=lambda x: True) -> list[dict]:
    """New dicts (the inputs may be shared, e.g. search index documents) with `autres_majoritaires`; `session` is the
    campaign when the items do not carry their own."""
    key = lambda x: (str(x.get("cod_aff_form")), x.get("session", session))
    fl = flags(con, [key(x) for x in items if only(x)])
    return [{**x, "autres_majoritaires": bool(only(x) and fl.get(key(x), False))} for x in items]
