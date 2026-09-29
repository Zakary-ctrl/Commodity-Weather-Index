# Commodity Weather Index

Tableau de bord mondial des anomalies météo sur 41 grandes ceintures agricoles (maïs, soja, blé, café, cacao, sucre, coton, jus d'orange, huile de palme, thé, riz) et de leur lecture pour les marchés à terme.

- **À chaque ouverture**, la page récupère les dernières prévisions (Open-Meteo) directement dans le navigateur du visiteur et recalcule écarts à la normale, alertes et scores de risque.
- **Chaque jour**, GitHub Actions recalcule tout et rédige les encadrés de vulgarisation (avec Claude si une clé API est fournie, sinon par gabarit).
- **Chaque heure**, pendant les premiers jours, GitHub Actions complète l'historique 1991-2020 qui sert aux normales, dans la limite du quota gratuit d'Open-Meteo.

Mise en ligne : voir **GUIDE-GITHUB.md**.

## Lancer en local

```bash
pip install -r requirements.txt
python run.py daily --no-llm   # prévisions + alertes (sans clé API Claude)
python run.py fill             # complète l'historique 1991-2020 (à relancer jusqu'à 100 %)
python make_dashboard.py       # construit site/index.html
open site/index.html
```

## Structure

| Fichier | Rôle |
| --- | --- |
| `config/zones.json` | Zones, points pondérés, calendriers culturaux, règles et seuils |
| `pipeline/fetch.py` | Collecte Open-Meteo, suivi du quota, cache de l'historique (`data/raw/`) |
| `pipeline/aggregate.py` | Normales journalières 1991-2020 par zone, séries de la fenêtre courante |
| `pipeline/metrics.py` | Indicateurs, moteur de règles, sévérité, score de risque |
| `pipeline/llm.py` | Prompt système, appel Claude, validateur, gabarit de repli |
| `pipeline/build.py` | Assemble `data/latest.json` |
| `dashboard/app.html` | L'interface et le moteur de recalcul en direct (JavaScript) |
| `make_dashboard.py` | Construit `site/` (GitHub Pages) et `dist/observatoire.html` (version autonome) |
| `.github/workflows/update.yml` | Automatisation GitHub Actions + GitHub Pages |

La logique de `pipeline/metrics.py` existe aussi en JavaScript dans `dashboard/app.html` (recalcul à l'ouverture). Toute modification d'une règle de calcul doit être faite aux deux endroits.

## Ajouter une zone ou une règle

Tout se fait dans `config/zones.json`. Métriques disponibles pour les règles : `pr_obs30_pct`, `pr_fc14_pct`, `tn_fc7_min`, `tx_fc7_max`, `n_tx_gt` (avec `t`, le seuil de chaleur en °C). Un nouveau point déclenche automatiquement le téléchargement de son historique.

## Limites connues

- Poids des points = approximation de la production, à remplacer par MapSPAM.
- Les 30 derniers jours sont des analyses de modèles, pas des relevés de stations.
- Open-Meteo est gratuit en usage non commercial uniquement (CC BY 4.0, citer la source).
- Information, pas une recommandation d'investissement.
