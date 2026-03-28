import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv
from notion_client import Client


def _env_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name(".env")
    return Path(__file__).with_name(".env")


load_dotenv(_env_path())

# Notion
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")

# TMDB
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

if not NOTION_TOKEN or not DATA_SOURCE_ID:
    raise RuntimeError("NOTION_TOKEN ou NOTION_DATA_SOURCE_ID manquant dans .env")

notion = Client(auth=NOTION_TOKEN, notion_version=NOTION_VERSION)

# Propriétés Notion
PROP_TITLE = "Titre"
PROP_STATUS = "Statut"
PROP_YEAR = "Année de sortie"
PROP_GENRE = "Genre"
PROP_PLATFORM = "Plateforme"
PROP_RATING = "Note"
PROP_WATCH_DATE = "Date de visionnage"
PROP_POSTER = "Poster"

# Mappage noms plateformes TMDB -> noms Notion
PROVIDER_NAME_MAP_FR = {
    "Amazon Prime Video": "Prime Video",
    "Disney Plus": "Disney+",
    "Apple TV Plus": "Apple TV+",
    "Google Play Movies": "Google Play (location/achat)",
    "YouTube": "YouTube (location/achat)",
    "HBO Max": "Max",
}

_TMDB_GENRE_CACHE = None


def normalize_title(title: str) -> str:
    s = unicodedata.normalize("NFKD", title)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def _norm_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def tmdb_poster_url(poster_path: str | None, size: str = "w92") -> str | None:
    if not poster_path:
        return None
    return f"https://image.tmdb.org/t/p/{size}{poster_path}"


def tmdb_genre_map(language: str = "fr-FR") -> dict[int, str]:
    global _TMDB_GENRE_CACHE

    if _TMDB_GENRE_CACHE is not None:
        return _TMDB_GENRE_CACHE

    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY manquant dans .env")

    url = "https://api.themoviedb.org/3/genre/movie/list"
    params = {"api_key": TMDB_API_KEY, "language": language}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    _TMDB_GENRE_CACHE = {g["id"]: g["name"] for g in data.get("genres", [])}
    return _TMDB_GENRE_CACHE


def fetch_tmdb_movie(title: str, language: str = "fr-FR") -> dict:
    """Recherche un film sur TMDB et retourne ses infos principales."""
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY manquant dans .env")

    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": title, "language": language}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    results = data.get("results") or []
    if not results:
        raise ValueError("Film introuvable sur TMDB")

    movie = results[0]
    year = int(movie["release_date"][:4]) if movie.get("release_date") else None

    gmap = tmdb_genre_map(language=language)
    genres = [gmap[g] for g in (movie.get("genre_ids") or []) if g in gmap]

    return {
        "id": movie["id"],
        "title": movie.get("title") or title,
        "year": year,
        "rating": movie.get("vote_average"),
        "genres": genres,
        "poster_path": movie.get("poster_path"),
        "poster_url": tmdb_poster_url(movie.get("poster_path"), size="w185"),
    }


def tmdb_search_suggestions(
    query: str, language: str = "fr-FR", limit: int = 8
) -> list[dict]:
    """
    Retourne une liste de suggestions :
    [{"id": int, "title": str, "year": int|None, "poster_path": str|None}, ...]
    """
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY manquant dans .env")

    q = (query or "").strip()
    if len(q) < 2:
        return []

    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": q, "language": language}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    out = []
    for m in (data.get("results") or [])[:limit]:
        title = m.get("title") or m.get("original_title") or ""
        if not title:
            continue

        year = int(m["release_date"][:4]) if m.get("release_date") else None

        out.append(
            {
                "id": m["id"],
                "title": title,
                "year": year,
                "poster_path": m.get("poster_path"),
            }
        )

    return out


def _pick_platform_from_tmdb_providers(providers_fr: dict) -> str | None:
    if not providers_fr:
        return None

    for bucket in ("flatrate", "ads", "rent", "buy"):
        lst = providers_fr.get(bucket) or []
        if lst:
            raw = lst[0].get("provider_name")
            if raw:
                return PROVIDER_NAME_MAP_FR.get(raw, raw)

    return None


def fetch_tmdb_watch_platform(movie_id: int, region: str = "FR") -> str | None:
    """Retourne une plateforme TMDB pour une région donnée, ou None."""
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY manquant dans .env")

    url = f"https://api.themoviedb.org/3/movie/{movie_id}/watch/providers"
    params = {"api_key": TMDB_API_KEY}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    providers = (data.get("results") or {}).get(region)
    return _pick_platform_from_tmdb_providers(providers)


def find_movie_by_title(title: str) -> str | None:
    target = normalize_title(title)

    next_cursor = None

    while True:
        body = {
            "page_size": 100,
        }

        if next_cursor:
            body["start_cursor"] = next_cursor

        res = notion.request(f"data_sources/{DATA_SOURCE_ID}/query", "POST", body=body)

        for page in res.get("results", []):
            props = page.get("properties", {})

            title_arr = props.get(PROP_TITLE, {}).get("title", [])
            existing_title = title_arr[0].get("plain_text") if title_arr else ""

            if normalize_title(existing_title) == target:
                return page["id"]

        if not res.get("has_more"):
            break

        next_cursor = res.get("next_cursor")
        if not next_cursor:
            break

    return None


def upsert_movie(
    *,
    title: str,
    status: str = "À voir",
    year=None,
    platform=None,
    genres=None,
    rating=None,
    watched_on=None,
    poster_url=None,
) -> str:
    page_id = find_movie_by_title(title)

    props = {
        PROP_TITLE: {"title": [{"text": {"content": title}}]},
    }

    if not page_id:
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

    if poster_url:
        props[PROP_POSTER] = {
            "files": [
                {
                    "name": f"{title} - poster",
                    "type": "external",
                    "external": {"url": poster_url},
                }
            ]
        }

    if page_id:
        notion.pages.update(page_id=page_id, properties=props)
        return page_id

    page = notion.pages.create(
        parent={"data_source_id": DATA_SOURCE_ID},
        properties=props,
    )
    return page["id"]


def mark_seen(title: str) -> str:
    page_id = find_movie_by_title(title)
    if not page_id:
        raise ValueError("Film introuvable dans Notion")

    props = {
        PROP_STATUS: {"status": {"name": "Vu"}},
        PROP_WATCH_DATE: {"date": {"start": date.today().isoformat()}},
    }

    notion.pages.update(page_id=page_id, properties=props)
    return page_id


def list_movies(status: str | None = None, limit: int = 50) -> list[tuple[str, str]]:
    body = {"page_size": limit}

    if status:
        body["filter"] = {"property": PROP_STATUS, "status": {"equals": status}}

    res = notion.request(f"data_sources/{DATA_SOURCE_ID}/query", "POST", body=body)

    out = []
    for page in res.get("results", []):
        props = page.get("properties", {})

        title_arr = props.get(PROP_TITLE, {}).get("title", [])
        title = title_arr[0].get("plain_text") if title_arr else "(sans titre)"

        status_obj = props.get(PROP_STATUS, {}).get("status", {})
        movie_status = status_obj.get("name") if status_obj else "(sans statut)"

        out.append((title, movie_status))

    return out


def list_movies_detailed(
    status: str | None = None, limit: int | None = None
) -> list[dict]:
    out = []
    next_cursor = None

    while True:
        body = {
            "page_size": 100,
        }

        if status:
            body["filter"] = {"property": PROP_STATUS, "status": {"equals": status}}

        if next_cursor:
            body["start_cursor"] = next_cursor

        res = notion.request(f"data_sources/{DATA_SOURCE_ID}/query", "POST", body=body)

        for page in res.get("results", []):
            props = page.get("properties", {})

            title_arr = props.get(PROP_TITLE, {}).get("title", [])
            title = title_arr[0].get("plain_text") if title_arr else "(sans titre)"

            status_obj = props.get(PROP_STATUS, {}).get("status", {})
            movie_status = status_obj.get("name") if status_obj else ""

            year = props.get(PROP_YEAR, {}).get("number")
            rating = props.get(PROP_RATING, {}).get("number")
            poster_files = props.get(PROP_POSTER, {}).get("files", [])
            poster_url = None

            if poster_files:
                first_file = poster_files[0]
                if first_file.get("type") == "external":
                    poster_url = first_file.get("external", {}).get("url")
                elif first_file.get("type") == "file":
                    poster_url = first_file.get("file", {}).get("url")

            platform_obj = props.get(PROP_PLATFORM, {}).get("select")
            platform = platform_obj.get("name") if platform_obj else ""

            genre_arr = props.get(PROP_GENRE, {}).get("multi_select", [])
            genres = [g.get("name") for g in genre_arr if g.get("name")]

            out.append(
                {
                    "id": page["id"],
                    "title": title,
                    "status": movie_status,
                    "year": year,
                    "rating": rating,
                    "platform": platform,
                    "genres": genres,
                    "poster_url": poster_url,
                }
            )

            if limit is not None and len(out) >= limit:
                return out[:limit]

        if not res.get("has_more"):
            break

        next_cursor = res.get("next_cursor")
        if not next_cursor:
            break

    return out


def auto_add(title: str) -> dict:
    """Recherche TMDB puis ajoute le film dans Notion."""
    movie = fetch_tmdb_movie(title)
    platform = fetch_tmdb_watch_platform(movie["id"], region="FR")

    page_id = upsert_movie(
        title=movie["title"],
        year=movie["year"],
        rating=movie["rating"],
        genres=movie["genres"],
        platform=platform,
        status="À voir",
        poster_url=movie["poster_url"],
    )

    return {
        "title": movie["title"],
        "platform": platform,
        "page_id": page_id,
    }


def auto_add_by_tmdb_id(movie_id: int, language: str = "fr-FR") -> dict:
    """
    Ajoute un film en utilisant un ID TMDB.
    """
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY manquant dans .env")

    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {"api_key": TMDB_API_KEY, "language": language}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    m = r.json()

    title = m.get("title") or m.get("original_title")
    year = int(m["release_date"][:4]) if m.get("release_date") else None
    rating = m.get("vote_average")
    genres = [g["name"] for g in (m.get("genres") or []) if g.get("name")]
    poster_url = tmdb_poster_url(m.get("poster_path"), size="w185")

    platform = fetch_tmdb_watch_platform(movie_id, region="FR")

    page_id = upsert_movie(
        title=title,
        year=year,
        rating=rating,
        genres=genres,
        platform=platform,
        status="À voir",
        poster_url=poster_url,
    )

    return {
        "title": title,
        "platform": platform,
        "page_id": page_id,
    }


def update_status(title: str, new_status: str) -> str:
    page_id = find_movie_by_title(title)
    if not page_id:
        raise ValueError("Film introuvable dans Notion")

    props = {
        PROP_STATUS: {"status": {"name": new_status}},
    }

    if new_status == "Vu":
        props[PROP_WATCH_DATE] = {"date": {"start": date.today().isoformat()}}

    notion.pages.update(page_id=page_id, properties=props)
    return page_id


def delete_movie(title: str) -> str:
    page_id = find_movie_by_title(title)
    if not page_id:
        raise ValueError("Film introuvable dans Notion")

    notion.pages.update(page_id=page_id, archived=True)
    return page_id


def tmdb_movie_details(movie_id: int, language: str = "fr-FR") -> dict:
    if not TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY manquant dans .env")

    url = f"https://api.themoviedb.org/3/movie/{movie_id}"

    params = {
        "api_key": TMDB_API_KEY,
        "language": language,
    }

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    return {
        "title": data.get("title"),
        "year": data.get("release_date", "")[:4],
        "rating": data.get("vote_average"),
        "overview": data.get("overview"),
    }
