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
4. **Score** (recommandé, décisions 3 et 5) : R(f,s) = Σ ω (0,35 IA + 0,25 Dem) + 0,10 Ins + 0,15 Div + 0,15 Comp, dans les
   3 scénarios (Div = diversité des débouchés, Comp = transférabilité des compétences ; PRD : 0,20 Ins + 0,20 Opt). Un terme manquant est renormalisé
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

## PR 1 ter : les compétences que la formation développe (demande du propriétaire, 17/11)

Les débouchés disent « vers quels métiers on va ». Les compétences disent « avec quoi on repart », ce qui reste utile si le
métier visé change. On l'ajoute pour mieux juger la formation.

- **Source officielle** : la fiche RNCP de chaque diplôme national (France Compétences, open data sur data.gouv.fr, licence
  ouverte, export quotidien). Elle donne les **blocs de compétences** (texte), les codes ROME et le code NSF. Les BTS, BUT,
  licences, DE infirmier et DE du travail social en ont une. Les CPGE, PASS et LAS n'en ont pas : pas de carte compétences
  pour elles, et c'est dit.
- **Lecture des compétences** : on rattache chaque compétence du bloc aux compétences ESCO (13 960 compétences, v1.2.1 déjà
  déposée). ESCO classe chacune par portée (`reuseLevel` : transversale 453, intersectorielle 3 788, propre à un secteur 6 667,
  propre à un métier 3 047) et la marque numérique ou verte. Le lien texte → ESCO n'est pas officiel : il est fait par règles
  fixes sur les mots, marqué « apparié », relu à la main sur un échantillon de 200 liens, et il compte dans la confiance.
  Aucune IA ne fournit un chiffre.
- **Trois indicateurs simples** (faits, pas de note) :
  1. *Compétences utiles ailleurs* : part des compétences transversales ou intersectorielles (« 6 compétences sur 10 servent
     dans de nombreux métiers »).
  2. *Métiers voisins* : nombre de métiers ESCO qui mobilisent au moins la moitié de ces compétences (« 35 métiers utilisent
     au moins la moitié de ce que vous apprendrez »). C'est la mesure de la reconversion possible.
  3. *Numérique et transition écologique* : part des compétences des collections ESCO numérique et verte.
- **Dans le score** : la transférabilité (indicateur 1, et 2 ramené sur 100 avec des bornes fixes) entre dans le terme
  « options », à côté de la diversité des débouchés (voir la décision n° 5).
- **Limite à dire** : les compétences viennent du référentiel NATIONAL du diplôme. Deux BTS de même nom ont les mêmes
  compétences. Ce qui distingue deux établissements reste l'insertion, les options et les chiffres d'admission. C'est une
  mesure du diplôme, pas de la qualité de l'enseignement.
- **Vérifier d'abord** (avant de coder) : la part des formations Parcoursup reliées à une fiche RNCP active, et la qualité du
  rattachement texte → ESCO sur 200 compétences. Si le rattachement n'est pas fiable, la carte montre les blocs RNCP tels
  qu'ils sont publiés, sans indicateur ni score.

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

## Vérifications faites le 17/11 (données réelles, session 2025)

**1. Lien formation → fiche RNCP (officiel).** La fiche Onisep de chaque licence, DE infirmier et DE du travail social donne
l'adresse de sa fiche RNCP. Pour les BTS et les BUT, l'intitulé national du diplôme retrouve la fiche RNCP (règle fixe sur le
titre, la fiche active d'abord). Résultat : **8 976 formations sur 14 252 (63 %)**, dont 4 432 BTS sur 5 351, 2 788 licences sur
3 052, 757 BUT sur 820, 412 LAS sur 513, 344 IFSI sur 344 et 243 EFTS sur 243. Il manque les BTSA (agricoles), le BTS ESF et quelques
parcours de BUT (à rattraper). Les CPGE, PASS et écoles n'ont pas de fiche RNCP pour l'entrée en première année : pas de carte
compétences, dit sur la page.

**2. Lien blocs RNCP → ESCO par les mots : NON fiable.** Sur 25 blocs tirés au hasard, 5 à 7 seulement tombent juste (« Gérer
l'engraissement des escargots » → « élever des escargots », mais « Communiquer dans des situations variées » → « services de
communication radio »). Cette voie est abandonnée, comme prévu.

**3. Voie officielle retenue : RNCP → codes ROME → compétences ROME 4.0 (France Travail, open data).** La fiche RNCP cite les
codes ROME des métiers visés. Le ROME 4.0 donne, pour chacun des 1 923 métiers, ses compétences (20 088 au total), chacune classée
par France Travail en **technique**, **technique expert** ou **transverse**, avec un repère « transition écologique » et
« transition numérique », et les **mobilités professionnelles** officielles vers d'autres métiers. Aucun appariement de textes.
Médianes par formation :

| Filière | Formations | Métiers ROME | Compétences | Transverses | Partagées par ≥ 20 métiers | Numérique | Écologique | Métiers proches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTS | 4 432 | 3 | 87 | 21 % | 33 % | 7 % | 2 % | 25 |
| Licence | 2 788 | 5 | 179 | 27 % | 27 % | 7 % | 2 % | 41 |
| BUT | 757 | 11 | 288 | 20 % | 29 % | 9 % | 4 % | 62 |
| LAS | 412 | 5 | 171 | 26 % | 31 % | 9 % | 2 % | 40 |
| IFSI | 344 | 1 | 28 | 29 % | 36 % | 0 % | 7 % | 10 |
| EFTS | 243 | 1 | 44 | 33 % | 28 % | 2 % | 0 % | 10 |

Limite à dire : ce sont les compétences des **métiers que le diplôme vise** selon sa fiche RNCP. Les blocs de compétences du
diplôme lui-même sont affichés tels que publiés (médiane : 5 blocs), sans calcul dessus.

**4. Pratique et entreprise.** L'apprentissage est possible pour tous les BTS et BUT (voies d'accès RNCP). La durée des stages
n'est imprimée que sur 119 textes de fiches Parcoursup : on l'affiche quand elle est écrite, et sinon la règle nationale du type
de diplôme avec sa source (par exemple 22 à 26 semaines de stage en BUT, arrêté du 6 décembre 2019), jamais une durée inventée.

**5. Métiers accessibles avec le seul diplôme.** Les métiers de la fiche Onisep d'un diplôme sont tous à son niveau ou en dessous
(0 métier au-dessus du niveau du diplôme sur 74 000 liens). Ils forment la liste « avec ce diplôme seul », avec leur repère de
robustesse. 5 182 BTS sur 5 502 et 3 254 BUT sur 3 268 ont au moins un métier noté.

**6. Gain par un master (licences).** 2 785 licences ont à la fois des métiers « licence seule » et des masters reliés (même
université, même discipline). La robustesse médiane des métiers après le master dépasse celle de la licence seule pour 2 505
d'entre elles (90 %). Le gain médian est de **+4,2 points** (de 0 à +9,8 points pour 80 % des licences). Il sera affiché comme
un changement de repère et de faits, par exemple « après un master, 5 % des métiers visés sont parmi les plus robustes, contre
aucun avec la licence seule », jamais comme une promesse.

## Validé par le propriétaire (17/11) et précisions

Les 5 recommandations sont validées. Le propriétaire ajoute :
- **Une formation = la somme des compétences qu'elle développe**, par la théorie, la pratique et l'expérience en entreprise
  (stages, alternance). On lit donc, pour chaque diplôme, ses blocs de compétences et, quand la source le dit, la part de
  pratique et de stage (durée des stages, alternance possible : fiche RNCP, fiche Onisep, fiche Parcoursup). Chaque compétence
  reçoit sa robustesse (portée ESCO, numérique, verte, et l'exposition à l'IA des métiers qui l'utilisent).
- **Le gain de robustesse par un master** : pour une licence (et un BUT ou un BTS quand une poursuite existe), on compare la
  robustesse avec le diplôme seul et après les masters accessibles (même université, même discipline, admis MonMaster). Le
  gain est affiché comme un écart de repère et de faits, jamais comme une promesse.
- **Les métiers accessibles avec le seul diplôme post-bac** sont traités à part : ceux dont le niveau minimum Onisep est atteint
  par le diplôme (bac+2 pour un BTS, bac+3 pour BUT et licence). Ils ont leur propre repère, séparé de celui des métiers après
  un master.

## Décisions (validées le 17/11)

1. **Repère des formations** : comparer chaque formation à toutes les formations, ou seulement à celles de sa filière (un BTS
   avec les BTS) ? Recommandation : la filière, car une licence et un BTS n'ont pas les mêmes débouchés ni la même insertion.
2. **Insertion des BTS** : Inserjeunes mesure l'emploi à 6 mois et InserSup à 18 mois. Recommandation : ne pas les mettre sur
   la même échelle. Pour les BTS, l'insertion reste affichée à part et son poids passe sur IA et demande, avec une limite dite.
3. **Poids de l'insertion** : garder 0,20 comme dans le PRD, ou le réduire à 0,10 tant qu'aucune correction du public
   n'existe (principe d'équité n° 7) ? Recommandation : 0,10, avec la limite affichée.
4. **Licence** : prendre les débouchés seulement par la poursuite en master (PRD), ou faire la moitié poursuite et la moitié
   métiers de la licence elle-même ? Recommandation : la poursuite seule, comme le PRD, avec les métiers de la licence montrés
   à part.

5. **Compétences** : les faire entrer dans le score ? Recommandation : oui, à 0,15, en partageant avec la diversité des
   débouchés le poids « options » du PRD (0,15 + 0,15 au lieu de 0,20), plus les 0,10 libérés par l'insertion. Les deux
   répondent à la même question : « si le métier visé ne tient pas, peut-on rebondir ? ». Seulement si la vérification du
   rattachement ESCO est bonne ; sinon, les compétences sont affichées sans entrer dans le score.

## Fait : la PR #81 a été fusionnée le 17/11

- CI verte (le lot 2 avait dépassé 45 minutes ; la construction relit maintenant une seule fois les fiches métiers, environ
  75 s de gagnées par entrepôt de test), puis passer la PR en « prête » pour lancer la relecture Codex et en traiter les
  retours.
- Si le lot 2 reste proche de 45 minutes, ajouter un quatrième lot de tests (fichier `.github/workflows/suptracker.yml`).
