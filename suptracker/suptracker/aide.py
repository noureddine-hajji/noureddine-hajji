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

CHECKED = "15 novembre 2026"
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
    {"id": "sans-proposition", "titre": "Sans proposition à la fin de la phase principale : la phase complémentaire, puis la CAES",
     "pour": "Les candidats qui n'ont reçu aucune proposition d'admission.",
     "comment": "Pendant la phase complémentaire, vous pouvez faire de nouveaux vœux dans les formations qui ont encore des "
                "places. Sans proposition ensuite, demandez l'aide de la commission d'accès à l'enseignement supérieur (CAES) "
                "de votre académie, depuis votre dossier. Elle cherche avec vous une formation proche de votre projet.",
     "tel": None,
     "url": "https://www.parcoursup.gouv.fr/contenus/les-solutions-si-vous-n-avez-pas-recu-de-proposition-d-admission-3456",
     "lien": "Parcoursup : les solutions si vous n'avez reçu aucune proposition"},
    {"id": "ecoute", "titre": "Si c'est trop lourd en ce moment : Fil Santé Jeunes",
     "pour": "Les jeunes de 12 à 25 ans. C'est gratuit et anonyme.",
     "comment": "Le stress des choix et des résultats arrive à beaucoup d'élèves. Des professionnels vous écoutent au téléphone "
                "ou par tchat, sans jugement.",
     "tel": ("0 800 235 236", "0800235236"), "url": "https://www.filsantejeunes.com/", "lien": "Fil Santé Jeunes"},
)


# ---- audit PR 6 (owner, 2026-11-24): an adult who goes back to studies or changes jobs ----
# The services that help an adult. Every link is an official page READ by the suptracker-aides workflow (data/aides, the
# development sandbox cannot reach them), or a link that such a page prints (`via`): scripts/redteam_reprise.py checks both
# against data/aides (status 200, the page's own title). Our own words, short: who it is for and what it does, never an amount,
# an age limit or a condition the student must meet (the official page says it: « selon votre situation »).
ADULTES_CHECKED = "24 novembre 2026"
SP = "https://www.service-public.gouv.fr/particuliers/vosdroits/"
ADULTES = (
    {"id": "cep", "titre": "Faire le point avec un conseiller : le conseil en évolution professionnelle (CEP)",
     "pour": "Toute personne qui veut faire le point sur sa situation professionnelle. C'est gratuit.",
     "comment": "Un conseiller vous aide à préciser votre projet, par exemple une reconversion. Il vérifie avec vous qu'il est "
                "réalisable et vous aide à trouver un financement.",
     "liens": ({"texte": "Service Public : le conseil en évolution professionnelle", "url": SP + "F32457"},
               {"texte": "Trouver son opérateur CEP", "url": SP + "R60574"})},
    {"id": "mission-locale", "titre": "Pour les jeunes : la mission locale",
     "pour": "Les jeunes, selon leur âge et leur situation : le site officiel le précise.",
     "comment": "Elle vous accueille, vous informe et vous accompagne vers l'emploi ou vers une formation.",
     "liens": ({"texte": "Service Public : ce que peut faire un jeune sorti de l'école", "url": SP + "F32846"},
               {"texte": "Trouver une mission locale", "url": "https://www.unml.info/le-reseau/annuaire/", "via": SP + "F32846"})},
    {"id": "france-travail", "titre": "Si vous cherchez un emploi : France Travail",
     "pour": "Les personnes inscrites comme demandeurs d'emploi.",
     "comment": "Votre compte personnel de formation peut financer une formation. Une rémunération est possible pendant une "
                "formation agréée, selon votre situation.",
     "liens": ({"texte": "Service Public : le CPF d'un demandeur d'emploi", "url": SP + "F12382"},
               {"texte": "Service Public : une rémunération pendant la formation", "url": SP + "F760"},
               {"texte": "Trouver son agence France Travail", "url": "https://www.francetravail.fr/annuaire/", "via": SP + "F32846"})},
    {"id": "cpf", "titre": "Financer une formation : le compte personnel de formation (CPF)",
     "pour": "Toute personne, dès son entrée sur le marché du travail.",
     "comment": "Il sert à suivre une formation tout au long de la vie active, y compris en période de chômage. Le montant de "
                "votre compte est sur le site officiel Mon compte formation.",
     "liens": ({"texte": "Service Public : le CPF d'un salarié du secteur privé", "url": SP + "F10705"},
               {"texte": "Mon compte formation", "url": SP + "R46472", "via": SP + "F10705"})},
    {"id": "ptp", "titre": "Changer de métier quand on est salarié : le projet de transition professionnelle (PTP)",
     "pour": "Les salariés, sous conditions d'ancienneté : le site officiel les précise.",
     "comment": "Le salarié s'absente de son poste pour suivre une formation certifiante, et il reste rémunéré. La demande de "
                "prise en charge se fait auprès de l'association Transitions Pro de sa région.",
     "liens": ({"texte": "Service Public : le projet de transition professionnelle", "url": SP + "F14018"},)},
    {"id": "vae", "titre": "Faire reconnaître votre expérience : la validation des acquis de l'expérience (VAE)",
     "pour": "Toute personne qui a une expérience, professionnelle ou non.",
     "comment": "Votre expérience peut être reconnue par un diplôme ou par un titre professionnel.",
     "liens": ({"texte": "Service Public : la validation des acquis de l'expérience", "url": SP + "F2401"},)},
)
# the official page each link was read on, and the words its title must carry (red team RP3)
ADULTES_TITRES = {SP + "F32457": "Conseil en évolution professionnelle (CEP)", SP + "R60574": "Trouver son opérateur CEP",
                  SP + "F32846": "Que peut faire un jeune de plus de 16 ans déscolarisé et sans diplôme ?",
                  SP + "F12382": "Compte personnel de formation (CPF) d'un demandeur d'emploi",
                  SP + "F760": "aide de France Travail pendant sa formation",
                  SP + "F10705": "Compte personnel de formation (CPF) d'un salarié du secteur privé",
                  SP + "F14018": "Projet de transition professionnelle (PTP)",
                  SP + "F2401": "Validation des acquis de l'expérience (VAE)"}
ADULTES_INTRO = ("Vous reprenez des études ou vous changez de métier : ces services publics gratuits vous accompagnent. Les "
                 "conditions d'accès d'une formation sont sur sa fiche Parcoursup, qui fait foi.")


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _service(s: dict) -> str:
    tel = f'<p class="aide-tel"><a href="tel:{esc(s["tel"][1])}">{esc(s["tel"][0])}</a></p>' if s["tel"] else ""
    link = f'<p><a href="{esc(s["url"])}" rel="noopener">{esc(s["lien"])}</a></p>' if s["url"] else ""
    return (f'<section class="aide-service" id="aide-{esc(s["id"])}"><h2>{esc(s["titre"])}</h2>'
            f'<p><strong>Pour qui :</strong> {esc(s["pour"])}</p><p>{esc(s["comment"])}</p>{tel}{link}</section>')


def _adulte(s: dict) -> str:
    links = "".join(f'<li><a href="{esc(x["url"])}" rel="noopener">{esc(x["texte"])}</a></li>' for x in s["liens"])
    return (f'<section class="aide-adulte" id="aide-{esc(s["id"])}"><h3>{esc(s["titre"])}</h3>'
            f'<p><strong>Pour qui :</strong> {esc(s["pour"])}</p><p>{esc(s["comment"])}</p><ul>{links}</ul></section>')


def adultes_html() -> str:
    return (f'<h2 id="aide-adultes">Vous reprenez des études ou vous changez de métier</h2><p>{esc(ADULTES_INTRO)}</p>'
            f'{"".join(_adulte(s) for s in ADULTES)}<p class="muted small">Pages officielles lues le {ADULTES_CHECKED}.</p>')


def page() -> str:
    return f"""<h1>Se faire aider pour choisir</h1>
<p>SupCompass montre les chiffres des années passées. Il ne connaît ni vous, ni votre dossier. Pour construire votre liste de
vœux, parlez-en à une personne : c'est gratuit, et ces services sont faits pour ça.</p>
<p>Avant un rendez-vous, préparez <a href="/#/voeux">votre liste Mes vœux</a> : vous pouvez la partager ou l'imprimer pour la
montrer.</p>
{''.join(_service(s) for s in SERVICES)}
{adultes_html()}
<p class="muted small">Coordonnées vérifiées sur les sites officiels le {CHECKED}. Les horaires changent pendant l'année :
consultez le site de chaque service avant d'appeler. SupCompass n'est lié à aucun de ces services.</p>"""
