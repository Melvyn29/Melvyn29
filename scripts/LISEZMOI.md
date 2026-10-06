# Graphiques du profil

Les cartes en haut du profil (`assets/*.svg`, en clair et en sombre) sont produites par
`scripts/generate.py`, lancé chaque nuit par `.github/workflows/stats.yml`.
Le workflow se lance aussi à la main : onglet **Actions** › *Graphiques du profil* › *Run workflow*.

## Jeton d'accès (à faire une fois)

Les dépôts étant privés, le script lit les données avec un jeton personnel en **lecture seule** :

1. GitHub › Settings › Developer settings › Personal access tokens › **Fine-grained tokens** › *Generate new token*.
2. Resource owner `Melvyn29`, **All repositories**, expiration au choix.
3. Repository permissions : **Contents : Read-only** (Metadata : Read-only s'ajoute seul).
4. Copier le jeton, puis dans ce dépôt : Settings › Secrets and variables › Actions ›
   *New repository secret*, nom `PROFILE_STATS_TOKEN`.

À l'expiration du jeton, le workflow échoue (courriel de GitHub) : en recréer un, mettre le secret à jour.

## Ce que lit le script

- graphe et contributions par mois : le calendrier de contributions GitHub (dernière année) ;
- « Quand je code » : l'heure des commits de la branche par défaut de chaque dépôt (heure locale du commit) ;
- langages : la somme des langages de tous les dépôts ;
- « En chiffres » : l'arborescence de `elens-platform` (fichiers `*.test.ts(x)`, migrations, pages, suites SQL).

Variables facultatives : `PROFILE_TZ` (défaut `America/Toronto`), `PROFILE_STATS_REPO` (défaut `elens-platform`).

Police : Cormorant Garamond Italic (SIL Open Font License, `OFL-cormorant.txt`), convertie en tracés
dans `glyphs.json` pour que le rendu ne dépende d'aucune police installée.

## Lancer en local

    PROFILE_STATS_TOKEN=... python scripts/generate.py
