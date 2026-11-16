"""Sprint R3 (owner, 2026-11-12): the bands of the filters shared by the search page and the map.

One definition of every band, served to the page (`vocab`, in /api/meta) so every list cuts at the same values:

* capacité: the published number of places of the formation's own campaign (`capa_fin`), four bands;
* phase complémentaire: did the formation ADMIT candidates in the complementary phase of its own campaign (`acc_pc` > 0)? Admits
  of a past campaign, never places left this year (the page says so);
* statut: public, private under contract, fee-charging private (Plan B's rule, `carte.statut_of`);
* taux d'accès: the OFFICIAL rate of the campaign (`taux_acces_ens`), four bands; a formation without a published rate is in none;
* zone: the zone of "Mon parcours", read by the page in the browser for the stored profile.

Owner, 2026-11-16: the filtering on the server of sprint R3 (`/api/search?avance=true`: these bands, the zones read for a profile
sent with the search) is gone. Since sprint H the one search page asks the engine for its keyword's codes only and filters in the
browser with these bands (`filtreBand`, `carteHas`); no profile travels with a search any more.

The list is never sorted by these values (never by chances).
"""
from __future__ import annotations

CAPACITE = (("moins20", "Moins de 20 places", None, 20), ("20a49", "20 à 49 places", 20, 50),
            ("50a99", "50 à 99 places", 50, 100), ("100plus", "100 places et plus", 100, None))
TAUX = (("moins30", "Moins de 30 %", None, 30), ("30a59", "De 30 à 59 %", 30, 60),
        ("60a89", "De 60 à 89 %", 60, 90), ("90plus", "90 % et plus", 90, None))
COMPLEMENTAIRE = (("oui", "A admis des candidats en phase complémentaire"), ("non", "Aucun admis en phase complémentaire"))
STATUT = (("public", "Publics"), ("contrat", "Privés sous contrat avec l'État / EESC"), ("prive", "Privés (payants)"))
ZONE = (("securite", "Vœux de sécurité"), ("cible", "Vœux cibles"), ("ambitieux", "Vœux ambitieux"),
        ("autre", "Autres (hors-profil, indéterminés, non situés)"))
ZONE_KEYS = ("securite", "cible", "ambitieux")


def vocab() -> dict:
    """What the page reads: every option of every group, the bands with their limits (the map cuts with the same ones)."""
    band = lambda b: [{"key": k, "label": lab, "min": lo, "max": hi} for k, lab, lo, hi in b]  # noqa: E731
    pair = lambda b: [{"key": k, "label": lab} for k, lab in b]  # noqa: E731
    return {"capacite": band(CAPACITE), "taux": band(TAUX), "complementaire": pair(COMPLEMENTAIRE),
            "statut": pair(STATUT), "zone": pair(ZONE)}


def band(value, bands) -> str | None:
    """The band of a value: lower limit included, upper limit excluded; no value, no band."""
    if value is None:
        return None
    for key, _, lo, hi in bands:
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return key
    return None
