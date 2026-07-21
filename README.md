# Veille logements CROUS

Vérifie automatiquement, toutes les 20 minutes, si un nouveau logement
correspondant à tes critères (par défaut : Gironde/33, individuel) apparaît
sur trouverunlogement.lescrous.fr, et t'envoie un email.

## Mise en place (10 min)

### 1. Créer le dépôt GitHub

- Crée un nouveau dépôt **privé** sur GitHub (ex: `crous-watch`).
- Mets-y tous les fichiers de ce dossier (via l'upload web, ou `git push` en local).

### 2. Créer un mot de passe d'application Gmail

Ton compte Gmail doit avoir la validation en 2 étapes activée, puis :
`myaccount.google.com` → Sécurité → Validation en 2 étapes → Mots de passe des applications.
Crée-en un pour "Mail" et copie le code à 16 caractères.

### 3. Ajouter les secrets GitHub

Dans le dépôt : **Settings → Secrets and variables → Actions → Secrets**, ajoute :

| Nom | Valeur |
|---|---|
| `GMAIL_USER` | ton adresse Gmail (ex: kennethvodounon@gmail.com) |
| `GMAIL_APP_PASSWORD` | le mot de passe d'application créé à l'étape 2 |
| `MAIL_TO` | (optionnel) adresse de destination si différente de GMAIL_USER |

### 4. (Optionnel) Ajuster les critères

Toujours dans **Settings → Secrets and variables → Actions**, onglet **Variables**, tu peux ajouter :

| Nom | Défaut | Rôle |
|---|---|---|
| `SEARCH_URL` | `.../tools/47/search` | URL de recherche CROUS. Va sur le site, filtre comme tu veux (ville, prix...), copie l'URL de la barre d'adresse. |
| `POSTAL_PREFIX` | `33` | Garde uniquement ce département (33 = Gironde). Vide = pas de filtre. |
| `COHAB_INCLUDE` | `Individuel` | Type de logement à garder. |
| `SURFACE_MIN` | `0` | Surface minimale en m² (ex: `15` pour exclure les petites chambres). |

### 5. Activer GitHub Pages (pour le récapitulatif consultable)

**Settings → Pages** → Source : "Deploy from a branch" → Branch : `main`, dossier `/docs` → Save.

Après la première exécution, la page sera visible à :
`https://<ton-pseudo-github>.github.io/<nom-du-depot>/`

⚠️ Avec GitHub Pages classique sur un dépôt **privé**, la page n'est visible
qu'aux personnes ayant accès au dépôt (ou toi seul si owner) — sauf si tu as
GitHub Pro/Team. Si tu veux que la page soit publique sans payer, mets le
dépôt en **public** (le contenu n'expose que des logements déjà publics sur
le site du CROUS, aucune donnée personnelle).

### 6. Lancer un premier test

Onglet **Actions** → "Veille logements CROUS" → **Run workflow** (bouton à droite).
Regarde les logs : ça te dira combien de logements ont été trouvés.

## Fonctionnement

- Le script se lance tout seul toutes les 20 min via GitHub Actions (gratuit
  pour un usage de ce volume).
- Il compare les logements trouvés à ceux déjà vus (`data/state.json`,
  committé automatiquement à chaque run).
- Un nouveau logement correspondant aux critères → email immédiat.
- La page `docs/index.html` liste en permanence tout ce qui est disponible
  *maintenant* selon tes critères, mise à jour à chaque vérification.

## Limites à connaître

- GitHub peut retarder les cron jobs de quelques minutes en cas de forte
  charge sur leur infrastructure — ce n'est pas garanti à la seconde près.
- Si le CROUS change la structure de sa page, le script peut cesser de
  détecter des logements ; en cas de doute, lance "Run workflow" manuellement
  et vérifie le nombre de logements trouvés dans les logs.
- Ce script ne fait que **te prévenir** : il ne réserve rien à ta place, il
  faut toujours candidater toi-même sur le site.
