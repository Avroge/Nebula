import os
import re
import unicodedata
import requests
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

PROP_GENRE = "Genre"

if not NOTION_TOKEN or not DATA_SOURCE_ID or not TMDB_API_KEY:
    raise SystemExit("Variables .env manquantes")

notion = Client(auth=NOTION_TOKEN, notion_version=NOTION_VERSION)


def norm_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def tmdb_movie_genres(language="fr-FR"):
    url = "https://api.themoviedb.org/3/genre/movie/list"

    params = {
        "api_key": TMDB_API_KEY,
        "language": language
    }

    r = requests.get(url, params=params)
    r.raise_for_status()

    data = r.json()

    return [g["name"] for g in data.get("genres", [])]


def get_current_multi_select_options(ds, prop_name):
    prop = ds["properties"].get(prop_name)

    if not prop:
        raise SystemExit(f"Propriété '{prop_name}' introuvable")

    if prop["type"] != "multi_select":
        raise SystemExit(f"'{prop_name}' n'est pas un multi_select")

    return prop["multi_select"]["options"]


def main():

    ds = notion.request(f"data_sources/{DATA_SOURCE_ID}", "GET")

    existing_options = get_current_multi_select_options(ds, PROP_GENRE)

    by_key = {}

    for opt in existing_options:
        name = opt["name"]
        k = norm_key(name)

        if k not in by_key:
            by_key[k] = opt

    tmdb_names = tmdb_movie_genres()

    added = []

    for name in tmdb_names:
        k = norm_key(name)

        if k in by_key:
            continue

        by_key[k] = {"name": name}
        added.append(name)

    if not added:
        print("OK : aucun genre à ajouter")
        return

    new_options = list(by_key.values())

    body = {
        "properties": {
            PROP_GENRE: {
                "multi_select": {
                    "options": new_options
                }
            }
        }
    }

    notion.request(
        f"data_sources/{DATA_SOURCE_ID}",
        "PATCH",
        body=body
    )

    print(f"{len(added)} genres ajoutés")
    print(", ".join(added))


if __name__ == "__main__":
    main()