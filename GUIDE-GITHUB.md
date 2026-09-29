# Mettre Commodity Weather Index en ligne avec GitHub (environ 15 minutes)

Résultat : un site public à l'adresse `https://TON-PSEUDO.github.io/commodity-weather-index/`, qui se met à jour tout seul, même quand ton Mac est éteint.

## 1. Créer le compte et le dépôt

1. Crée un compte sur https://github.com/signup (gratuit). Choisis ton pseudo avec soin : il apparaîtra dans l'adresse du site.
2. En haut à droite, clique sur **+** puis **New repository**.
3. Nom : `commodity-weather-index`. Coche **Public**. Ne coche rien d'autre. Clique **Create repository**.

## 2. Déposer les fichiers

1. Sur la page du dépôt vide, clique sur le lien **uploading an existing file**.
2. Ouvre le dossier `Observatoire-Soft-Commodities` dans le Finder, sélectionne **tout son contenu** (`Cmd + A`) et glisse-le dans la page GitHub. Les dossiers `config`, `dashboard`, `data` et `pipeline` doivent apparaître.
3. En bas, clique **Commit changes**.

Le Finder cache les dossiers dont le nom commence par un point : le fichier d'automatisation n'a donc pas été envoyé. On le crée à la main :

4. Sur la page du dépôt, clique **Add file** puis **Create new file**.
5. Dans le champ du nom, tape exactement : `.github/workflows/update.yml` (les `/` créent les dossiers).
6. Ouvre le fichier `github-actions-update.yml` du dossier avec TextEdit, copie tout son contenu et colle-le dans GitHub.
7. Clique **Commit changes**, puis encore **Commit changes** dans la fenêtre qui s'ouvre.

## 3. Régler deux paramètres

1. Onglet **Settings** du dépôt, puis **Pages** dans le menu de gauche. Sous **Build and deployment**, dans **Source**, choisis **GitHub Actions**.
2. Toujours dans **Settings**, menu **Actions** puis **General**. Descends jusqu'à **Workflow permissions**, coche **Read and write permissions**, clique **Save**.

## 4. (Optionnel) Brancher Claude pour les encadrés

Sans clé, les encadrés sont générés par un gabarit exact mais plus sec. Avec une clé, ils sont rédigés par Claude chaque matin (quelques euros par mois au plus).

1. Crée une clé sur https://console.anthropic.com (menu **API Keys**). Garde-la pour toi : ne la colle jamais dans un fichier du dépôt.
2. Dans le dépôt : **Settings**, **Secrets and variables**, **Actions**, bouton **New repository secret**.
3. Nom : `ANTHROPIC_API_KEY`. Valeur : ta clé. **Add secret**.
4. Facultatif, onglet **Variables** de la même page : variable `OSC_MODEL` avec l'identifiant du modèle Claude à utiliser (liste sur https://docs.claude.com/en/docs/about-claude/models). Sans elle, un modèle par défaut est utilisé ; s'il est refusé, le gabarit prend le relais.

## 5. Premier lancement

1. Onglet **Actions**. Si GitHub demande de les activer, accepte.
2. Clique sur **Commodity Weather Index - mise à jour** à gauche, puis **Run workflow** à droite, puis le bouton vert.
3. Attends 10 à 15 minutes (pastille verte). Le lien du site apparaît dans le détail de l'exécution, sous **deploy**, et dans **Settings** puis **Pages**.

Ensuite, tout est automatique : une exécution par heure (courte quand il n'y a rien à faire), un recalcul complet chaque jour vers 6 ou 7 h, heure de Paris.

## Ce qui se passe les premiers jours

| Délai | Ce qui fonctionne |
| --- | --- |
| Dès le premier lancement | Carte, prévisions en direct, alertes de gel et de chaleur, graphiques |
| Après 2 à 3 jours | Écarts à la normale et alertes de sécheresse ou de pluie excessive pour la saison en cours |
| Après une dizaine de jours | Normales complètes sur les 12 mois : l'outil est autonome toute l'année |

Le pourcentage d'avancement s'affiche sous la carte tant que l'historique n'est pas complet.

## Si quelque chose coince

- **Croix rouge dans Actions** : clique sur l'exécution pour lire l'erreur. `Permission denied` ou `403` au moment du `git push` : refais l'étape 3.2.
- **Le site affiche 404** : vérifie l'étape 3.1, puis relance le workflow.
- **« quota Open-Meteo atteint »** dans le journal : c'est normal pendant la phase de remplissage, l'exécution suivante reprendra.
- **Modifier une zone ou un seuil** : ouvre `config/zones.json` sur GitHub, clique sur le crayon, modifie, **Commit changes**. La prochaine exécution en tient compte.
