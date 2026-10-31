"""Second blind holdout (written after tuning on the first): harder phrasings."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_search as E  # noqa: E402
from eval_search import all_of, fili, has, loc  # noqa: E402

HOLDOUT2 = [
    ("je veux faire une prépa ECG à Lyon", all_of(has("fil_lib_voe_acc", "ECG"), loc("Lyon"))),
    ("licence de psychologie à Bordeaux", all_of(has("fil_lib_voe_acc", "Psychologie"), loc("Bordeaux"))),
    ("bts banque", has("fil_lib_voe_acc", "Banque")),
    ("BTS SIO Marseille", all_of(has("fil_lib_voe_acc", "Services informatiques"), loc("Marseille"))),
    ("IFSI La Réunion", all_of(fili("IFSI"), loc("Réunion"))),
    ("droit guadeloupe", all_of(has("fil_lib_voe_acc", "Droit"), loc("Guadeloupe"))),
    ("but techniques de commercialisation grenoble", all_of(has("fil_lib_voe_acc", "Techniques de commercialisation"), loc("Grenoble"))),
    ("prépa scientifique toulouse", all_of(has("form_lib_voe_acc", "scientifique"), loc("Toulouse"))),
    ("histoire de l'art", has("fil_lib_voe_acc", "Histoire de l'art")),
    ("informatique nancy", all_of(has("fil_lib_voe_acc", "Informatique"), loc("Nancy"))),
    ("engineering school lyon", all_of(fili("Ecole d'Ingénieur"), loc("Lyon"))),
    ("psychology paris", all_of(has("fil_lib_voe_acc", "Psychologie"), loc("Paris"))),
    ("dut gea", has("fil_lib_voe_acc", "Gestion des entreprises")),
    ("lettres modernes", has("fil_lib_voe_acc", "Lettres")),
    ("économie montpellier", all_of(has("fil_lib_voe_acc", "Econom"), loc("Montpellier"))),
    ("bts diététique", has("fil_lib_voe_acc", "Diététique")),
    ("staps nantes", all_of(has("fil_lib_voe_acc", "Activités Physiques"), loc("Nantes"))),
    ("geographie", has("fil_lib_voe_acc", "Géographie")),
    ("prepa ens", any_of := (lambda r: "ENS" in (r["fil_lib_voe_acc"] or ""))),
    ("sociologie lille", all_of(has("fil_lib_voe_acc", "Sociologie"), loc("Lille"))),
]

if __name__ == "__main__":
    E.GOLD[:] = HOLDOUT2
    sys.exit(E.main(sys.argv[1:]))
