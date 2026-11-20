"""Owner, 2026-11-17: « Comment on calcule la robustesse 2035 », the method page of the robustesse indicator (robustesse.py for the
jobs, robustesse_formation.py for the formations) and the CHANGELOG of the model versions. One source for the page and the app,
served like the trust pages (legal.py): `/robustesse` (indexable, readable without JavaScript) and `/api/page/robustesse`
(`#/info/robustesse`).

Rules (scripts/redteam_methode.py, redteam_langage.py, redteam_conformite.py): vouvoiement, short sentences, never a chance or a
promise, the weights and thresholds READ from the modules' constants (never typed twice), every model version of the modules in
the changelog, every string escaped.
"""
from __future__ import annotations

import html

from . import robustesse as RJ
from . import robustesse_formation as RF

# every version of the model, newest first: (version, date, what changed). The modules' MODEL_VERSION must be listed.
CHANGELOG = (
    ("2027.5-f", "20 novembre 2026",
     "Les offres en apprentissage sans statistiques reprennent la note de leur diplôme quand toutes les formations de ce diplôme "
     "ont la même. Une vingtaine d'intitulés de BTS sont maintenant reliés à leur fiche Onisep (option renommée, abréviation). "
     "Cinq métiers sans code reçoivent celui d'une fiche voisine, validé à la main."),
    ("2027.4-f", "18 novembre 2026",
     "Seuil revu : une licence est notée par les masters de son université dès qu'au moins un master documenté par l'Onisep "
     "mène à un métier. Sinon, elle est notée sur ses propres métiers, ou à défaut sur ceux de sa famille de formations."),
    ("2027.3-f", "18 novembre 2026",
     "Une licence n'est notée par les masters de son université que s'ils mènent à assez de métiers : au moins deux masters ou "
     "cinq métiers. Sinon, elle est notée sur ses propres métiers, et la page le dit. Un BUT ne lit plus que la fiche RNCP de son "
     "propre parcours."),
    ("2027.2 / 2027.2-f", "17 novembre 2026",
     "Contrôle avec l'usage réel de l'IA (Anthropic Economic Index) : il fait baisser la confiance quand il ne concorde pas avec "
     "l'OIT, sans changer le score. Second repère des formations, parmi toutes les formations."),
    ("2027.1-f", "17 novembre 2026",
     "Première version pour les formations : métiers visés, insertion, diversité des débouchés, compétences transférables."),
    ("2027.1", "17 novembre 2026",
     "Première version pour les métiers : résistance à l'IA et demande d'ici 2035, trois scénarios, contrôles avec l'OCDE et "
     "les compétences vertes (ESCO), repère en trois niveaux."),
)


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def pc(x: float) -> str:
    return f"{round(100 * x):d} %"


def page() -> str:
    lo, hi = pc(RJ.REPERE_SHARE), pc(1 - RJ.REPERE_SHARE)
    versions = "".join(f"<li><strong>{esc(v)}</strong> ({esc(d)}) : {esc(t)}</li>" for v, d, t in CHANGELOG)
    return f"""<h1>Comment on calcule la robustesse 2035</h1>
<p>La robustesse 2035 est une estimation du modèle de SupCompass. Elle dit si un métier, ou les métiers auxquels mène une
formation, devraient garder de la valeur sur le marché du travail entre 2030 et 2035. Ce n'est ni une prévision pour une
personne, ni une promesse d'emploi, ni une chance d'admission.</p>
<h2>Pour un métier</h2>
<ul>
<li>La résistance à l'IA générative compte pour {pc(RJ.W_IA / (RJ.W_IA + RJ.W_DEM))} du score. Elle part de l'exposition des tâches
publiée par l'OIT. Elle tient compte de la part des usages où l'IA aide le travail au lieu de le faire à la place (Anthropic
Economic Index).</li>
<li>La demande d'ici 2035 compte pour {pc(RJ.W_DEM / (RJ.W_IA + RJ.W_DEM))}. Elle réunit les postes à pourvoir selon le Cedefop
({pc(RJ.W_CED)}), selon « Les métiers en 2030 » ({pc(RJ.W_M2030)}) et les recrutements jugés difficiles en 2026 ({pc(RJ.W_BMO)}).</li>
<li>Trois scénarios sont calculés : IA accélérée, central, transition bas-carbone. La page montre le score du milieu, avec
l'écart entre le moins et le plus favorable.</li>
</ul>
<h2>Pour une formation</h2>
<ul>
<li>Les métiers visés comptent pour {pc(RF.W_JOBS)}. Ce sont ceux de la fiche Onisep du diplôme. Pour une licence, ce sont ceux
des masters de la même université, pesés par leurs admis, dès qu'au moins un de ces masters, décrit par l'Onisep, mène à un
métier. Sinon, ce sont les métiers de la licence seule, ou à défaut ceux de sa famille de formations.</li>
<li>L'insertion après le diplôme de sortie compte pour {pc(RF.W_INS)}, quand elle est publiée.</li>
<li>La diversité des débouchés compte pour {pc(RF.W_DIV)}, et les compétences transférables pour {pc(RF.W_COMP)}. Les compétences
viennent de la fiche RNCP du diplôme et du référentiel ROME 4.0 de France Travail.</li>
<li>Un élément absent n'est jamais remplacé par une valeur inventée : le score se calcule sur les autres, et la confiance
baisse.</li>
</ul>
<h2>Ce que la page montre en premier</h2>
<p>Les scores sont proches les uns des autres : un ou deux points d'écart ne veulent rien dire. La page montre donc d'abord un
repère en trois niveaux : parmi les {lo} les plus robustes, dans la moyenne, ou parmi les {lo} les moins robustes. Pour un
métier, le repère le compare aux autres métiers estimés. Pour une formation, il y a deux repères : un dans sa filière, un parmi
toutes les formations. Le score reste dans « Détail du calcul ».</p>
<p>Quand les formations d'une filière mènent toutes aux mêmes métiers, elles ne sont pas classées entre elles. Quand les métiers
comptés arrivent après d'autres études, la page le dit.</p>
<h2>La confiance</h2>
<p>La confiance est la plus faible de quatre mesures : la fraîcheur des sources, la part de liens observés, l'accord entre les
sources et la part des éléments présents. En dessous de {esc(str(RJ.CONF_LOW).replace(".", ","))} sur 1, la page dit « données
insuffisantes » et ne montre aucun chiffre.</p>
<p>Deux contrôles ne changent jamais le score. La mesure de l'OCDE et l'usage réel de l'IA sont comparés à l'OIT par le rang
du métier. Au-delà de {round(100 * RJ.RANK_GAP)} points d'écart entre les deux places, la confiance baisse, sans descendre sous {esc(str(RJ.RANK_FLOOR).replace(".", ","))}.</p>
<h2>Dans « Mes vœux »</h2>
<p>Chaque vœu montre côte à côte sa zone pour votre profil et ses repères de robustesse. Les deux ne sont jamais réunis en une
seule note : l'une parle de l'admission, l'autre des métiers d'après.</p>
<h2>Dans la recherche</h2>
<p>La recherche de formations propose deux filtres : la robustesse dans la filière et parmi toutes les formations. Ce sont des
filtres : la liste n'est jamais triée par ces repères.</p>
<h2>À côté de l'insertion publiée</h2>
<p>Pour un BTS ou un BUT, la page de la formation montre aussi l'insertion publiée par le ministère, dans un encadré à part. Ces
chiffres n'entrent pas dans le score : ils décrivent des promotions passées, quelques mois après le diplôme.</p>
<h2>Les versions du modèle</h2>
<ul>
{versions}
</ul>
<p class="muted small">Version actuelle : {esc(RJ.MODEL_VERSION)} pour les métiers, {esc(RF.MODEL_VERSION)} pour les formations.
Les sources et leurs années sont données sur chaque page, sous « D'où vient ce chiffre ? ». Pour en parler à quelqu'un, voyez
<a href="/#/info/aide">Se faire aider</a>.</p>"""
