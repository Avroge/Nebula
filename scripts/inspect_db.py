import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")

notion = Client(auth=NOTION_TOKEN, notion_version=NOTION_VERSION)

db = notion.databases.retrieve(database_id=DATABASE_ID)

print("Type Python:", type(db))
print("Keys:", list(db.keys()))
print("object:", db.get("object"))
print("id:", db.get("id"))
print("title:", "".join([t.get("plain_text","") for t in db.get("title", [])]) if isinstance(db.get("title"), list) else db.get("title"))

# Si c'est une erreur ou pas un database, on affiche tout
if db.get("object") != "database" or "properties" not in db:
    print("\n--- RAW RESPONSE ---")
    print(db)
    raise SystemExit("\nCe n'est pas un objet 'database' (ou pas la bonne ID).")

print("\nProperties:")
for name, prop in db["properties"].items():
    print(f"- {name}: {prop['type']}")