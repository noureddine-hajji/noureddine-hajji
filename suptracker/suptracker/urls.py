"""Parcoursup fiche URL parsing."""
from __future__ import annotations

import re

# Fiche URLs carry the formation's cod_aff_form as g_ta_cod, e.g.
# https://dossierappel.parcoursup.fr/Candidats/public/fiches/afficherFicheFormation?g_ta_cod=6170&typeBac=0
_G_TA_COD = re.compile(r"[?&#]g_ta_cod=(\d+)", re.IGNORECASE)
_PARCOURSUP_HOST = re.compile(r"^(https?://)?([a-z0-9-]+\.)*parcoursup\.fr(/|$)", re.IGNORECASE)
UAI_RE = re.compile(r"^\d{7}[A-Za-z]$")


def extract_cod_aff_form(text: str) -> str | None:
    text = text.strip()
    if not _PARCOURSUP_HOST.match(text):
        return None
    m = _G_TA_COD.search(text)
    return m.group(1) if m else None


def is_uai(text: str) -> bool:
    return bool(UAI_RE.match(text.strip()))
