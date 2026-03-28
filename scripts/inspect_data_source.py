import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")

if not NOTION_TOKEN or not DATA_SOURCE_ID:
    raise SystemExit("ERREUR: NOTION_TOKEN / NOTION_DATA_SOURCE_ID manquant dans .env")

notion = Client(auth=NOTION_TOKEN, notion_version=NOTION_VERSION)

ds = notion.request(f"data_sources/{DATA_SOURCE_ID}", "GET")

print("Data source id:", ds.get("id"))
print("Data source name:", ds.get("name"))

print("\nProperties:")
for name, prop in ds.get("properties", {}).items():
    print(f"- {name}: {prop['type']}")
