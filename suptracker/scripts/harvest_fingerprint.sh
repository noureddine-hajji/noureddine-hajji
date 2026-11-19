#!/usr/bin/env bash
# The fingerprint of every input a scheduled fetch commits to main (run from suptracker/): the harvested reports, the fiches'
# grids (CONTENT files; of etat.csv only (code, status), it is rewritten with each reading date: Codex), the open days, the
# travel fares, the student-aid pages and the RNCP export. suptracker-data rebuilds after one of those fetches only when this
# differs from data/harvest_fingerprint.txt (the value of the last published warehouse): a fetch that changed nothing costs no
# build, and a fetch that changed something never leaves main with a warehouse older than its own data (red team J9).
set -euo pipefail
{
  git ls-files -s -- data/rapports/harvest data/fiches/champs.csv data/fiches/criteres.csv data/fiches/attendus.csv \
    data/fiches/identite.csv data/fiches/frais.csv data/fiches/textes.csv.gz \
    data/jpo/onisep data/jpo/sites/extraits.csv.gz data/jpo/concours/extraits.csv.gz \
    data/transports/tarifs_tgv.csv.gz data/transports/gares.csv.gz data/transports/carburants.csv.gz \
    data/aides data/rncp/export-fiches-csv.zip data/rncp/rome_toutes_donnees.zip
  cut -d, -f1,2 data/fiches/etat.csv 2>/dev/null || true
  cut -d, -f1,3 data/jpo/sites/etat.csv 2>/dev/null || true
  cut -d, -f1,3,5 data/jpo/concours/etat.csv 2>/dev/null || true
} | sha256sum | cut -d' ' -f1
