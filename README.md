# Nebula

Nebula est une application Python pour gérer une watchlist de films dans **Notion**, enrichie automatiquement avec les données de **TMDB** (titre, année, note, genres, affiche et plateforme de visionnage).

Le projet propose :
- une **interface graphique** (`app.py`) pour un usage quotidien,
- un module métier (`notion_movies.py`) qui centralise la logique Notion/TMDB,
- des scripts utilitaires pour inspection/préremplissage.

---

## Fonctionnalités principales

- 🔎 Recherche de films via TMDB avec suggestions.
- ➕ Ajout automatique d’un film dans Notion.
- ✅ Gestion des statuts (`À voir`, `Vu`, `À revoir`, `En cours`).
- 🖼️ Affichage des affiches avec cache local.
- 🗂️ Vue liste/galerie, tri, filtres et recherche locale.
- 🧾 Import en lot de titres (depuis l’UI).

---

## Prérequis

- Python **3.10+** recommandé
- Un compte Notion avec une base (data source) compatible
- Une clé API TMDB

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> Si votre `requirements.txt` est incomplet, installez au minimum :
>
> ```bash
> pip install requests python-dotenv notion-client pillow
> ```

---

## Configuration

Créez un fichier `.env` à la racine du projet :

```env
NOTION_TOKEN=secret_xxx
NOTION_DATA_SOURCE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TMDB_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_VERSION=2025-09-03
```

### Propriétés attendues dans Notion

La data source Notion doit contenir (au moins) ces propriétés :

- `Titre` (title)
- `Statut` (status)
- `Année de sortie` (number)
- `Genre` (multi_select)
- `Plateforme` (select)
- `Note` (number)
- `Date de visionnage` (date)
- `Poster` (files)

---

## Lancer l’application

### Interface graphique

```bash
python app.py
```

### Utilisation du module (script)

Le module `notion_movies.py` expose des fonctions réutilisables (ex: `auto_add`, `update_status`, `delete_movie`, `list_movies_detailed`).

---

## Scripts utilitaires présents

- `inspect_db.py` : inspection de la base/data source Notion.
- `inspect_data_source.py` : vérification de la structure côté Notion.
- `prefill_tmdb_genres.py` : préremplissage/gestion des genres TMDB.
- `prefill_platforms.py` : aide au préremplissage des plateformes.

---

## Structure rapide

```text
.
├── app.py                 # UI Tkinter
├── notion_movies.py       # Logique Notion + TMDB
├── movies_cli.py          # CLI legacy / expérimental
├── inspect_db.py
├── inspect_data_source.py
├── prefill_tmdb_genres.py
├── prefill_platforms.py
├── settings.json          # Préférences UI
└── README.md
```

---

## Bonnes pratiques

- Ne versionnez pas votre fichier `.env`.
- Vérifiez les noms exacts des propriétés Notion (ils doivent matcher le code).
- En cas d’erreur API, consultez `app.log`.

---

## Statut du projet

Projet personnel en évolution continue. Les fonctionnalités et scripts peuvent évoluer rapidement.
