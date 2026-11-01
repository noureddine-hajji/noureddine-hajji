"""A5 glossary (V1): the words of Parcoursup and of the statistics the site shows, in plain French
for a Terminale student. Each entry can point to the detailed method (METHODOLOGY key)."""
from __future__ import annotations

GLOSSARY = {
    "voeu": ("Vœu", "Une demande d'admission que tu fais sur Parcoursup pour une formation. Tu peux formuler jusqu'à "
             "10 vœux (hors sous-vœux). Les chiffres de candidatures sont des vœux, pas des personnes : un même élève "
             "est compté dans chaque formation demandée.", None),
    "sous_voeu": ("Sous-vœu", "Un choix à l'intérieur d'un vœu multiple (par exemple plusieurs écoles d'un même concours "
                  "commun). Les candidatures d'un sous-vœu sont partagées avec les autres et ne s'additionnent pas.", "subwish"),
    "phase_principale": ("Phase principale", "La période où les formations envoient leurs propositions d'admission, de "
                         "fin mai à mi-juillet. La phase complémentaire, ensuite, concerne les places restées libres.", "timing"),
    "proposition": ("Proposition d'admission", "Une réponse « oui » ou « oui si » d'une formation à un vœu. L'élève peut "
                    "l'accepter ou la refuser ; les admis sont ceux qui ont accepté.", None),
    "admis": ("Admis", "Les candidats qui ont accepté définitivement la proposition d'une formation (phase principale et "
              "complémentaire).", None),
    "taux_acces": ("Taux d'accès", "Indicateur officiel publié par le ministère : la part des candidats de la phase "
                   "principale dont le rang de classement était au moins aussi bon que celui du dernier candidat appelé. "
                   "Ce n'est pas ta chance personnelle d'être admis.", "taux_acces_ens"),
    "neo_bachelier": ("Néo-bachelier", "Un élève qui passe le bac l'année de sa candidature (par opposition à un étudiant "
                      "déjà dans le supérieur qui se réoriente).", "mentions"),
    "mention": ("Mention au bac", "Assez bien (12 à 14), bien (14 à 16), très bien (16 et plus). Les chiffres « avec votre "
                "mention ou moins » décrivent les admis des années passées, pas une chance.", "journey_bg"),
    "doublette": ("Doublette de spécialités", "Les deux enseignements de spécialité gardés en Terminale (par exemple "
                  "Mathématiques + SES). Les options comme Mathématiques expertes ne font pas partie de la doublette et "
                  "ne sont pas publiées dans les données.", "journey_stage1"),
    "serie": ("Série du bac", "Bac général, bac technologique (STMG, STI2D, ST2S…) ou bac professionnel. Les données ne "
              "distinguent pas les séries technologiques entre elles.", "serie_offer"),
    "groupe_appel": ("Groupe d'appel", "Les candidats d'une formation sont classés par groupes (par exemple « bacheliers "
                     "technologiques »). Le rang du dernier appelé est la place du dernier candidat de ce groupe qui a "
                     "reçu une proposition.", "journey_groups"),
    "secteur": ("Secteur (licences)", "Pour une licence non sélective, les candidats de l'académie de l'université sont "
                "prioritaires ; la part d'admis venant de l'académie le montre.", None),
    "boursier": ("Boursier", "Élève qui reçoit une bourse de lycée. Les formations ont un taux minimum de boursiers fixé "
                 "par le recteur.", None),
    "selective": ("Formation sélective", "Une formation qui classe et choisit ses candidats (BUT, BTS, CPGE, écoles, "
                  "certaines licences). Une licence non sélective dit « oui » tant qu'il reste des places.", None),
    "las_pass": ("PASS et LAS", "Les deux voies d'accès aux études de santé (médecine, maïeutique, odontologie, pharmacie, "
                 "kinésithérapie) : le PASS (parcours d'accès spécifique santé) ou une licence avec option accès santé (LAS).", None),
    "cohorte": ("Cohorte", "Un groupe de personnes suivies ensemble, par exemple les bacheliers inscrits en L1 en 2023. "
                "Chaque chiffre du site dit de quelle cohorte il parle.", None),
    "taux_attendu": ("Taux attendu (« simulé »)", "Le taux de réussite qu'on observerait si les inscrits d'une université "
                     "réussissaient comme la moyenne nationale des étudiants de même profil. L'écart au taux observé "
                     "s'appelle la valeur ajoutée.", "success"),
    "valeur_ajoutee": ("Valeur ajoutée", "La différence, en points, entre le taux observé et le taux attendu. Elle se lit "
                       "avec prudence et ne classe pas les universités.", "success"),
    "fiabilite": ("Fiabilité (A, B, C)", "Une note qui dit à quel point un chiffre est solide (nombre de personnes, ancienneté "
                  "de la cohorte, façon de relier les sources). Elle ne dit pas si le chiffre est bon ou mauvais pour toi.", "fiabilite"),
    "ips": ("Indice de position sociale (IPS)", "Un indice publié par le ministère de l'Éducation nationale qui résume le milieu "
            "social des élèves d'un lycée (profession des parents). Plus il est élevé, plus il est favorisé en moyenne. C'est un "
            "indicateur du lycée, pas le tien.", "lycee"),
    "va_lycee": ("Valeur ajoutée d'un lycée", "L'écart entre les résultats du lycée au bac (réussite, mentions, accès de la "
                 "seconde au bac) et ceux qu'on attendrait vu le profil de ses élèves. Un chiffre positif veut dire que le lycée "
                 "fait mieux qu'attendu.", "lycee"),
    "repere": ("Repère (fourchette)", "Pour la prochaine campagne, l'intervalle où devraient se trouver le taux d'accès et la "
               "part d'admis avec ta mention ou moins. Il est vérifié sur les années passées : on affiche combien de fois la vraie "
               "valeur est tombée dedans. Ce n'est pas une chance d'admission.", "repere"),
    "but": ("BUT (bachelor universitaire de technologie)", "Un diplôme en 3 ans préparé dans un IUT (institut universitaire de "
            "technologie), qui fait partie d'une université. Les chiffres de réussite publiés par le SIES sont donnés par "
            "université, toutes spécialités confondues.", "but"),
    "master": ("Master (M1, M2)", "Le diplôme en 2 ans après la licence (bac + 5). Les chiffres de réussite en master portent sur "
               "tous les étudiants entrés en M1 dans l'université et la discipline, d'où qu'ils viennent.", "master"),
    "paysage": ("Identifiant Paysage", "Le code officiel d'un établissement dans le référentiel du ministère. Il sert à relier "
                "une formation Parcoursup aux autres sources (réussite, insertion) sans se tromper d'université.", None),
    "zone": ("Zones (sécurité, cible, ambitieux)", "Un repère pour équilibrer ta liste, calculé à partir des admis des "
             "années passées : ce ne sont pas des probabilités d'admission.", "journey_zones"),
    "plan_b": ("Plan B", "Une formation du même programme, ailleurs, plus accessible pour ton profil d'après les admis des "
               "années passées.", "planb"),
}


def as_list() -> list[dict]:
    return [{"key": k, "terme": t, "definition": d, "methode": m}
            for k, (t, d, m) in sorted(GLOSSARY.items(), key=lambda kv: kv[1][0].lower())]
