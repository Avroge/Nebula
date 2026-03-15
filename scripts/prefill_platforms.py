import os
import re
import unicodedata
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")

PROP_PLATFORM = "Plateforme"  # ton nom exact

if not NOTION_TOKEN or not DATA_SOURCE_ID:
    raise SystemExit("ERREUR: NOTION_TOKEN / NOTION_DATA_SOURCE_ID manquant dans .env")

notion = Client(auth=NOTION_TOKEN, notion_version=NOTION_VERSION)


def norm_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


PLATFORMS_FR = [
    "Netflix",
    "Prime Video",
    "Disney+",
    "Canal+",
    "Apple TV+",
    "Paramount+",
    "Max",
    "Crunchyroll",
    "YouTube (location/achat)",
    "Google Play (location/achat)",
    "Molotov",
    "Arte",
    "France.tv",
    "MyCanal",
    "OCS",
]


def main():
    ds = notion.request(f"data_sources/{DATA_SOURCE_ID}", "GET")

    prop = ds["properties"].get(PROP_PLATFORM)
    if not prop:
        raise SystemExit(f"ERREUR: Propriété '{PROP_PLATFORM}' introuvable.")
    if prop["type"] != "select":
        raise SystemExit(f"ERREUR: '{PROP_PLATFORM}' n'est pas un select (type actuel: {prop['type']}).")

    existing_options = prop["select"].get("options", [])
    by_key = {}

    for opt in existing_options:
        name = opt.get("name")
        if not name:
            continue
        k = norm_key(name)
        if k not in by_key:
            by_key[k] = opt

    added = []
    for name in PLATFORMS_FR:
        k = norm_key(name)
        if k in by_key:
            continue
        by_key[k] = {"name": name}
        added.append(name)

    if not added:
        print("OK: aucune plateforme à ajouter (déjà pré-rempli).")
        return

    new_options = list(by_key.values())

    body = {
        "properties": {
            PROP_PLATFORM: {
                "select": {
                    "options": new_options
                }
            }
        }
    }

    notion.request(f"data_sources/{DATA_SOURCE_ID}", "PATCH", body=body)

    print(f"OK: {len(added)} plateformes ajoutées à '{PROP_PLATFORM}'.")
    print("Ajoutées:", ", ".join(added))


if __name__ == "__main__":
    main()