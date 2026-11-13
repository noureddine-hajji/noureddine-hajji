"""Sprint Q4 (owner, 2026-11-13): "Se faire aider", the people who help a student choose, one source for the page and the app.

SupCompass shows figures; it does not advise one student. The red-team evaluation (Psy-EN expert) asked for a way to a
human: this page lists the official, free services, each with who it is for, how to reach it and its official address.
Served like the trust pages (legal.py): `/aide` (indexable, readable without JavaScript) and `/api/page/aide` (`#/info/aide`).

Rules (scripts/redteam_langage.py):
  - only official services (public bodies), each with an https address on an official host (OFFICIAL_HOSTS);
  - phone numbers as published by the service, checked against the red team's own table; a `tel:` link dials the
    number shown; opening hours are NOT printed (they change during the campaign): the page sends to the service's site;
  - every fact was checked on the services' sites on CHECKED; SupCompass never claims to answer itself;
  - vouvoiement, short sentences, every string escaped.
"""
from __future__ import annotations

import html

CHECKED = "13 novembre 2026"
OFFICIAL_HOSTS = ("www.parcoursup.gouv.fr", "www.onisep.fr", "www.education.gouv.fr", "www.filsantejeunes.com",
                  "www.monparcourshandicap.gouv.fr")

# (id, title, who it is for, what to do, phone (shown, dialled), address, link text)
SERVICES = (
    {"id": "lycee", "titre": "Au lycée : votre professeur principal et le psychologue de l'Éducation nationale",
     "pour": "Les élèves de seconde, de première et de terminale.",
     "comment": "En terminale, vous avez deux professeurs principaux. Le psychologue de l'Éducation nationale (Psy-EN) "
                "reçoit au lycée ou au CIO : demandez un rendez-vous à la vie scolaire. Ils connaissent votre dossier et "
                "les formations de votre région.",
     "tel": None, "url": None, "lien": None},
    {"id": "cio", "titre": "Près de chez vous : un centre d'information et d'orientation (CIO)",
     "pour": "Les élèves, les étudiants et les adultes. C'est gratuit.",
     "comment": "Des psychologues de l'Éducation nationale vous reçoivent pour parler de votre projet. Cherchez le CIO le plus "
                "proche dans l'annuaire du ministère, puis appelez-le pour connaître ses horaires.",
     "tel": None, "url": "https://www.education.gouv.fr/annuaire?keywords=Centre+d%27information+et+d%27orientation",
     "lien": "Trouver un CIO (annuaire de l'Éducation nationale)"},
    {"id": "moel", "titre": "À distance : Mon orientation en ligne (Onisep)",
     "pour": "Tout le monde, les parents aussi. C'est gratuit.",
     "comment": "Des conseillers de l'Onisep répondent à vos questions sur les formations et les métiers, par téléphone, par "
                "tchat ou par courriel. L'appel n'est pas surtaxé.",
     "tel": ("01 77 77 12 25", "+33177771225"), "url": "https://www.onisep.fr/mon-orientation-en-ligne",
     "lien": "Mon orientation en ligne : tchat, courriel et horaires"},
    {"id": "parcoursup", "titre": "Pour une question sur Parcoursup : le numéro vert et la messagerie",
     "pour": "Les candidats et leurs parents, pendant la procédure.",
     "comment": "Le numéro vert est gratuit. Depuis l'étranger, composez le +33 800 400 070. Pour une question sur votre "
                "dossier, écrivez aussi par la rubrique « Contact » de votre dossier Parcoursup.",
     "tel": ("0 800 400 070", "0800400070"),
     "url": "https://www.parcoursup.gouv.fr/faq/thematiques/aides-et-accompagnement/accompagnement-pendant-la-procedure",
     "lien": "Parcoursup : aide et horaires du numéro vert"},
    {"id": "handicap", "titre": "Avec un handicap ou un trouble de santé",
     "pour": "Les élèves qui ont besoin d'un aménagement pour leurs études.",
     "comment": "Chaque formation a un référent handicap : son contact est sur la fiche Parcoursup de la formation. Le site "
                "officiel Mon parcours handicap dit à qui s'adresser.",
     "tel": None, "url": "https://www.monparcourshandicap.gouv.fr/etudes-superieures/orientation-quels-sont-vos-interlocuteurs",
     "lien": "Mon parcours handicap : vos interlocuteurs"},
    {"id": "ecoute", "titre": "Si c'est trop lourd en ce moment : Fil Santé Jeunes",
     "pour": "Les jeunes de 12 à 25 ans. C'est gratuit et anonyme.",
     "comment": "Le stress des choix et des résultats arrive à beaucoup d'élèves. Des professionnels vous écoutent au téléphone "
                "ou par tchat, sans jugement.",
     "tel": ("0 800 235 236", "0800235236"), "url": "https://www.filsantejeunes.com/", "lien": "Fil Santé Jeunes"},
)


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _service(s: dict) -> str:
    tel = f'<p class="aide-tel"><a href="tel:{esc(s["tel"][1])}">{esc(s["tel"][0])}</a></p>' if s["tel"] else ""
    link = f'<p><a href="{esc(s["url"])}" rel="noopener">{esc(s["lien"])}</a></p>' if s["url"] else ""
    return (f'<section class="aide-service" id="aide-{esc(s["id"])}"><h2>{esc(s["titre"])}</h2>'
            f'<p><strong>Pour qui :</strong> {esc(s["pour"])}</p><p>{esc(s["comment"])}</p>{tel}{link}</section>')


def page() -> str:
    return f"""<h1>Se faire aider pour choisir</h1>
<p>SupCompass montre les chiffres des années passées. Il ne connaît ni vous, ni votre dossier. Pour construire votre liste de
vœux, parlez-en à une personne : c'est gratuit, et ces services sont faits pour ça.</p>
<p>Avant un rendez-vous, préparez <a href="/#/voeux">votre liste Mes vœux</a> : vous pouvez la partager ou l'imprimer pour la
montrer.</p>
{''.join(_service(s) for s in SERVICES)}
<p class="muted small">Coordonnées vérifiées sur les sites officiels le {CHECKED}. Les horaires changent pendant l'année :
consultez le site de chaque service avant d'appeler. SupCompass n'est lié à aucun de ces services.</p>"""
