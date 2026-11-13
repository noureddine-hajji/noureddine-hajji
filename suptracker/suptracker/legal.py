"""Sprint Q1 (owner, 2026-11-13): the trust and compliance pages, ONE source for the server page and the app.

Pages: À propos, Contact, Mentions légales, Politique de confidentialité, Déclaration d'accessibilité. Each is served as an
indexable page at its own address (`/a-propos`…, rendered by the server, readable without JavaScript) and to the app
through `/api/page/<slug>` (same HTML). Owner's choices: the publisher is "M. N. HAJJI, à titre personnel" and also the
publication director; the contact is an on-site form (no address published, see contact.py); the tagline is TAGLINE.

Rules (scripts/redteam_conformite.py):
  - the legal notice names the publisher, the publication director, the host (name and postal address) and the licences
    of the data the site serves (generated from sources.py: every source "en_ligne" is listed, none is forgotten);
  - the privacy page names every third party the pages contact (host, analytics store, map tiles) and every kind of data
    kept, with its retention, read from the code's own constants (never retyped);
  - the accessibility statement does not claim conformity without an audit ("non conforme" in the RGAA sense), lists the
    known limits, the checks actually run, a contact and the Défenseur des droits;
  - vouvoiement everywhere, every stored string escaped.
"""
from __future__ import annotations

import html

from . import aide as AI
from . import analytics as A
from . import config
from . import contact as C
from . import sources as S

SITE = "SupCompass"
TAGLINE = "Les chiffres officiels de l'orientation post-bac, expliqués"
PUBLISHER = "M. N. HAJJI"
UPDATED = "13 novembre 2026"
HOST = {"name": "Vercel Inc.", "address": "440 N Barranca Ave #4133, Covina, CA 91723, États-Unis", "url": "https://vercel.com"}
STORE = {"name": "Upstash, Inc.", "country": "États-Unis", "url": "https://upstash.com"}
TILES = {"name": "OpenStreetMap Foundation", "country": "Royaume-Uni", "host": "tile.openstreetmap.org",
         "policy": "https://osmfoundation.org/wiki/Privacy_Policy"}
DEFENSEUR = "https://formulaire.defenseurdesdroits.fr/"
CNIL = "https://www.cnil.fr/fr/plaintes"
SLUGS = ("a-propos", "contact", "mentions-legales", "confidentialite", "accessibilite", "aide")       # "aide": sprint Q4 (aide.py)
FOOTER = (("aide", "Se faire aider"), ("a-propos", "À propos"), ("contact", "Contact"), ("mentions-legales", "Mentions légales"),
          ("confidentialite", "Confidentialité"), ("accessibilite", "Accessibilité : non conforme"))


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _years() -> str:
    return f"{min(config.YEARS)}–{max(config.YEARS)}"


def _link(url: str, text: str | None = None) -> str:
    return f'<a href="{esc(url)}" rel="noopener">{esc(text or url)}</a>'


def _sources() -> str:
    rows = [s for s in S.SOURCES if s.get("status") == "en_ligne"]
    items = "".join(f"<li>{esc(s['title'])} — {esc(s['producer'])} ({esc(s.get('licence') or 'licence non précisée')})"
                    f"{' : ' + _link(s['url'], 'source') if s.get('url') else ''}</li>" for s in rows)
    return f"<ul class=\"legal-list\">{items}</ul>"


def _contact_link() -> str:
    return '<a href="/contact">formulaire de contact</a>'


def a_propos() -> str:
    return f"""<h1>À propos de {SITE}</h1>
<p>{SITE} rend lisibles les chiffres publics de l'orientation après le bac : taux d'accès, profil des admis, rapports des jurys,
réussite, poursuite d'études et métiers. Les données viennent des campagnes Parcoursup {_years()} publiées par le ministère
(SIES) et d'autres sources officielles, citées sur chaque page.</p>
<h2>Qui fait {SITE} ?</h2>
<p>{SITE} est un projet personnel et indépendant, édité par {PUBLISHER} à titre personnel. Il n'est affilié ni à Parcoursup,
ni au ministère de l'Enseignement supérieur, ni à un établissement. Le site est gratuit, sans publicité, sans compte et sans
revente de données.</p>
<h2>Ce que {SITE} fait, et ne fait pas</h2>
<ul class="legal-list">
<li>Il reprend les indicateurs officiels tels qu'ils sont publiés, sans les recalculer. Un chiffre calculé par {SITE} est
toujours signalé comme une « estimation ».</li>
<li>Il montre des résultats des campagnes passées, <strong>jamais des chances d'admission</strong>.</li>
<li>Il ne remplace ni la fiche officielle de chaque formation sur Parcoursup, qui fait foi, ni l'avis de votre professeur
principal, d'un psychologue de l'Éducation nationale ou d'un centre d'information et d'orientation (CIO).</li>
</ul>
<h2>Méthode et sources</h2>
<p>La méthode de chaque chiffre est expliquée à côté de lui (bouton « i »), dans le <a href="/#/glossaire">glossaire</a> et
sur la page <a href="/#/qualite">Qualité des données</a>. La liste des sources et de leurs licences figure dans les
<a href="/mentions-legales">mentions légales</a>.</p>
<h2>Une erreur, une question ?</h2>
<p>Écrivez-nous avec le {_contact_link()}. Chaque signalement d'erreur est vérifié sur les données officielles.</p>
<p class="muted small">Page mise à jour le {UPDATED}.</p>"""


def contact() -> str:
    return f"""<h1>Écrire à {SITE} ou signaler une erreur</h1>
<p>Une erreur dans un chiffre ou un texte, une question, une suggestion : ce formulaire arrive directement à l'éditeur du site.
Aucune adresse e-mail n'est demandée ; vous pouvez en laisser une si vous souhaitez une réponse.</p>
<div id="contact-form"><noscript><p class="warn">Le formulaire a besoin de JavaScript. Activez-le pour envoyer un message.</p></noscript></div>
<h2>Ce qui est conservé</h2>
<p>Votre message, son sujet, la page concernée et, si vous l'indiquez, votre adresse pour vous répondre. Ni votre adresse IP,
ni votre navigateur ne sont enregistrés avec le message. Les messages sont supprimés automatiquement au bout de
{C.RETENTION_DAYS // 365 * 12} mois. Détails dans la <a href="/confidentialite">politique de confidentialité</a>.</p>
<p class="muted small">Pour une question sur votre dossier Parcoursup, adressez-vous à la plateforme Parcoursup : {SITE}
n'a aucun accès aux dossiers des candidats.</p>"""


def mentions_legales() -> str:
    return f"""<h1>Mentions légales</h1>
<h2>Éditeur du site</h2>
<p>{SITE} est édité par {PUBLISHER}, à titre personnel et non professionnel. Contact : {_contact_link()}.</p>
<p>Conformément à l'article 6 de la loi n° 2004-575 du 21 juin 2004 pour la confiance dans l'économie numérique, l'éditeur,
qui agit à titre non professionnel, a communiqué ses éléments d'identification à l'hébergeur.</p>
<h2>Directeur de la publication</h2>
<p>{PUBLISHER}.</p>
<h2>Hébergeur</h2>
<p>{esc(HOST['name'])}, {esc(HOST['address'])} — {_link(HOST['url'])}.</p>
<h2>Indépendance</h2>
<p>{SITE} est un site indépendant. Il n'est affilié ni à Parcoursup, service du ministère chargé de l'enseignement
supérieur, ni à ce ministère, ni à aucun établissement. Les noms de formations et d'établissements sont ceux des données
publiques.</p>
<h2>Données et licences</h2>
<p>Les chiffres affichés viennent des jeux de données publics suivants, réutilisés selon leur licence. Les indicateurs
officiels sont repris tels qu'ils sont publiés ; un chiffre calculé par {SITE} est signalé comme une estimation.</p>
{_sources()}
<p>Fond de carte : © les contributeurs d'OpenStreetMap (licence ODbL), affiché avec la bibliothèque Leaflet (licence BSD).
Polices de caractères hébergées par le site, sous licence SIL Open Font License.</p>
<h2>Responsabilité</h2>
<p>Les chiffres décrivent les campagnes passées ; ce ne sont pas des chances d'admission. La fiche de chaque formation sur
Parcoursup fait foi. Malgré le soin apporté aux vérifications, une erreur reste possible : signalez-la avec le
{_contact_link()}, elle sera corrigée.</p>
<h2>Propriété intellectuelle</h2>
<p>Les textes, la mise en page et les illustrations propres à {SITE} appartiennent à son éditeur, sauf mention contraire.
Les données publiques restent soumises à leur licence d'origine, citée ci-dessus.</p>
<h2>Vos données personnelles</h2>
<p>Voir la <a href="/confidentialite">politique de confidentialité</a>.</p>
<p class="muted small">Page mise à jour le {UPDATED}.</p>"""


def confidentialite() -> str:
    months = C.RETENTION_DAYS // 365 * 12
    return f"""<h1>Politique de confidentialité</h1>
<p>{SITE} fonctionne sans compte, sans cookie et sans publicité. Cette page dit précisément ce qui est envoyé, ce qui est
conservé, pendant combien de temps, et à qui.</p>
<h2>Responsable du traitement</h2>
<p>{PUBLISHER}, éditeur du site. Contact : {_contact_link()}.</p>
<h2>1. Votre profil et votre liste de vœux restent dans votre navigateur</h2>
<p>Votre situation, votre bac, vos spécialités, votre mention, votre moyenne, votre académie, votre lycée et votre liste de vœux
sont enregistrés <strong>uniquement dans votre navigateur</strong> (stockage local). {SITE} ne les conserve pas.</p>
<p>Pour lire les formations selon votre profil, la page envoie au serveur, dans l'adresse de la demande et sans aucun
identifiant, ce dont le calcul a besoin :</p>
<ul class="legal-list">
<li>la série, les spécialités et la tranche de mention, pour situer chaque formation ;</li>
<li>la ligne de votre bac technologique ou professionnel (série et spécialités, ou spécialité), seulement pour lire votre liste de vœux ;</li>
<li>votre académie, si vous l'avez indiquée, avec la recherche, le plan B, « Où je me situe » et votre liste de vœux, pour
présenter d'abord les formations de votre académie (pour « Je me réoriente », elle reste dans votre navigateur) ;</li>
<li>votre moyenne exacte, seulement avec la recherche avancée, pour son filtre de zone ;</li>
<li>les codes des formations de votre liste de vœux, pour la lire.</li>
</ul>
<p>Votre lycée n'est jamais envoyé. Ces demandes ne sont ni enregistrées ni reliées à vous par {SITE}. Vous pouvez tout effacer depuis « Mon profil » ou en vidant les données du site dans votre navigateur.</p>
<h2>2. Mesure d'audience, sans cookie</h2>
<p>{SITE} compte ses visites pour s'améliorer, sans cookie et sans rien lire sur votre appareil. Aucune adresse IP et aucun
identifiant de navigateur n'est enregistré : un visiteur est un pseudonyme calculé pour la journée, qui change chaque jour
et ne permet pas de relier deux visites. Seuls des compteurs par jour sont conservés, {A.RETENTION_DAYS} jours au plus. Les
recherches tapées sont normalisées (e-mails, adresses web et nombres masqués) et n'apparaissent dans les statistiques que si
au moins {A.K_ANON} visiteurs différents les ont tapées.</p>
<p>Cette mesure sert uniquement aux statistiques de {SITE}, n'est croisée avec aucun autre traitement et ne suit personne
d'un site à l'autre. Si votre navigateur envoie le signal « Ne pas me pister » (Do Not Track) ou Global Privacy Control,
aucune mesure n'est faite.</p>
<h2>3. Formulaire de contact</h2>
<p>Si vous écrivez avec le {_contact_link()}, sont conservés : le sujet choisi, votre message, la page et la formation
concernées, le jour d'envoi et, seulement si vous la donnez, votre adresse e-mail pour vous répondre. Ni votre adresse IP,
ni votre navigateur ne sont enregistrés avec le message. Ces informations servent uniquement à vous répondre et à corriger
le site (intérêt légitime de l'éditeur). Elles sont supprimées automatiquement au bout de {months} mois. Pour limiter les
abus, un compteur anonyme du nombre de messages envoyés dans la journée est gardé deux jours.</p>
<p>Si vous avez moins de 15 ans, demandez l'accord d'un parent avant de laisser votre adresse e-mail.</p>
<h2>4. Carte des formations</h2>
<p>Quand vous ouvrez la carte, votre navigateur télécharge le fond de carte auprès des serveurs de
{esc(TILES['name'])} ({esc(TILES['country'])}), qui voient alors votre adresse IP, selon
{_link(TILES['policy'], 'leur politique de confidentialité')}. La liste des formations fonctionne sans la carte. La
recherche autour d'une ville se fait dans votre navigateur : votre position n'est jamais envoyée.</p>
<h2>5. Hébergement et prestataires</h2>
<ul class="legal-list">
<li><strong>{esc(HOST['name'])}</strong> ({_link(HOST['url'], 'vercel.com')}), hébergeur : comme tout hébergeur, il
reçoit l'adresse IP et la page demandée à chaque visite et peut les garder brièvement dans ses journaux techniques.</li>
<li><strong>{esc(STORE['name'])}</strong> ({esc(STORE['country'])}), base de données qui conserve les compteurs d'audience et
les messages du formulaire.</li>
</ul>
<p>Ces prestataires peuvent traiter des données hors de l'Union européenne ; ces transferts sont encadrés par les garanties
prévues dans leurs conditions (clauses contractuelles types de la Commission européenne ou cadre de protection des données
UE–États-Unis). {SITE} n'utilise aucun autre service tiers : pas de réseau social, pas de régie publicitaire, pas d'outil de
mesure externe, polices de caractères hébergées par le site.</p>
<h2>6. Vos droits</h2>
<p>Vous pouvez demander l'accès à vos données, leur rectification ou leur effacement, et vous opposer à leur traitement, avec
le {_contact_link()}. Comme aucun message n'est relié à une identité, indiquez le jour d'envoi et quelques mots de votre
message pour qu'il soit retrouvé. Si vous estimez que vos droits ne sont pas respectés, vous pouvez saisir la CNIL :
{_link(CNIL, 'cnil.fr')}.</p>
<p class="muted small">Page mise à jour le {UPDATED}.</p>"""


def accessibilite() -> str:
    return f"""<h1>Déclaration d'accessibilité</h1>
<p>{PUBLISHER} s'engage à rendre {SITE} accessible à toutes et à tous, y compris avec un lecteur d'écran, au clavier seul,
avec un zoom important ou sur un petit écran. Cette déclaration s'applique à l'ensemble du site.</p>
<h2>État de conformité</h2>
<p>{SITE} <strong>n'a pas encore fait l'objet d'un audit de conformité</strong> au référentiel général d'amélioration de
l'accessibilité (RGAA 4.1). En l'absence d'audit, il est déclaré <strong>non conforme</strong> au sens du RGAA, même si
le site vise le niveau AA des règles internationales WCAG 2.1.</p>
<h2>Ce qui est vérifié à chaque modification</h2>
<ul class="legal-list">
<li>Un contrôle automatique (outil axe-core) des règles WCAG 2.1 A et AA sur les pages principales, en thème clair et
sombre, sur grand écran et sur téléphone.</li>
<li>Des contrôles programmés : un seul titre principal par page, titres dans l'ordre, nom de page annoncé et focus placé
sur le titre après chaque navigation, lien d'évitement, contrastes d'au moins 4,5:1 pour le texte, champs de formulaire
étiquetés, affichage sans défilement horizontal à 320 pixels de large, animations réduites si vous le demandez.</li>
</ul>
<h2>Limites connues</h2>
<ul class="legal-list">
<li>La carte des formations (fond OpenStreetMap) est difficile à utiliser sans la vue : la liste des formations, à côté,
donne les mêmes informations et se parcourt au clavier.</li>
<li>Les graphiques ont un nom accessible et, le plus souvent, un tableau des mêmes chiffres ; certains détails ne sont
lisibles qu'au survol.</li>
<li>Les rapports des jurys sont des documents PDF publiés par les formations sur Parcoursup : leur accessibilité ne
dépend pas de {SITE}.</li>
<li>Le site n'a pas encore été testé de bout en bout avec un lecteur d'écran (NVDA, VoiceOver) : c'est prévu.</li>
</ul>
<h2>Technologies utilisées</h2>
<p>HTML5, CSS, JavaScript, SVG.</p>
<h2>Retour d'information et contact</h2>
<p>Si vous n'arrivez pas à accéder à un contenu ou à un service, écrivez avec le {_contact_link()} : une alternative
accessible vous sera proposée et le défaut sera corrigé.</p>
<h2>Voies de recours</h2>
<p>Si vous signalez un défaut d'accessibilité sans obtenir de réponse satisfaisante, vous pouvez saisir le Défenseur des
droits : {_link(DEFENSEUR, 'formulaire en ligne')}, un délégué près de chez vous, ou un courrier gratuit, sans timbre, à
Défenseur des droits, Libre réponse 71120, 75342 Paris CEDEX 07.</p>
<p class="muted small">Déclaration établie le {UPDATED}.</p>"""


PAGES = {
    "a-propos": ("À propos", "Qui édite SupCompass, ce que le site fait et ne fait pas, sa méthode et ses sources.", a_propos),
    "contact": ("Contact et signalement d'erreur", "Écrire à SupCompass ou signaler une erreur dans un chiffre ou un texte.", contact),
    "mentions-legales": ("Mentions légales", "Éditeur, hébergeur, sources de données et licences de SupCompass.", mentions_legales),
    "confidentialite": ("Politique de confidentialité", "Ce que SupCompass envoie, conserve et pendant combien de temps : "
                        "sans compte, sans cookie, sans publicité.", confidentialite),
    "accessibilite": ("Déclaration d'accessibilité", "État de conformité de SupCompass au RGAA, limites connues et recours.",
                      accessibilite),
    "aide": ("Se faire aider pour choisir", "Les services gratuits qui aident à choisir ses études : professeur principal, "
             "psychologue de l'Éducation nationale, CIO, Mon orientation en ligne, numéro vert Parcoursup.", AI.page),
}


def page(slug: str) -> dict | None:
    p = PAGES.get(slug)
    if p is None:
        return None
    title, description, body = p
    return {"slug": slug, "title": title, "description": description, "html": body()}


def body(slug: str) -> str:
    """The server-rendered page: the same HTML the app shows, kept if the app cannot load (data-seo)."""
    p = page(slug)
    return f'<article class="card legal" data-seo="{esc(slug)}">{p["html"]}</article>'


def footer() -> str:
    return "".join(f'<a href="/{s}">{esc(t)}</a>' for s, t in FOOTER)          # spaced by the flex gap (no orphan "·")
