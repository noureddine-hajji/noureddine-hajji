"""Blind holdout for search: queries never used while tuning (see eval_search.py for the gold set).
Same pass rule: >= 4 of the top 5 results satisfy the predicate."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_search as E  # noqa: E402
from eval_search import all_of, any_of, fili, has, loc  # noqa: E402

HOLDOUT = [
    ("bts commerce international", has("fil_lib_voe_acc", "Commerce international")),
    ("bts cg lille", all_of(has("fil_lib_voe_acc", "Comptabilité et gestion"), loc("Lille"))),
    ("but informatique", all_of(fili("BUT"), has("fil_lib_voe_acc", "Informatique"))),
    ("licence maths", all_of(fili("Licence"), has("fil_lib_voe_acc", "Mathématiques"))),
    ("PCSI lyon", all_of(has("fil_lib_voe_acc", "PCSI"), loc("Lyon"))),
    ("BCPST", has("fil_lib_voe_acc", "BCPST")),
    ("prépa véto", has("fil_lib_voe_acc", "BCPST")),
    ("école de commerce lille", all_of(fili("Ecole de Commerce"), loc("Lille"))),
    ("ifsi lyon", all_of(fili("IFSI"), loc("Lyon"))),
    ("licence histoire", all_of(fili("Licence"), has("fil_lib_voe_acc", "Histoire"))),
    ("LLCER anglais", has("fil_lib_voe_acc", "Langues, littératures et civilisations")),
    ("sciences de l'éducation", has("fil_lib_voe_acc", "Sciences de l'éducation")),
    ("ergothérapie", has("fil_lib_voe_acc", "Ergothérapeute")),
    ("psychomotricité", has("fil_lib_voe_acc", "Psychomotricien")),
    ("staps lyon", all_of(has("fil_lib_voe_acc", "Activités Physiques"), loc("Lyon"))),
    ("licence psycho paris", all_of(has("fil_lib_voe_acc", "Psychologie"), loc("Paris"))),
    ("eco gestion bordeaux", all_of(has("fil_lib_voe_acc", "Economie et gestion"), loc("Bordeaux"))),
    ("IUT GEA lyon", all_of(has("fil_lib_voe_acc", "Gestion des entreprises"), loc("Lyon"))),
    ("BUT GEII", has("fil_lib_voe_acc", "Génie électrique et informatique industrielle")),
    ("école d'architecture", has("fil_lib_voe_acc", "Architecture")),
    ("assistant social", has("fil_lib_voe_acc", "Assistant de service social")),
    ("éducateur spécialisé", has("fil_lib_voe_acc", "Educateur spécialisé")),
    ("BUT carrières juridiques", has("fil_lib_voe_acc", "Carrières juridiques")),
    ("prépa MP2I", has("fil_lib_voe_acc", "MP2I")),
    ("licence physique chimie", has("fil_lib_voe_acc", "Physique, chimie")),
    ("sciences politiques licence", all_of(fili("Licence"), has("fil_lib_voe_acc", "Science politique"))),
    ("pharmacie lille", all_of(fili("PASS", "Licence_Las"), loc("Lille"))),
    ("informatique rennes", all_of(has("fil_lib_voe_acc", "Informatique"), loc("Rennes"))),
    ("bts tourisme", has("fil_lib_voe_acc", "Tourisme")),
    ("licence anglais", has("fil_lib_voe_acc", "Langues")),
]

if __name__ == "__main__":
    E.GOLD[:] = HOLDOUT
    sys.exit(E.main(sys.argv[1:]))
