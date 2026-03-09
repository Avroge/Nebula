import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")

notion = Client(auth=NOTION_TOKEN, notion_version=NOTION_VERSION)

db = notion.databases.retrieve(database_id=DATABASE_ID)

data_sources = db.get("data_sources", [])
if not data_sources:
    raise SystemExit("ERREUR: Aucun data_source trouvé dans ce database.")

# En général il n’y en a qu’un
DATA_SOURCE_ID = data_sources[0]["id"]
print("Data source id:", DATA_SOURCE_ID)
print("Data source name:", data_sources[0].get("name"))

# notion-sdk-py n’a pas toujours un wrapper 'data_sources', donc on appelle l’API “raw”
ds = notion.request(f"data_sources/{DATA_SOURCE_ID}", "GET")

print("\nProperties:")
for name, prop in ds["properties"].items():
    print(f"- {name}: {prop['type']}")