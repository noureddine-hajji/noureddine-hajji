---
title: "Reconstruction de la complémentarité humaine (θ) et du C-AIOE — FMI × O*NET"
lang: fr
version: "1.0"
updated: "2026-11-05"
status: "Guide méthodologique sourcé ; aucun score métier observé n'est prétendu calculé"
---

# Reconstruire la complémentarité humaine (θ) et le C-AIOE à partir d'O*NET

**Référence principale :** Pizzinelli, C., Panton, A., Tavares, M. M., Cazzaniga, M., & Li, L. (2023), *Labor Market Exposure to AI: Cross-country Differences and Distributional Implications*, IMF Working Paper WP/23/216, sections 2.2 à 2.4, annexe A.  
**Données descriptives :** O*NET 31.0 (août 2026), fichiers `work_context.csv` et `job_zones.csv`.  
**Date de vérification des documentations :** 5 novembre 2026.

> **Portée réelle :** ce document décrit précisément le contenu des deux fichiers, les variables à sélectionner, leur sens, leurs transformations, la formule des scores, une méthode de reconstruction et les pièges de comparabilité. Il ne prétend **pas** contenir des scores calculés pour les métiers : les CSV complets et le fichier AIOE n'ont pas été fournis ici. **Les deux fichiers O*NET suffisent à calculer θ, mais pas à calculer C-AIOE : ce dernier exige aussi un indice AIOE externe**.

## 1. Vue d'ensemble : trois objets distincts

| Indice | Définition | Source nécessaire | Lecture correcte |
|---|---|---|---|
| **AIOE** (*AI Occupational Exposure*) | Degré d'exposition théorique d'un métier aux capacités de l'IA | Felten, Raj & Seamans (2021), ou reconstruction séparée à partir des capacités O*NET et de la matrice applications IA–capacités | Plus haut = plus de tâches/capacités liées à l'IA, **sans préjuger de la substitution** |
| **θ** (*potential complementarity*, ou complémentarité humaine potentielle) | Potentiel d'utilisation de l'IA **en complément** du travail humain, d'après six caractéristiques du métier | `work_context.csv` (**11 variables**) + `job_zones.csv` (**1 variable**) | Plus haut = complémentarité potentielle plus forte dans le cadre conceptuel du FMI ; échelle 0–1 |
| **C-AIOE** (*Complementarity-Adjusted AI Occupational Exposure*) | Indice d'exposition à l'IA **corrigé par θ** | **AIOE + θ** et minimum θ de référence | Plus haut = exposition relative *moins amortie* par la complémentarité, proxy de pression de substitution, **pas probabilité de perte d'emploi** |

### Données manquantes : ce qu'il est interdit d'inventer

1. Si AIOE n'est pas fourni ou reconstruit, produire `theta` et laisser `c_aioe` à `NA`.
2. Si une des 11 variables Work Context ou la Job Zone manque, marquer le score `theta` comme **incomplet**, sans remplacement silencieux par zéro ou moyenne du groupe.
3. Ne pas fusionner naïvement des valeurs issues de nomenclatures métiers différentes (O*NET-SOC vs SOC 2010).
4. Ne pas présenter un score calculé à partir de l'O*NET 31.0 comme une reproduction exacte des résultats du FMI 2023.

## 2. Fichier `work_context.csv` — définition, structure, usage

### 2.1. Définition

**Work Context** décrit les **conditions sociales, physiques et organisationnelles** dans lesquelles s'exerce un emploi : interactions avec d'autres personnes, responsabilité, conditions environnementales, contraintes et dangers physiques, liberté de décision, degré d'automatisation, etc. Il s'agit de **caractéristiques du poste de travail**, et non de compétences personnelles ni d'un score IA.

Dans O*NET 31.0, le fichier comprend **305 389 lignes, 16 colonnes, 57 éléments Work Context évalués, et des notations pour 911 métiers**. La granularité n'est **pas** « une ligne = un métier » : plusieurs lignes correspondent à un couple *métier × indicateur × échelle*, avec parfois des catégories de réponses distinctes. Une simple moyenne de toutes les lignes de `Data Value` serait erronée.

**Fichier :** [Télécharger `work_context.csv` (O*NET 31.0)](https://www.onetcenter.org/dl_files/database/db_31_0_csv/work_context.csv)  
**Dictionnaire officiel :** https://www.onetcenter.org/dictionary/31.0/csv/work_context.html

### 2.2. Les 16 colonnes expliquées

| Colonne (nom exact CSV) | Définition | Utilisation pour θ |
|---|---|---|
| `O*NET-SOC Code` | Identifiant O*NET-SOC du métier, ex. `29-1141.00` | **Clé de jointure** avec Job Zones et les correspondances SOC |
| `Title` | Intitulé du métier en anglais | Lisibilité et vérification de jointure ; pas une clé fiable |
| `Element ID` | Identifiant stable de la variable, ex. `4.C.3.b.2` | **Filtre principal** : conserver les 11 identifiants sélectionnés |
| `Element Name` | Libellé de l'indicateur | Documentation ; peut être renommé selon la version |
| `Scale ID` | Code de l'échelle de notation (`CX`, `CXP`, `CT`, `CTP`) | **Crucial** pour ne pas confondre une moyenne avec un pourcentage de réponses |
| `Scale Name` | Nom descriptif de l'échelle | Vérifier le type de donnée |
| `Category` | Modalité d'une question catégorielle, si présente | Ne pas agréger indistinctement les catégories |
| `Data Value` | Valeur observée/calculée pour le métier, l'élément et l'échelle | **Note brute** à traiter en fonction de `Scale ID` |
| `N` | Taille de l'échantillon | Contrôle de fiabilité |
| `Standard Error` | Erreur standard de la note | Incertitude statistique |
| `Lower CI Bound` | Borne basse de l'IC à 95 % | Contrôle de robustesse |
| `Upper CI Bound` | Borne haute de l'IC à 95 % | Contrôle de robustesse |
| `Recommend Suppress` | `Y` lorsque la précision est insuffisante selon O*NET | Marquer ou écarter suivant la politique qualité |
| `Not Relevant` | `Y` lorsque le contexte ne s'applique pas à ce métier | Marquer comme non pertinent ; **pas égal à zéro** |
| `Date` | Mois/année de mise à jour de la note | Traçabilité temporelle |
| `Domain Source` | Origine du renseignement (enquête, analystes, etc.) | Traçabilité et analyse de couverture |

### 2.3. Échelles et normalisation : attention aux pièges

- `CX` : note synthétique *Context*, généralement sur **1–5** pour les éléments visés. Pour une note brute `x` allant de 1 à 5 : **`score_100 = 100 × (x−1)/(5−1) = 25 × (x−1)`**. Ainsi 1→0 ; 3→50 ; 5→100.
- `CXP` : pourcentage des répondants associé à **une modalité**, codée par `Category`. C'est une distribution, **pas** la note synthétique à injecter directement dans θ. Une valeur de 60 dans `CXP` signifie typiquement « 60 % des réponses dans cette modalité », et non « score de contexte de 60 ».
- `CT` / `CTP` : échelles ou pourcentages liés à des questions catégorielles spécifiques ; vérifier leur sens dans `Scales Reference` et `Work Context Categories` ; **ne pas les assimiler à `CX`**.
- Pour reconstruire l'approche O*NET standard du FMI, privilégier **la note `CX` normalisée 0–100 de chaque indicateur**, si elle est effectivement présente et valide. La fonction générale est `100 × (x − Minimum)/(Maximum − Minimum)` avec les bornes de la **bonne échelle**, disponibles dans `Scales Reference`.
- En cas d'absence de `CX`, **ne pas substituer automatiquement `CXP`**. L'utilisation d'une distribution de réponses pour reconstituer un score moyen exige un traitement séparé, documenté et validé contre O*NET OnLine.

Sources : [O*NET Scales Reference](https://www.onetcenter.org/dictionary/31.0/csv/scales_reference.html), [O*NET OnLine — Scales, Ratings and Standardized Scores](https://www.onetonline.org/help/online/scales), [Work Context Categories](https://www.onetcenter.org/dictionary/31.0/csv/work_context_categories.html).

## 3. Fichier `job_zones.csv` — définition, structure, usage

### 3.1. Définition

Les **Job Zones** classent les métiers d'après le **niveau de préparation professionnelle nécessaire** : combinaison de formation académique, expérience professionnelle, entraînement et apprentissage sur le poste. Elles mesurent une **exigence du métier**, pas la qualification effective d'un individu. Le FMI utilise cette variable comme proxy du potentiel d'appropriation d'outils IA et de compétences complémentaires.

O*NET 31.0 contient **923 métiers et 5 colonnes** :

| Colonne | Définition | Rôle |
|---|---|---|
| `O*NET-SOC Code` | Identifiant du métier | **Jointure exacte** avec `work_context.csv` |
| `Title` | Intitulé du métier | Contrôle |
| `Job Zone` | Niveau de préparation requis | **Sixième dimension de θ** |
| `Date` | Date de mise à jour | Traçabilité |
| `Domain Source` | Origine de l'attribution | Traçabilité |

**Fichier :** [Télécharger `job_zones.csv` (O*NET 31.0)](https://www.onetcenter.org/dl_files/database/db_31_0_csv/job_zones.csv)  
**Dictionnaire officiel :** https://www.onetcenter.org/dictionary/31.0/csv/job_zones.html

### 3.2. Attention : changement majeur entre le FMI 2023 et O*NET 2026

| Job Zone historique (O*NET utilisé dans l'esprit du FMI 2023) | Signification | Transformation FMI en points |
|---|---|---:|
| **1** | Très faible ou aucune préparation | **20** |
| **2** | Une certaine préparation | **40** |
| **3** | Préparation moyenne | **60** |
| **4** | Préparation considérable | **80** |
| **5** | Préparation extensive | **100** |

**Depuis la transition O*NET vers quatre groupes**, les anciennes zones 1 et 2 ont été rassemblées dans **« Job Zone 1–2 »**. Dans les fichiers 31.0, cette catégorie utilise **le code numérique 2** ; les autres codes sont 3, 4, 5. Les quatre catégories sont donc : `2 (1–2)`, `3`, `4`, `5`.

**Conséquences :**

- *Reconstruction historique* : utiliser une version antérieure d'O*NET avec les **cinq zones distinctes**, puis appliquer `JZ_100 = 20 × JobZone`. Il faut encore harmoniser les métiers en **SOC 2010** pour rapprocher Felten/FMI.
- *Adaptation O*NET 31.0* : appliquer provisoirement `JZ_100 = 20 × JobZone` aux codes `2/3/4/5`, **mais** identifier cette variante comme **`theta_onet31_adapte`**, non équivalente au score 2023. Les métiers autrefois en zone 1 perdent l'information nécessaire pour retrouver leur niveau 20. Même si on connaissait le niveau historique, des reclassements supplémentaires peuvent intervenir.
- Ne pas reconstituer l'ancienne Job Zone 1 à partir de la seule catégorie fusionnée `1–2` : **impossible sans données historiques**.

Sources : [O*NET — Transition des Job Zones (octobre 2025)](https://www.onetcenter.org/reports/Job_Zone_Transition.html), [O*NET — Job Zone Reference 31.0](https://www.onetcenter.org/dictionary/31.0/csv/job_zone_reference.html), [O*NET — Archives](https://www.onetcenter.org/db_releases.html).

## 4. Les 11 variables `Work Context` retenues par le FMI — dictionnaire opérationnel

Le FMI en sélectionne **11 sur 57**, réparties en **cinq composantes Work Context**, plus la composante **Skills = Job Zone**. La sélection ne doit pas être confondue avec l'ensemble des 57 éléments disponibles.

Le tableau ci-dessous associe les concepts du papier de 2023 aux libellés courants consultables dans O*NET 31.0. Les **identifiants `Element ID`** sont préférables aux libellés, qui peuvent évoluer.

| Groupe FMI | `Element ID` | Variable O*NET (nom courant / historique) | Ce que le score 0–100 mesure ; direction attendue pour θ | Transformation |
|---|---|---|---|---|
| **1. Communication** | `4.C.1.a.2.l` | **Face-to-Face Discussions with Individuals and Within Teams** / *Face-to-Face Discussions* | Fréquence des discussions en présence avec personnes/équipes ; score élevé = interaction humaine soutenue | `x` |
| Communication | `4.C.1.a.2.c` | **Public Speaking** | Fréquence de la prise de parole devant un public ; élevé = plus d'exigence d'interaction/oratoire | `x` |
| **2. Responsabilité** | `4.C.1.c.2` | **Work Outcomes and Results of Other Workers** / *Responsibility for Outcomes and Results* | Responsabilité vis-à-vis des résultats du travail d'autrui ; élevé = supervision, responsabilité et contrôle humain | `x` |
| Responsabilité | `4.C.1.c.1` | **Health and Safety of Other Workers** / *Responsible for Others' Health and Safety* | Responsabilité pour la santé/sécurité d'autres personnes ; élevé = enjeu fort de supervision et d'imputabilité | `x` |
| **3. Conditions physiques** | `4.C.2.a.1.c` **(proxy à valider)** | **Outdoors, Exposed to All Weather Conditions** / FMI : *Exposure to Outdoors Environments* | Fréquence du travail dehors en conditions météorologiques variées ; élevé = environnement physique difficile à automatiser sans robotique | `x` |
| Conditions physiques | `4.C.2.a.3` | **Physical Proximity** | Nécessité de travailler physiquement à proximité d'autres personnes ; élevé = contexte de coprésence | `x` |
| **4. Criticité** | `4.C.3.a.1` | **Consequence of Error** | Gravité des conséquences d'une erreur non facilement rattrapable ; élevé = coûts de l'erreur importants | `x` |
| Criticité | `4.C.3.a.4` | **Freedom to Make Decisions** | Liberté de décision sans supervision ; élevé = autonomie et jugement professionnel | `x` |
| Criticité | `4.C.3.a.2.b` | **Frequency of Decision Making** | Fréquence des décisions touchant les personnes, finances ou réputation ; élevé = décisions fréquentes | `x` |
| **5. Non-routine** | `4.C.3.b.2` | **Degree of Automation** | Degré **actuel** d'automatisation du travail ; élevé = automatisation déjà forte | **`100 − x`** |
| Non-routine | `4.C.3.b.8` | **Determine Tasks, Priorities and Goals** / *Structured Versus Unstructured Work* | Liberté de définir tâches, priorités et objectifs ; élevé = travail **moins structuré** | `x` |
| **6. Compétences / formation** | — | **Job Zone** (`job_zones.csv`) | Préparation nécessaire au métier ; élevé = formation/expérience longue | **`20 × JZ`** (historique 1–5) |

**Précision capitale sur « extérieur » :** le papier du FMI emploie l'expression générique *Exposure to Outdoors Environments*, qui n'est pas le libellé exact d'une unique variable O*NET. L'indicateur `4.C.2.a.1.c` (**Outdoors, Exposed to All Weather Conditions**) est une correspondance opérationnelle plausible ; `4.C.2.a.1.d` (**Outdoors, Under Cover**) est un autre élément distinct. **Sans le script ou la table d'éléments des auteurs, l'identité exacte de leur variable extérieure ne peut pas être garantie.** Avant d'annoncer une reproduction exacte, valider ce choix contre leurs données ou résultats de référence. Ne pas additionner les deux variables sans justification.

**Précision sur le nom de la « routine » :** pour `4.C.3.b.8`, la note O*NET élevée correspond à **plus de liberté** (travail moins structuré), ce qui explique le sens positif ; le FMI inverse **uniquement `Degree of Automation`**, pas ce deuxième indicateur.

**Raisonnement économique sous-jacent (FMI) :** présence/interactions, responsabilité juridique et humaine, contexte physique, conséquences des erreurs, autonomie/non-routine et préparation professionnelle sont considérés comme des frictions à une substitution intégrale de l'humain. Ces choix sont **hypothèses de mesure**, et non vérifications empiriques qu'une profession serait « irremplaçable ».

Sources : [IMF WP/23/216, §2.3 et §2.4](https://www.imf.org/-/media/files/publications/wp/2023/english/wpiea2023216-print-pdf.pdf), [O*NET — les 57 descripteurs courants](https://www.onetonline.org/find/descriptor/browse/4.C/).

## 5. Formules exactes à reconstruire

### 5.1. Score normalisé d'un contexte de travail

Pour le métier `i` et l'élément `e`, si l'observation utile est une note `CX` de 1 à 5 :

\[
X_{i,e}=100\frac{\mathrm{DataValue}_{i,e}-1}{5-1}
=25(\mathrm{DataValue}_{i,e}-1).
\]

Pour *Degree of Automation* uniquement :

\[
X^{*}_{i,\mathrm{automation}}=100-X_{i,\mathrm{automation}}.
\]

Tous les autres `X*` valent `X`. Cette notation suppose des entrées comparables **en 0–100** ; une note brute de 1–5 ne peut pas être directement moyennée avec une Job Zone de 20–100.

### 5.2. Six scores de dimensions (0–100)

Pour un métier `i`, en notant `FF`, `PS`, `OR`, `HS`, `OD`, `PP`, `CE`, `FD`, `DM`, `AU` et `US` les onze notes normalisées (l'automatisation brute étant `AU`) :

\[
\begin{aligned}
D_{1,i}^{communication} &= (FF_i+PS_i)/2,\\
D_{2,i}^{responsabilite} &= (OR_i+HS_i)/2,\\
D_{3,i}^{physique} &= (OD_i+PP_i)/2,\\
D_{4,i}^{criticite} &= (CE_i+FD_i+DM_i)/3,\\
D_{5,i}^{non\_routine} &= ((100-AU_i)+US_i)/2,\\
D_{6,i}^{skills} &= 20\,JZ_i \quad\text{(référence historique, JZ=1…5)}.
\end{aligned}
\]

### 5.3. Score de complémentarité humaine potentielle θ (0–1)

\[
\boxed{\displaystyle \theta_i=\frac{1}{6}\sum_{g=1}^{6}\frac{D_{g,i}}{100}
=\frac{D_{1,i}+D_{2,i}+D_{3,i}+D_{4,i}+D_{5,i}+D_{6,i}}{600}}
\]

**Pondération :** 1/6 pour **chaque dimension** et non 1/12 pour chaque variable élémentaire ; par exemple une variable de criticité pèse `1/(6×3)=1/18`, une variable de communication `1/(6×2)=1/12` et la Job Zone `1/6`.

**Ancrages historiques rapportés par le FMI (échantillon et nomenclature de l'article, pas seuils universels) :** `θ_min = 0,31` (*Hand Cutters and Trimmers*, SOC 2010 `51-9031`) ; `θ_max = 0,78` (*Oral and Maxillofacial Surgeons*, `29-1022`) ; médiane `0,58`. Ils servent au **contrôle de vraisemblance** d'une reconstruction historique, et **ne doivent pas être imposés** à des données mises à jour en 2026.

### 5.4. Score d'exposition corrigé C-AIOE

**Spécification de référence du FMI :**

\[
\boxed{\displaystyle C\text{-}AIOE_i=AIOE_i\,\left[1-(\theta_i-\theta_{\min})\right]}
\]

**Variante de sensibilité** (également discutée par les auteurs) :

\[
C\text{-}AIOE_i(w)=AIOE_i\,\left[1-w(\theta_i-\theta_{\min})\right],\quad 0\le w\le1.
\]

- `w = 1` : **C-AIOE FMI de référence**.
- `w = 0,5` : ajustement moitié moins prononcé (analyse de sensibilité, **non** score de référence).
- `w = 0` : score **AIOE non corrigé**.
- `θ_min` : minimum observé dans la **population de référence du calcul**. Pour la réplication de l'article utiliser l'**univers et la référence de l'article** (`0,31`) si la méthode est correctement alignée ; pour une **nouvelle adaptation**, recalculer `min(θ_i)` sur l'univers couvert et archiver cet univers.

**L'échelle du C-AIOE est celle de l'AIOE utilisé.** Il ne s'agit pas par défaut d'un pourcentage. N'appliquez pas cette multiplication à une version AIOE *centrée-réduite* pouvant prendre des valeurs négatives sans vérifier sa compatibilité avec l'échelle positive de référence du FMI. En particulier, un changement d'origine ou de normalisation *avant* l'ajustement change le résultat et peut inverser certaines interprétations. Si l'on souhaite représenter les scores sur 0–100 pour un graphique, normaliser les **indices finaux** en documentant la méthode et l'univers, sans les confondre avec les valeurs brutes du papier.

### 5.5. Exemple numérique (entièrement fictif)

| Dimension | Entrées 0–100 | Calcul | Score |
|---|---|---|---:|
| Communication | Face-à-face 80 ; oral public 60 | `(80+60)/2` | 70 |
| Responsabilité | Résultats d'autrui 70 ; sécurité 90 | `(70+90)/2` | 80 |
| Conditions physiques | Extérieur 40 ; proximité 60 | `(40+60)/2` | 50 |
| Criticité | Erreurs 80 ; autonomie 60 ; décisions 70 | `(80+60+70)/3` | 70 |
| Non-routine | Automatisation **brute 60** ; tâches non structurées 90 | `((100−60)+90)/2` | 65 |
| Skills | Job Zone historique = **4** | `20×4` | 80 |

**θ = (70+80+50+70+65+80)/600 = 0,6917.**  
En prenant **pour l'exemple seulement** `θ_min=0,31` et `AIOE=6,00` sur une échelle positive compatible :  
**`C-AIOE (w=1) = 6 × [1−(0,6917−0,31)] ≈ 3,71`.**  
**`C-AIOE (w=0,5) ≈ 4,86`.**

> Ces nombres sont illustratifs ; ils ne correspondent à **aucun métier évalué**. Ils servent uniquement à valider l'arithmétique.

## 6. Sources externes indispensables pour un C-AIOE complet

### AIOE : Felten, Raj & Seamans (2021)

L'AIOE est obtenu en reliant **10 applications de l'IA** aux **52 capacités professionnelles O*NET** à l'aide d'une matrice de proximité, puis en pondérant l'exposition des capacités par leur présence et importance dans chaque métier. Formellement :

\[
AIOE_i=\frac{\sum_{j=1}^{52} A_j\,L_{ji}\,I_{ji}}{\sum_{j=1}^{52}L_{ji}\,I_{ji}},
\qquad A_j=\sum_{k=1}^{10} \mathrm{relatedness}_{jk}.
\]

Les fichiers **Work Context** et **Job Zones** ne contiennent ni ces notes AIOE, ni la matrice IA–capacités. Il faut donc :

1. **Idéal pour une réplication :** récupérer les scores AIOE de la version utilisée par les auteurs ou le matériel de réplication de l'étude FMI, puis harmoniser la nomenclature **SOC 2010**.
2. **Alternative indépendante :** consulter le [dépôt public de Felten et al. — AIOE-Data/AIOE](https://github.com/AIOE-Data/AIOE) et sa documentation, identifier la **colonne exacte** (score brut vs score standardisé), sa version et sa nomenclature.
3. **À défaut :** reconstruire AIOE séparément à partir des capacités et de la matrice d'applications IA, puis justifier que l'échelle retenue permet le même ajustement que dans l'article.

Le jeu de données spécifique de la reproduction FMI identifié comme `AIOE_CAIOE_theta_for_sharing.xlsx` a fait l'objet de restrictions de redistribution dans les informations de reproductibilité publiques ; **sa présence dans un référentiel ne vaut pas autorisation de le repartager**. [Catalogue de reproductibilité de la Banque mondiale](https://reproducibility.worldbank.org/catalog/403).

## 7. Protocole recommandé : reconstruction historique vs adaptation actuelle

| Étape | **Réplication historique (prioritaire pour comparer au FMI)** | **Indice actualisé O*NET 31.0 (exploratoire)** |
|---|---|---|
| Données Work Context | Version historique à préciser (par ex. archive O*NET 28.0, août 2023, **sans garantie qu'il s'agisse de la version des auteurs**) | O*NET 31.0 |
| Job Zones | **Cinq zones 1–5** | **Quatre groupes**, codes 2/3/4/5 |
| Descripteurs | 11 variables ci-dessus, vérifier l'ambiguïté de l'extérieur | 11 variables, valider l'équivalence sémantique des renommages |
| Échelle | Variables 0–100 ; automatisation inversée | Identique, après validation des échelles |
| Rattachement métiers | Conversion **O*NET-SOC → SOC 2010**, puis joindre AIOE de même nomenclature | O*NET-SOC 31.0 ; si AIOE en SOC 2010, **crosswalk explicite** obligatoire |
| `θ_min` | Référence FMI historique 0,31 après validation complète | Minimum recalculé dans l'univers d'analyse |
| Résultat à nommer | `theta_fmi2023_replication` et `caioe_fmi2023_replication` si effectivement reproduits | `theta_onet31_adapte` et `caioe_onet31_adapte` |
| Comparabilité | Vérifier contre les extrêmes historiques et les scores originaux si accessibles | **Non équivalent au FMI 2023** ; comparaison de niveaux absolus à proscrire |

**Attention aux correspondances métiers :**

- Un code `29-1141.00` est un code **O*NET-SOC**, pas forcément le même objet statistique qu'un code **US SOC 2010** à six chiffres `29-1141`.
- Retirer `.00` peut créer un **identifiant d'aide**, mais ne constitue **pas** un crosswalk correct lorsque les taxonomies sont de millésimes différents, qu'un métier est scindé, fusionné ou renommé. Utiliser les correspondances officielles O*NET/BLS et un traitement explicite des relations 1:n et n:1.
- Si plusieurs codes correspondent à un code SOC, définir à quel niveau on agrège et comment ; les auteurs utilisent des **moyennes simples** pour certaines correspondances SOC 2010 → ISCO-08, ce qui ne prouve pas que la même règle soit universelle à tous les niveaux.

Archives : [O*NET Database Releases](https://www.onetcenter.org/db_releases.html) ; [dictionnaire O*NET 28.0 – Work Context](https://www.onetcenter.org/dictionary/28.0/excel/work_context.html) ; [dictionnaire O*NET 28.0 – Job Zones](https://www.onetcenter.org/dictionary/28.0/excel/job_zones.html).

### 7.1. Pipeline vérifiable, étape par étape

1. **Ingestion / versionnage :** enregistrer millésime, URL, date, empreinte de chaque fichier et nomenclature des professions.
2. **Filtrage :** dans `Work Context`, ne conserver que les 11 `Element ID` de la section 4, et la **note contextuelle `CX`** pertinente (pas les répartitions `CXP`).
3. **Qualité :** vérifier pour chaque `O*NET-SOC Code × Element ID` qu'il existe **exactement une note utile**, que `Data Value` appartient à sa plage, et que `Not Relevant` et `Recommend Suppress` ne sont pas `Y` (ou appliquer une politique explicite de publication et de fiabilité).
4. **Normalisation :** convertir chaque note en 0–100 avec les bornes de son échelle ; renverser uniquement l'automatisation.
5. **Pivot :** obtenir une ligne par `O*NET-SOC Code` et 11 colonnes de variables ; contrôler la **couverture 11/11**.
6. **Jointure Job Zones :** jointure `O*NET-SOC Code` ; vérifier la présence de la zone ; calculer `skills_100=20×zone` et marquer le régime *historique 5 zones* ou *actuel 4 groupes*.
7. **Agrégation :** calculer les cinq dimensions Work Context, plus `skills_100` ; puis `theta` par moyenne égale des six dimensions.
8. **Harmonisation codes :** rattacher la nomenclature de **l'AIOE** à celle de θ avec des tables de correspondance validées.
9. **C-AIOE :** appliquer la formule avec un **AIOE positif et compatible** et un `theta_min` défini par l'univers d'analyse ; calculer `w=1` et `w=0,5`.
10. **Audits :** vérifier `0≤theta≤1`, `0≤C-AIOE≤AIOE` seulement lorsque `AIOE≥0` et `θ≥θ_min`; tester valeurs manquantes, doublons, dispersion, réplicabilité et différences entre versions.

### 7.2. Contrôles à effectuer **avant** de publier un score métier

- [ ] Les **11 identifiants** correspondent réellement aux indicateurs O*NET retenus ; la variable extérieure est validée.
- [ ] Chaque note `CX` est convertie correctement en **0–100** ; aucune colonne `CXP` n'est prise pour une note moyenne.
- [ ] L'automatisation a été inversée **une seule fois** ; le travail non structuré a été conservé dans son sens positif.
- [ ] On calcule une **moyenne de six groupes**, et non de 12 variables.
- [ ] La **Job Zone** correspond au bon régime (5 niveaux historiques vs 4 groupes actuels).
- [ ] Les métiers ont été reliés à AIOE avec une **correspondance taxonomique documentée**.
- [ ] L'**échelle AIOE** est définie et compatible avec la multiplication.
- [ ] La **population** et le **minimum `theta_min`** sont fixés et archivés.
- [ ] Les valeurs manquantes et les indicateurs de précision O*NET ne sont pas masqués.
- [ ] Les scores décrits comme « répliqués FMI » sont effectivement validés contre une source de référence ; sinon étiquetés **« estimation adaptée »**.

## 8. Schéma de sortie conseillé (une ligne par métier de référence)

| Champ | Type / échelle | Raison |
|---|---|---|
| `occupation_code` | chaîne | Identifiant dans la nomenclature finale |
| `occupation_title` | chaîne | Interprétation |
| `onet_soc_code` | chaîne | Identifiant d'origine O*NET |
| `soc2010_code` | chaîne / NA | Code de rapprochement AIOE/FMI |
| `onet_release` | chaîne | Ex. `28.0` ou `31.0` |
| `job_zone_release` | chaîne | Identification du régime 5 zones / 4 groupes |
| `crosswalk_rule` | chaîne | Source et règle de conversion de métier |
| `work_context_coverage` | entier 0–11 | Nombre d'éléments complets |
| `communication_100` | 0–100 | Composante 1 |
| `responsibility_100` | 0–100 | Composante 2 |
| `physical_conditions_100` | 0–100 | Composante 3 |
| `criticality_100` | 0–100 | Composante 4 |
| `nonroutine_100` | 0–100 | Composante 5 |
| `job_zone_raw` | 1–5 ou 2–5 | Zone brute et régime |
| `skills_100` | 20–100 ou 40–100 | Composante 6 |
| `theta` | 0–1 | Complémentarité humaine potentielle |
| `theta_min_reference` | 0–1 | Minimum utilisé pour le calcul |
| `aioe_raw` | échelle d'origine | Exposition IA avant ajustement |
| `c_aioe_w1` | échelle AIOE | **Score FMI principal** |
| `c_aioe_w05` | échelle AIOE | Test de sensibilité |
| `score_method` | texte | `fmi_2023_replication` ou `onet31_adaptation` |
| `quality_flags` | texte/liste | Non-réponse, suppression, ambiguïté variable extérieure, crosswalk |

### Lecture stratégique des résultats : exposé ≠ remplaçable

| AIOE | θ | Lecture prudente dans le cadre FMI |
|---|---|---|
| Élevé | Élevé | Forte exposition **et** fort potentiel d'augmentation par l'IA ; le C-AIOE amortit l'exposition |
| Élevé | Faible | Forte exposition **et** faible complémentarité modélisée ; pression de substitution potentiellement supérieure |
| Faible | Élevé | Exposition faible malgré un contexte favorable à l'aide humaine–IA ; **pas** d'inférence automatique sur la productivité |
| Faible | Faible | Exposition faible et complémentarité modélisée faible ; l'IA peut néanmoins créer des tâches nouvelles |

**Limites d'interprétation :** les indices ne mesurent ni l'adoption effective de l'IA, ni la qualité des outils disponibles, ni les coûts de déploiement, ni l'existence de garde-fous, ni la demande, ni le nombre d'emplois détruits. Ils caractérisent un **potentiel relatif d'exposition et de complémentarité** selon les hypothèses des auteurs, datées de 2023. En 2026, les possibilités des modèles multimodaux, agents, outils et robots peuvent modifier leur validité empirique ; ne pas inférer des résultats sur un poste individuel à partir du seul métier agrégé.

## 9. Catalogue explicatif des 57 éléments Work Context (annexe de référence historique)

Cette annexe donne une **définition opérationnelle concise en français des 57 variables décrites dans l'annexe A.1 du FMI (2023)**. Les libellés ci-dessous sont historiques : O*NET 31.0 en a renommé certains ; pour l'extraction, utiliser **les `Element ID` contemporains** et le tableau de la section 4. La marque **`[θ]`** signale les **11 indicateurs retenus pour le score FMI**. Les 46 autres sont informatifs mais **n'entrent pas dans θ de référence**.

| N° | Variable (libellé historique anglais) | Explication en français | FMI θ ? |
|---:|---|---|:---:|
| 1 | Electronic Mail | Fréquence d'utilisation des courriels au travail. | — |
| 2 | Face-to-Face Discussions | Fréquence de discussions en face à face avec individus ou équipes. | **[θ]** |
| 3 | Letters and Memos | Fréquence de rédaction/usage de lettres et notes écrites. | — |
| 4 | Public Speaking | Fréquence des prises de parole devant un public. | **[θ]** |
| 5 | Telephone | Fréquence des conversations téléphoniques. | — |
| 6 | Contact With Others | Intensité générale des contacts nécessaires au travail. | — |
| 7 | Deal With Physically Aggressive People | Fréquence des contacts avec des personnes physiquement agressives. | — |
| 8 | Deal With Unpleasant or Angry People | Fréquence des interactions avec des personnes mécontentes ou hostiles. | — |
| 9 | Frequency of Conflict Situations | Fréquence des conflits à gérer. | — |
| 10 | Responsibility for Outcomes and Results | Responsabilité du travailleur pour les résultats produits par d'autres. | **[θ]** |
| 11 | Responsible for Others' Health and Safety | Responsabilité pour la santé et sécurité d'autres personnes. | **[θ]** |
| 12 | Coordinate or Lead Others | Importance de coordonner/conduire les activités d'autrui. | — |
| 13 | Deal With External Customers | Importance de traiter avec clients externes ou grand public. | — |
| 14 | Work With Work Group or Team | Importance du travail en groupe/équipe. | — |
| 15 | Spend Time Bending or Twisting the Body | Temps passé à se pencher ou se tordre. | — |
| 16 | Spend Time Climbing Ladders, Scaffolds, or Poles | Temps passé à grimper des échelles/échafaudages. | — |
| 17 | Spend Time Keeping or Regaining Balance | Temps passé à maintenir ou retrouver son équilibre. | — |
| 18 | Spend Time Kneeling, Crouching, Stooping, or Crawling | Temps passé agenouillé, accroupi ou à ramper. | — |
| 19 | Spend Time Making Repetitive Motions | Temps passé à effectuer des gestes répétitifs. | — |
| 20 | Spend Time Sitting | Temps passé assis. | — |
| 21 | Spend Time Standing | Temps passé debout. | — |
| 22 | Spend Time Using Your Hands to Handle, Control, or Feel Objects, Tools, or Controls | Usage des mains pour manipuler objets, outils et commandes. | — |
| 23 | Spend Time Walking and Running | Temps passé à marcher ou courir. | — |
| 24 | Cramped Work Space, Awkward Positions | Fréquence de travail en espaces exigus ou postures inconfortables. | — |
| 25 | Exposed to Contaminants | Fréquence d'exposition aux poussières, gaz et contaminants. | — |
| 26 | Exposed to Whole Body Vibration | Fréquence de vibrations transmises à tout le corps. | — |
| 27 | Extremely Bright or Inadequate Lighting | Exposition à des éclairages trop forts ou insuffisants. | — |
| 28 | Sounds, Noise Levels Are Distracting or Uncomfortable | Exposition à un bruit gênant ou distrayant. | — |
| 29 | Very Hot or Cold Temperatures | Exposition à des températures extrêmes. | — |
| 30 | Exposed to Disease or Infections | Exposition à des agents infectieux ou maladies. | — |
| 31 | Exposed to Hazardous Conditions | Exposition à des conditions dangereuses. | — |
| 32 | Exposed to Hazardous Equipment | Exposition à des équipements dangereux. | — |
| 33 | Exposed to High Places | Exposition au travail en hauteur. | — |
| 34 | Exposed to Minor Burns, Cuts, Bites, or Stings | Exposition à brûlures, coupures, piqûres ou morsures mineures. | — |
| 35 | Exposed to Radiation | Exposition aux radiations. | — |
| 36 | Wear Common Protective or Safety Equipment | Fréquence du port d'équipements de protection ordinaires. | — |
| 37 | Wear Specialized Protective or Safety Equipment | Fréquence du port d'équipements de protection spécialisés. | — |
| 38 | In an Enclosed Vehicle or Equipment | Fréquence de travail en véhicule ou cabine fermés. | — |
| 39 | In an Open Vehicle or Equipment | Fréquence de travail en véhicule ou machine ouverts. | — |
| 40 | Indoors, Environmentally Controlled | Travail dans un intérieur climatiquement contrôlé. | — |
| 41 | Indoors, Not Environmentally Controlled | Travail dans un intérieur sans contrôle de l'environnement. | — |
| 42 | Outdoors, Exposed to Weather | Travail en extérieur exposé aux intempéries ; correspondance opérationnelle proposée pour l'« outdoors » du FMI. | **[θ] ?** |
| 43 | Outdoors, Under Cover | Travail à l'extérieur mais sous abri ; **élément distinct** du précédent. | — |
| 44 | Physical Proximity | Degré de proximité physique nécessaire avec d'autres personnes. | **[θ]** |
| 45 | Level of Competition | Intensité de la concurrence ou des pressions compétitives. | — |
| 46 | Consequence of Error | Gravité potentielle d'une erreur difficile à corriger. | **[θ]** |
| 47 | Freedom to Make Decisions | Latitude de décision sans supervision. | **[θ]** |
| 48 | Frequency of Decision Making | Fréquence des décisions affectant personnes, ressources ou réputation. | **[θ]** |
| 49 | Impact of Decisions on Co-workers or Company Results | Importance de l'impact des décisions sur collègues/organisation. | — |
| 50 | Duration of Typical Work Week | Durée hebdomadaire typique du travail. | — |
| 51 | Pace Determined by Speed of Equipment | Degré auquel la vitesse des machines impose le rythme. | — |
| 52 | Time Pressure | Fréquence d'échéances et contraintes de temps fortes. | — |
| 53 | Work Schedules | Caractère régulier, variable ou atypique des horaires. | — |
| 54 | Degree of Automation | Niveau d'automatisation déjà présent ; **valeur inversée pour θ**. | **[θ]** |
| 55 | Importance of Being Exact or Accurate | Importance d'une très haute précision dans l'exécution. | — |
| 56 | Importance of Repeating Same Tasks | Importance de répéter des tâches semblables. | — |
| 57 | Structured versus Unstructured Work | Latitude pour définir tâches, priorités et objectifs ; grande latitude = plus non-routinier. | **[θ]** |

## 10. Sources officielles et traçabilité

1. **FMI, 2023 — étude et équations (§2.2–2.4, §5.1, annexe A.1).** https://www.imf.org/-/media/files/publications/wp/2023/english/wpiea2023216-print-pdf.pdf
2. **O*NET 31.0 — dictionnaire Work Context (colonnes et 57 descripteurs).** https://www.onetcenter.org/dictionary/31.0/csv/work_context.html
3. **O*NET 31.0 — dictionnaire Job Zones (4 catégories).** https://www.onetcenter.org/dictionary/31.0/csv/job_zones.html
4. **O*NET — pages officielles des 57 variables actuelles.** https://www.onetonline.org/find/descriptor/browse/4.C/
5. **O*NET — définition des échelles et score standardisé.** https://www.onetonline.org/help/online/scales
6. **O*NET — valeurs minimum et maximum par échelle.** https://www.onetcenter.org/dictionary/31.0/csv/scales_reference.html
7. **O*NET, 2025 — transition Job Zones 5 → 4 groupes.** https://www.onetcenter.org/reports/Job_Zone_Transition.html
8. **O*NET — archives historiques des versions.** https://www.onetcenter.org/db_releases.html
9. **Felten et al. — dépôt des données AIOE.** https://github.com/AIOE-Data/AIOE
10. **Banque mondiale — fiche de reproductibilité de l'étude du FMI.** https://reproducibility.worldbank.org/catalog/403

---

**Synthèse décisionnelle :** pour obtenir un score **scientifiquement défendable**, séparer impérativement **(a) la reconstruction θ à partir des 11 Work Context et de Job Zones**, **(b) l'obtention de l'AIOE Felten sur une échelle compatible**, **(c) la correction multiplicative C-AIOE**, **(d) l'harmonisation des métiers et des millésimes**. L'ambiguïté exacte de l'indicateur extérieur, la transition des Job Zones et le changement de nomenclature SOC sont les trois principaux risques de faux sentiment de réplication.
