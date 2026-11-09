# Product Requirements Document (PRD) — SupClair
**Version :** 1.0  
**Statut :** Approuvé & En Développement  
**Auteurs :** Équipe Produit & Data Visualization (SupClair CivicTech)  
**Date :** Juin 2025 / Session Parcoursup 2025–2026  
**Cible :** Lycéens de Première/Terminale, Parents d'élèves, Professeurs principaux, Conseillers d'orientation  

---

## 1. Executive Summary & Vision Produit

### 1.1 Contexte & Problématique
Chaque année en France, près de **950 000 candidats** utilisent la plateforme nationale **Parcoursup**. Malgré l'ouverture des données publiques de la plateforme (Open Data SIES / MESR) et des initiatives comme SupTracker ou les rapports d'admission annuels, le processus génère une anxiété massive, documentée quotidiennement sur les forums communautaires (notamment r/parcoursup et r/etudiants) :
1. **Confusion systémique entre "Position en liste d'attente" et "Rang pédagogique fixe" :** Les candidats voient leur position descendre chaque matin sans comprendre s'ils ont une chance réelle d'être admis, menant à des abandons prématurés ou des paniques infondées.
2. **Le piège statistique du "Taux d'accès brut" :** Un taux d'accès officiel affiché à 15% peut correspondre soit à une filière très populaire à recrutement moyen (effet de volume massif, ex: Licence Droit), soit à une formation élitiste inaccessible (médiane à 18/20, ex: CPES). À l'inverse, des classes préparatoires affichent 30% d'accès uniquement par auto-censure des candidats.
3. **Intimidation statistique :** Les rapports officiels sont des PDF de 40 pages ou des tableaux bruts illisibles pour un élève de 17 ans et sa famille.
4. **Réforme du Bac et impact des spécialités :** L'inadéquation de la "doublette" de spécialités de Terminale (ex: abandonner les maths pour postuler en école de commerce) est souvent découverte trop tard par le candidat.

### 1.2 Vision & Proposition de Valeur
**SupClair** est un dashboard d'aide à la décision publique et civique ("CivicTech"), conçu pour transformer l'opacité et le stress de Parcoursup en un parcours d'anticipation limpide, probabiliste et centré sur l'humain.

> **Promesse utilisateur :** *"En 30 secondes et 3 réglages, visualisez où vous vous situez réellement par rapport aux cohortes des 3 dernières années, comprenez votre cinétique d'appel jour par jour et sécurisez votre portefeuille de vœux sans angoisse."*

---

## 2. Objectifs & Indicateurs de Succès (KPIs)

### 2.1 Objectifs Produit
- **Clarté cognitive immédiate :** Rendre compréhensible en moins de 5 secondes l'état d'admission d'un vœu à un lycéen.
- **Désensibilisation au stress :** Fournir une cinétique temporelle prédictive (projection de l'offre à J+X jours) pour dissuader les décisions impulsives entre J1 et J5.
- **Équilibrage du portefeuille de vœux :** Guider l'utilisateur pour qu'aucun dossier ne contienne 0 vœu de sécurité.

### 2.2 Métriques de Succès (KPIs)
- **Taux de compréhension "Rang vs Position" :** > 90% sur tests utilisateurs.
- **Taux de diversification des portefeuilles :** 100% des utilisateurs guidés vers au moins 1 vœu classifié "Sécurité".
- **Temps moyen de session d'arbitrage :** < 3 minutes pour évaluer 6 vœux.
- **Indice de Confiance Utilisateur (CSAT / NPS) :** NPS > +55 auprès des familles et enseignants.

---

## 3. Personas Utilisateurs

### Persona 1 : Camille (17 ans, Terminale Générale)
- **Profil :** 15.8 de moyenne générale, Spécialités Maths + Physique-Chimie, Option Maths Expertes.
- **Pain Point :** Classée 540e en attente en MPSI au 2 juin. Elle pense être refusée et ne dort plus, alors que l'année dernière le dernier admis était le 620e au 8 juin.
- **Besoin :** Savoir si son rang est dans la "Zone Sûre" ou "Tampon" et quand l'offre devrait tomber.

### Persona 2 : Marc (Parent d'élève, 48 ans)
- **Profil :** Cadre, peu familier avec les réformes du lycée modulaire.
- **Pain Point :** Voit des taux d'accès de 22% sur une école d'ingénieurs et 40% sur une licence universitaire, mais ignore pourquoi son fils est accepté dans l'un et recalé dans l'autre.
- **Besoin :** Une visualisation claire montrant les notes réelles des admis plutôt que des pourcentages trompeurs.

### Persona 3 : Sarah (Professeure Principale de Terminale)
- **Profil :** En charge de 34 élèves pour la formulation des vœux et le suivi des phases d'admission.
- **Pain Point :** Passe des heures à expliquer les mêmes principes statistiques de base sur les listes d'attente.
- **Besoin :** Un support visuel interactif projetable en classe pour la phase d'orientation et de confirmation.

---

## 4. Architecture Fonctionnelle & Modules Clés

```
┌────────────────────────────────────────────────────────────────────────┐
│                   PERSISTENT GLOBAL CONTROL BAR                        │
│ [ Moyenne: 10.0-19.5 ] [ Doublette Spés ] [ Maths Exp ] [ Boursier ]   │
│ ────────────────────────────────────────────────────────────────────── │
│ Portfolio Diagnostic Pill: [ X Sécurité ] [ Y Cible ] [ Z Ambitieux ] │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ (Live recalculation)
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
┌───────────────────┐       ┌───────────────────┐       ┌───────────────────┐
│     MODULE A      │       │     MODULE B      │       │     MODULE C      │
│  Trajectoire      │       │  Comparateur      │       │  Matrice Vraie    │
│  d'Attente &      │       │  Boxplots         │       │  Sélectivité      │
│  Jauge Historique │       │  Alignés          │       │  (Taux vs Médiane)│
└───────────────────┘       └───────────────────┘       └───────────────────┘
```

### Module 1 : Bandeau de Profil Académique Persistant ("Where Do I Stand?")
- **Curseur de Moyenne Générale :** Intervalle de `10.0` à `19.5`, incrément `0.1`. Calcul automatique de la mention au Baccalauréat (*Passable, Assez Bien, Bien, Très Bien, Félicitations du Jury*).
- **Sélecteur de Spécialités (Doublettes) :** Prise en compte des 5 combinaisons majeures (`Maths + SES`, `Maths + Physique`, `Maths + NSI`, `SES + HGGSP`, `Physique + SVT`).
- **Modulateurs & Bonus :**
  - Toggle `Maths Expertes` (bonus d'adéquation + boost de rang de 10 à 15%).
  - Toggle `Simulation Boursier` (application du quota d'accès légal, gain simulé de rang d'environ 8%).
- **Diagnostic en temps réel du Portefeuille :**
  - Badge de solidité : *Portefeuille Sécurisé* vs *Portefeuille à Risque (0 vœu de secours)*.
  - Compteur dynamique : Nombre de vœux *Sécurité (Safety)*, *Cible (Target)*, *Ambitieux (Reach)*.

### Module 2 : Trajectoire d'Attente & Jauge Historique (Module A)
- **Séparation sémantique des 3 métriques :**
  1. *Position en liste d'attente (Dynamique)* : Décroît chaque matin selon les désistements.
  2. *Mon Rang Pédagogique (Fixe)* : Rang attribué définitivement par la commission d'examen des vœux.
  3. *Rang du Dernier Appelé (Historique N-1 à N-3)* : Donnée pivot d'arbitrage.
- **Jauge d'Admission Horizontale Multi-Zones :**
  - **Zone Verte (Sécurisée) :** Rang $\le \min(\text{Cutoff}_{2023..2025})$.
  - **Zone Ambre (Tampon / Buffer) :** Entre le minimum et le maximum historique $+15\%$. Dépend des désistements intermédiaires.
  - **Zone Rouge (Tension / Peu Probable) :** Au-delà des seuils d'appel observés.
  - Curseur positionnel de l'élève comparé au front d'appel du jour (ex: J+6).
- **Cinétique d'Appel (Courbe prédictive J1 à J14) :**
  - Comparaison entre la vitesse réelle de l'année en cours, la moyenne historique et la projection à J+14.
  - Estimation de date d'offre ferme : ex. *"Proposition attendue vers J+4 à J+6"*.

### Module 3 : Comparateur de Boxplots Alignés (Module B)
- **Normalisation sur axe unique :** Alignement strict de l'ensemble des 6 formations sur une échelle $10/20$ à $20/20$.
- **Décomposition statistique sans jargon :**
  - Whisker (Moustache) : Étendue du 10e au 90e percentile (80% des admis).
  - Boîte (Interquartile) : 25e au 75e percentile (50% centraux des admis).
  - Médiane ($p50$) : Note repère.
- **Ligne repère "Vous êtes ici" :** Ligne verticale traversant l'ensemble des formations selon le slider de note du candidat.
- **Indicateur d'Affinité de Spécialité :** Taux réel d'admis ayant la même doublette (Voie royale $\ge 30\%$, Voie secondaire acceptée $\ge 10\%$, Inadaptée $< 5\%$).

### Module 4 : Matrice de Vraie Sélectivité (Module C)
- **Graphique 2D de débiaisement :**
  - Axe X : Taux d'Accès Officiel Parcoursup ($0\%$ à $75\%$).
  - Axe Y : Note Médiane des Admis au Baccalauréat ($10$ à $20/20$).
- **Typologie des 4 Quadrants :**
  1. *Élite Auto-Censurée :* Taux d'accès correct (20–35%), mais médiane $\ge 17.5/20$ (CPGE, CPES).
  2. *Goulot d'Étranglement (Volume) :* Taux d'accès très faible ($\le 20\%$) dû à la masse de vœux, mais médiane accessible $\le 14/20$ (Licences en tension, IFSI).
  3. *Sélectivité Extrême :* Volume énorme + niveau stratosphérique (PASS, doubles licences sélectives).
  4. *Sécurité Accessible :* Taux d'accès élevé + notes compatibles dossier moyen.

---

## 5. Spécifications Techniques & Données

### 5.1 Stack & Intégration
- **Frontend :** Single-Page Application React (React 18/19), JavaScript (ES2023) / TypeScript.
- **Styling :** Tailwind CSS avec palette sémantique (Indigo/Ardoise Slate, Émeraude, Ambre, Rose).
- **Moteur Visuel :** Recharts / Custom SVG réactif sans dépendance externe lourde.
- **Responsive Design :** Desktop-first (optimisé tableaux de bord 1440px / 1280px), entièrement adaptatif tablette et mobile.

### 5.2 Schéma de Données (Program Schema)
```typescript
interface ProgramData {
  id: string;
  name: string;
  school: string;
  type: string;
  capacite: number;
  voeux: number;
  tauxAcces: number; // en %
  medianGrade: number; // /20
  quadrantCategory: 'Élite Auto-Censurée' | 'Goulot d’Étranglement' | 'Sélectivité Extrême' | 'Sécurité Accessible';
  grades: {
    p10: number;
    p25: number;
    p50: number;
    p75: number;
    p90: number;
  };
  doublettes: Record<string, number>; // ex: { 'Maths + SES': 48 }
  mathsExpertesBoost: number;
  baseRankAt16: number;
  rankSensitivity: number;
  lastCalled: {
    y2023: number;
    y2024: number;
    y2025: number;
  };
  currentCalledRank: number;
  dailyVelocity: number;
  cinetiqueAppel: Array<{
    day: string;
    currentYear: number | null;
    projected?: number;
    avgHistorical: number;
  }>;
}
```

### 5.3 Algorithme de Simulation de Rang
$$\text{RangSimulé} = \text{BaseRank}_{16} - (\text{Moyenne} - 16.0) \times \text{Sensibilité} + \Delta_{\text{Doublette}} - \text{Bonus}_{\text{MathsExp}} - \text{Bonus}_{\text{Boursier}}$$
- $\Delta_{\text{Doublette}}$ pénalise les profils minoritaires ($+50$ à $+300$ places).
- $\text{Bonus}_{\text{MathsExp}} \approx 10\% \text{ à } 12\%$ d'amélioration de rang.
- $\text{Bonus}_{\text{Boursier}} \approx 8\%$ d'amélioration de rang selon quota légal.

---

## 6. Accessibilité (a11y), Éthique & Garde-fous

1. **Aucune promesse contractuelle :** Mention explicite systématique en pied de page : *"Outil d'aide à la décision basé sur les données publiques ouvertes SIES. Ne constitue pas une garantie juridique d'admission."*
2. **Accessibilité des contrastes :** Conformité WCAG AA sur les textes statistiques et les zones de danger (palette couleur doublement codée avec icônes et labels textuels pour daltoniens).
3. **Pédagogie bienveillante :** Présence de bulles d'explications contextuelles activables ("Conseils Anti-Panique") pour désamorcer l'angoisse des candidats.

---

## 7. Roadmap Produit

| Phase | Jalons & Livrables | Horizon |
| :--- | :--- | :--- |
| **Phase 1 (Actuelle)** | Prototype Dashboard interactif, 6 filières représentatives, modules A, B et C, simulation temps réel. | T2 2025 |
| **Phase 2 (V2.0)** | Importation directe de la liste de vœux via export JSON Parcoursup, élargissement à 12 000 formations via API Open Data MESR. | T3 2025 |
| **Phase 3 (V2.5)** | Notifications push d'évolution quotidienne du front d'appel (J1 à J14) et simulateur de phase complémentaire. | T4 2025 |
