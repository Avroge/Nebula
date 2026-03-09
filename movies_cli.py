import os
import requests

from datetime import date
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_GENRE_CACHE: dict[int, str] | None = None

def tmdb_genre_map(language: str = "fr-FR") -> dict[int, str]:
    """
    Récupère la liste officielle des genres films TMDB et renvoie {id: name}.
    On met en cache en mémoire pour éviter de re-télécharger à chaque commande.
    """
    global TMDB_GENRE_CACHE
    if TMDB_GENRE_CACHE is not None:
        return TMDB_GENRE_CACHE

    url = "https://api.themoviedb.org/3/genre/movie/list"
    params = {"api_key": TMDB_API_KEY, "language": language}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    TMDB_GENRE_CACHE = {g["id"]: g["name"] for g in data.get("genres", [])}
    return TMDB_GENRE_CACHE

if not NOTION_TOKEN or not DATA_SOURCE_ID:
    raise SystemExit("ERREUR: NOTION_TOKEN ou NOTION_DATA_SOURCE_ID manquant dans .env")

notion = Client(auth=NOTION_TOKEN, notion_version=NOTION_VERSION)

PROP_TITLE = "Titre"
PROP_STATUS = "Statut"
PROP_YEAR = "Année de sortie"
PROP_GENRE = "Genre"
PROP_PLATFORM = "Plateforme"
PROP_RATING = "Note"
PROP_WATCH_DATE = "Date de visionnage"


def find_movie_by_title(title: str) -> str | None:
    body = {
        "filter": {"property": PROP_TITLE, "title": {"equals": title}},
        "page_size": 1,
    }
    res = notion.request(f"data_sources/{DATA_SOURCE_ID}/query", "POST", body=body)
    results = res.get("results", [])
    return results[0]["id"] if results else None


def upsert_movie(title: str, status: str | None = None, year: int | None = None,
                 platform: str | None = None, genres: list[str] | None = None,
                 rating: float | None = None, watched_on: date | None = None) -> str:
    existing_id = find_movie_by_title(title)

    props = {PROP_TITLE: {"title": [{"text": {"content": title}}]}}
    if status is not None:
        props[PROP_STATUS] = {"status": {"name": status}}
    if year is not None:
        props[PROP_YEAR] = {"number": int(year)}
    if platform is not None:
        props[PROP_PLATFORM] = {"select": {"name": platform}}
    if genres:
        props[PROP_GENRE] = {"multi_select": [{"name": g} for g in genres]}
    if rating is not None:
        props[PROP_RATING] = {"number": float(rating)}
    if watched_on is not None:
        props[PROP_WATCH_DATE] = {"date": {"start": watched_on.isoformat()}}

    if existing_id:
        notion.pages.update(page_id=existing_id, properties=props)
        return existing_id

    page = notion.pages.create(parent={"data_source_id": DATA_SOURCE_ID}, properties=props)
    return page["id"]


def set_status(title: str, status: str, set_watch_date: bool = False) -> str:
    page_id = find_movie_by_title(title)
    if not page_id:
        raise SystemExit(f"Introuvable: '{title}'")

    props = {PROP_STATUS: {"status": {"name": status}}}
    if set_watch_date:
        props[PROP_WATCH_DATE] = {"date": {"start": date.today().isoformat()}}

    notion.pages.update(page_id=page_id, properties=props)
    return page_id


def list_movies(status: str | None = None, limit: int = 20):
    body = {"page_size": limit}
    if status:
        body["filter"] = {"property": PROP_STATUS, "status": {"equals": status}}

    res = notion.request(f"data_sources/{DATA_SOURCE_ID}/query", "POST", body=body)
    for page in res.get("results", []):
        props = page.get("properties", {})
        title_arr = props.get(PROP_TITLE, {}).get("title", [])
        title = title_arr[0].get("plain_text") if title_arr else "(sans titre)"
        st = props.get(PROP_STATUS, {}).get("status", {})
        st_name = st.get("name") if st else "(sans statut)"
        print(f"- {title} [{st_name}]")

def fetch_tmdb_movie(title: str, language: str = "fr-FR"):
    if not TMDB_API_KEY:
        raise SystemExit("TMDB_API_KEY manquant dans .env")

    url = "https://api.themoviedb.org/3/search/movie"
    params = {
        "api_key": TMDB_API_KEY,
        "query": title,
        "language": language,
    }

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    if not data.get("results"):
        raise SystemExit("Film introuvable sur TMDB")

    movie = data["results"][0]

    year = None
    if movie.get("release_date"):
        year = int(movie["release_date"][:4])

    genre_ids = movie.get("genre_ids", []) or []
    gmap = tmdb_genre_map(language=language)
    genres = [gmap[g] for g in genre_ids if g in gmap]

    return {
        "id": movie["id"],
        "title": movie["title"],
        "year": year,
        "rating": movie["vote_average"],
        "genres": genres,   # si tu l’as déjà
    }

def parse_args(argv: list[str]):
    if not argv:
        raise SystemExit(
            "Commandes:\n"
            "  add \"Titre\" [\"Statut\"] [--year 2022] [--platform Netflix] [--genres \"SF,Apocalyptique\"] [--rating 7.5]\n"
            "  seen \"Titre\"      (met Statut=Vu + Date de visionnage=aujourd’hui)\n"
            "  rewatch \"Titre\"   (met Statut=À revoir)\n"
            "  list [--status \"À voir\"] [--limit 20]\n"
        )

    cmd = argv[0].lower()
    title = argv[1] if len(argv) > 1 else None
    if not title or title.startswith("--"):
        title = None

    opts = {}
    i = 2

    # ✅ Si le 3e argument existe et ne commence pas par "--", on l'interprète comme statut
    if cmd == "add" and len(argv) > 2 and not argv[2].startswith("--"):
        opts["status"] = argv[2]
        i = 3

    while i < len(argv):
        if argv[i] == "--year":
            opts["year"] = int(argv[i + 1]); i += 2
        elif argv[i] == "--platform":
            opts["platform"] = argv[i + 1]; i += 2
        elif argv[i] == "--genres":
            opts["genres"] = [g.strip() for g in argv[i + 1].split(",") if g.strip()]; i += 2
        elif argv[i] == "--rating":
            opts["rating"] = float(argv[i + 1]); i += 2
        elif argv[i] == "--status":
            opts["status"] = argv[i + 1]; i += 2
        elif argv[i] == "--limit":
            opts["limit"] = int(argv[i + 1]); i += 2
        else:
            raise SystemExit(f"Option inconnue: {argv[i]}")
    return cmd, title, opts

# --- TMDB: watch providers (plateformes) ---

PROVIDER_NAME_MAP_FR = {
    "Amazon Prime Video": "Prime Video",
    "Disney Plus": "Disney+",
    "Apple TV Plus": "Apple TV+",
    "Google Play Movies": "Google Play (location/achat)",
    "YouTube": "YouTube (location/achat)",
    "HBO Max": "Max",
}

def pick_platform_from_tmdb_providers(providers_fr: dict) -> str | None:
    """
    Choisit une plateforme 'meilleure' à partir de la réponse FR.
    Priorité: flatrate (abonnement) > ads (gratuit pub) > rent > buy.
    """
    if not providers_fr:
        return None

    for bucket in ("flatrate", "ads", "rent", "buy"):
        lst = providers_fr.get(bucket) or []
        if lst:
            raw = lst[0].get("provider_name")
            if not raw:
                continue
            return PROVIDER_NAME_MAP_FR.get(raw, raw)

    return None


def fetch_tmdb_watch_platform(movie_id: int, region: str = "FR") -> str | None:
    """
    Appelle GET /3/movie/{movie_id}/watch/providers et renvoie une plateforme (ou None).
    """
    if not TMDB_API_KEY:
        raise SystemExit("TMDB_API_KEY manquant dans .env")

    url = f"https://api.themoviedb.org/3/movie/{movie_id}/watch/providers"
    params = {"api_key": TMDB_API_KEY}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    providers_fr = (data.get("results") or {}).get(region)
    return pick_platform_from_tmdb_providers(providers_fr)

if __name__ == "__main__":
    import sys
    cmd, title, opts = parse_args(sys.argv[1:])

    if cmd == "add":
        if not title:
            raise SystemExit("Usage: add \"Titre\" ...")
        page_id = upsert_movie(title=title, **opts)
        print("OK page_id =", page_id)

    elif cmd == "seen":
        if not title:
            raise SystemExit("Usage: seen \"Titre\"")
        page_id = set_status(title, "Vu", set_watch_date=True)
        print("OK page_id =", page_id)

    elif cmd == "rewatch":
        if not title:
            raise SystemExit("Usage: rewatch \"Titre\"")
        page_id = set_status(title, "À revoir", set_watch_date=False)
        print("OK page_id =", page_id)

    elif cmd == "list":
        list_movies(status=opts.get("status"), limit=opts.get("limit", 20))
    
    elif cmd == "auto":

        if not title:
            raise SystemExit('Usage: auto "Titre du film"')

        movie = fetch_tmdb_movie(title)

        platform = fetch_tmdb_watch_platform(movie["id"], region="FR")

        page_id = upsert_movie(
            title=movie["title"],
            year=movie["year"],
            rating=movie["rating"],
            genres=movie["genres"],   # ✅ Ajout
            platform=platform,            # ✅ AJOUT
            status="À voir",
        )

        print(f"✔ Film synchronisé : {movie['title']}")
        print("Plateforme détectée :", platform or "(inconnue)")

    else:
        raise SystemExit(f"Commande inconnue: {cmd}")
