# Prochain sprint : Robustesse 2035 des formations (PRD du 16/11/2026, partie « formations »)

Préparé le 17/11/2026, après la PR #81 (robustesse par métier, repère + 3 faits).

## Ce qui existe déjà (PR #81)

- Un score par métier pour 876 des 1 124 métiers Onisep. Il se calcule à partir de l'IA (OIT 2025 × AEI mai 2026) et de la
  demande (Cedefop 2026, Métiers 2030, BMO 2026), dans 3 scénarios, avec un indice de confiance, et les contrôles OCDE et ESCO.
- Ce que voit l'élève (choix du propriétaire, 17/11) : un repère en tête (« parmi les 20 % les plus robustes » / « dans la
  moyenne » / « parmi les 20 % les moins robustes »), puis 3 faits concrets. Le score n'apparaît que dans « Détail du calcul ».

## Mesure faite avant de coder (entrepôt du 17/11, session 2025)

Formations dont le diplôme est relié à des métiers Onisep qui ont un score :

| Filière | Formations | Reliées à des métiers notés | Métiers par formation (médiane) |
|---|---:|---:|---:|
| BTS | 5 351 | 4 743 | 5 |
| Licence | 3 052 | 2 788 | 3 |
| Autre formation | 1 815 | 0 | — |
| CPGE | 986 | 0 | — |
| BUT | 820 | 820 | 10 |
| École d'ingénieur | 585 | 0 | — |
| Licence LAS | 513 | 412 | 3 |
| IFSI | 344 | 344 | 5 |
| PASS | 287 | 0 | — |
| École de commerce | 256 | 0 | — |
| EFTS | 243 | 180 | 1 |
| **Total** | **14 252** | **9 287 (65 %)** | |

L'objectif du PRD est un score publié pour au moins 95 % des formations. Il faut donc une deuxième voie pour les CPGE, PASS,
écoles et « autres » (3 929 formations).

## PR 1 : le score par formation (P0 du PRD)

1. **Débouchés ω (somme = 1)**, une seule méthode par formation, affichée :
   - *direct* : les métiers de la fiche Onisep du diplôme (`onisep_link` → `onisep_formation_metier`). L'Onisep ne donne pas de
     poids, donc poids égaux, et c'est dit.
   - *poursuite* (licence, LAS) : les masters de la même université et de la même discipline (lien du sprint 16), pondérés par
     les admis MonMaster (des personnes), puis les métiers Onisep de chaque mention de master.
   - *famille* (CPGE, PASS, écoles d'ingénieur et de commerce, autres) : le chemin métier → formation de `parcours.py` lu à
     l'envers (règles de famille déjà écrites). Lien « moins sûr », qui compte dans la confiance.
2. **Insertion (Ins)** : InserSup (emploi stable à 18 mois, comme aujourd'hui) pour licence, BUT et master ; Inserjeunes
   pour les BTS (à 6 mois, donc pas comparable : à séparer ou à ne pas mélanger, voir question 2). Principe d'équité du PRD :
   aucune correction du public n'est publiée, donc poids réduit et limite affichée.
3. **Diversité des débouchés (Opt)** : entropie de Shannon normalisée des ω sur les grands groupes ISCO (1 chiffre). C'est une
   mesure calculée, pas une note.
4. **Score** : R(f,s) = Σ ω (0,35 IA + 0,25 Dem) + 0,20 Ins + 0,20 Opt, dans les 3 scénarios. Un terme manquant est renormalisé
   et fait baisser la couverture. Médiane affichée, avec le moins et le plus favorable (comme pour les métiers).
5. **Confiance** (PRD 6.6) : le plus faible de 4 indicateurs, à savoir fraîcheur, part des ω observée (direct > poursuite >
   famille), accord des sources, couverture. En dessous de 0,4 : « données insuffisantes ».
6. **Régime IA** des débouchés (PRD 6.5), moyenne pondérée par ω.
7. **Affichage** (règle du 17/11) : sur la fiche formation, une carte dans l'onglet « Emploi et métiers », jamais au-dessus de
   L'essentiel. On y met d'abord le repère, puis 3 faits, et le score seulement dans « Détail du calcul ». Faits proposés :
   - « Débouchés : N métiers, dont K parmi les plus robustes » ;
   - « Après ce diplôme : X sur 10 en emploi stable à 18 mois (InserSup) » ;
   - « Débouchés variés / plutôt concentrés » (diversité).
   Les 3 à 5 premiers métiers sont listés avec leur poids et leur source (F-04).
8. **Red team `redteam_robustesse_formations.py`** : ω recalculés indépendamment (sommes à 1, une méthode par formation),
   entropie, insertion, formule et scénarios, confiance, repère ; pas de lien sans source ; page échappée et sans mot
   anxiogène ; mode `--real` qui imprime la couverture (cible ≥ 95 % publiées, ≥ 60 % en confiance moyenne ou haute) et la
   stabilité de Spearman à ±10 points ; test de mutation.
9. **Stockage** : un JSON compact par formation dans `rapport_textes.duckdb`, jamais dans l'entrepôt (budget de 95 Mo).
   Les détails métiers déjà calculés sont réutilisés, sans relire `metiers.detail`, pour le temps de CI.

## PR 1 bis : l'usage observé de l'IA comme contrôle des métiers (accord du propriétaire, 17/11)

- **Donnée** : l'Anthropic Economic Index publie, pour 740 métiers O*NET (mai 2026, monde), la part de l'usage de Claude qui
  porte sur les tâches de chaque métier (indicateur `pct`). C'est une exposition « observée » : ce que les gens font vraiment
  avec l'IA. L'OIT, elle, mesure ce que l'IA pourrait faire.
- **Règle** (la même que pour l'OCDE) : c'est un contrôle, jamais dans l'exposition ni dans le score. On compare le rang du
  métier selon l'OIT et selon l'usage observé ; un écart de plus de 15 points fait baisser l'accord des sources, avec le même
  plancher à 0,5. Les deux places sont affichées côte à côte dans « Détail du calcul ».
- **À vérifier d'abord sur les données** : la part d'usage dépend du nombre de personnes qui exercent le métier et des
  utilisateurs de Claude. Il faut donc trouver une normalisation défendable, par exemple la part d'usage rapportée à
  l'emploi du métier (BLS) ou le seul rang. Si aucune n'est défendable, on ne l'affiche pas et on le dit au propriétaire.
- Lien : le même que pour l'augmentation (O*NET → SOC → ISCO, tables officielles ; grand groupe signalé à défaut).
- Red team : RB12 (lecture indépendante, rangs, aucun effet sur le score, page), mutants.

## PR 2 : comparer ses vœux (P0 C-01, C-02 ; P1)

- Dans Mes vœux, jusqu'à 10 formations sur un graphique robustesse × atteignabilité (atteignabilité = la zone déjà calculée,
  jamais mélangée au score), avec la taille du point selon la confiance. Tableau triable, export CSV.
- Page méthode publique et journal des versions du modèle (R-03) : chaque changement de score est noté (avant, après, cause).
- Badge de sensibilité aux pondérations (R-02) : « classement stable » ou « sensible ».

## Décisions à prendre par le propriétaire avant de coder

1. **Repère des formations** : comparer chaque formation à toutes les formations, ou seulement à celles de sa filière (un BTS
   avec les BTS) ? Recommandation : la filière, car une licence et un BTS n'ont pas les mêmes débouchés ni la même insertion.
2. **Insertion des BTS** : Inserjeunes mesure l'emploi à 6 mois et InserSup à 18 mois. Recommandation : ne pas les mettre sur
   la même échelle. Pour les BTS, l'insertion reste affichée à part et son poids passe sur IA et demande, avec une limite dite.
3. **Poids de l'insertion** : garder 0,20 comme dans le PRD, ou le réduire à 0,10 tant qu'aucune correction du public
   n'existe (principe d'équité n° 7) ? Recommandation : 0,10, avec la limite affichée.
4. **Licence** : prendre les débouchés seulement par la poursuite en master (PRD), ou faire la moitié poursuite et la moitié
   métiers de la licence elle-même ? Recommandation : la poursuite seule, comme le PRD, avec les métiers de la licence montrés
   à part.

## Fait : la PR #81 a été fusionnée le 17/11

- CI verte (le lot 2 avait dépassé 45 minutes ; la construction relit maintenant une seule fois les fiches métiers, environ
  75 s de gagnées par entrepôt de test), puis passer la PR en « prête » pour lancer la relecture Codex et en traiter les
  retours.
- Si le lot 2 reste proche de 45 minutes, ajouter un quatrième lot de tests (fichier `.github/workflows/suptracker.yml`).
