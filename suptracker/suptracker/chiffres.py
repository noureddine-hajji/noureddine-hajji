"""Owner, 2026-11-16: "Nos chiffres et ceux de Parcoursup", why SupCompass never gives a probability and how its figures differ
from what the Parcoursup fiche shows. One source for the page and the app, served like the trust pages (legal.py):
`/nos-chiffres` (indexable, readable without JavaScript) and `/api/page/nos-chiffres` (`#/info/nos-chiffres`).

What the fiche shows was read on the live fiches kept in data/rapports/live/fiches_live/ (2026-11-14): "Les chiffres
globaux d'accès à cette formation en <année>" (every candidate: applied, ranked, could receive a proposal, chose the
formation) and "En savoir plus sur l'accès à la formation selon mon profil" (lycéens de terminale only, by type of bac,
"pas comparables" with the first block, as the fiche itself says). The page says only that, and sends to the fiche.

Rules (scripts/redteam_langage.py, scripts/redteam_conformite.py): vouvoiement, short sentences, no jargon a student would not
know, never "chance" except to say the site does not give one, every string escaped, links inside the site only.
"""
from __future__ import annotations

import html

CHECKED = "16 novembre 2026"


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def page() -> str:
    return f"""<h1>Nos chiffres et ceux de Parcoursup</h1>
<p>Sur la fiche de chaque formation, Parcoursup publie ses propres chiffres. SupCompass part des mêmes données publiques. Voici
ce qui est pareil, ce qui change, et pourquoi le site ne donne jamais de probabilité d'admission.</p>
<h2>Ce que montre la fiche Parcoursup</h2>
<ul>
<li>Les chiffres de l'année passée pour tous les candidats : combien ont postulé, combien ont été classés, combien ont pu
recevoir une proposition, combien ont choisi la formation.</li>
<li>Un bloc « accès à la formation selon mon profil ». Il ne compte que les lycéens de terminale, selon leur type de bac. La
fiche précise que ces chiffres ne se comparent pas avec ceux du premier bloc.</li>
</ul>
<h2>Pourquoi SupCompass ne donne pas de probabilité</h2>
<p>Les données publiques décrivent les admis des années passées. Elles ne disent rien de votre dossier : vos notes, les
appréciations de vos professeurs et votre projet ne sont dans aucun fichier public.</p>
<p>Un pourcentage « de chances » ferait croire à une précision qui n'existe pas. SupCompass montre donc des parts d'admis et
des repères : sécurité, cible ou ambitieux. Chaque chiffre dit d'où il vient. Un chiffre calculé par le site porte toujours la
mention « estimation ».</p>
<h2>Ce que SupCompass ajoute</h2>
<ul>
<li>Plusieurs années : les campagnes 2022 à 2025 côte à côte, et une fourchette pour la prochaine campagne.</li>
<li>Le rapport public du jury, quand la formation l'a publié : les candidats de votre paire de spécialités, avec les
effectifs.</li>
<li>La grille d'analyse des candidatures de la fiche, réunie sur la page de la formation.</li>
<li>Ce qui aide à décider : un plan B, votre liste de vœux lue d'un coup, le coût de la vie sur place et les aides.</li>
</ul>
<h2>Si deux chiffres ne disent pas la même chose</h2>
<ul>
<li>Ils ne comptent pas toujours les mêmes personnes : tous les candidats, ou seulement les lycéens de terminale.</li>
<li>Ils ne portent pas toujours sur la même année. SupCompass indique l'année de chaque chiffre.</li>
<li>Le taux d'accès officiel est repris tel quel. Nos estimations sont signalées comme telles.</li>
</ul>
<p>En cas de doute, la fiche Parcoursup de la formation fait foi. Pour en parler à quelqu'un, voyez
<a href="/#/info/aide">Se faire aider</a>.</p>
<p class="muted small">Contenu de la fiche Parcoursup vérifié le {esc(CHECKED)}. La présentation de la fiche peut changer
d'une campagne à l'autre.</p>"""
