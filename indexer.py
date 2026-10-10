#!/usr/bin/env python3
"""
indexer.py — Sincronização de Metadados TMDB e Vinculação no Supabase
Runtime: Python 3.10+
Dependências: requests, supabase
"""

import os
import sys
import argparse
import requests
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
TMDB_TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN")

def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY devem estar definidos.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_tmdb_headers() -> dict:
    if not TMDB_TOKEN:
        raise ValueError("TMDB_READ_ACCESS_TOKEN deve estar definido.")
    return {
        "Authorization": f"Bearer {TMDB_TOKEN}",
        "accept": "application/json"
    }

def search_anime_tmdb(query: str) -> list:
    """Pesquisa série de anime no TMDB por nome."""
    url = "https://api.themoviedb.org/3/search/tv"
    params = {"query": query, "language": "pt-BR", "include_adult": "false"}
    res = requests.get(url, headers=get_tmdb_headers(), params=params)
    res.raise_for_status()
    return res.json().get("results", [])

def sync_anime(tmdb_id: int) -> str:
    """Busca dados da série, temporadas e episódios no TMDB e sincroniza no Supabase."""
    supabase = get_supabase()
    headers = get_tmdb_headers()

    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?language=pt-BR"
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    data = res.json()

    anime_payload = {
        "tmdb_id": data["id"],
        "title": data.get("name"),
        "original_title": data.get("original_name"),
        "overview": data.get("overview"),
        "poster_path": data.get("poster_path"),
        "backdrop_path": data.get("backdrop_path"),
        "first_air_date": data.get("first_air_date") or None,
        "status": data.get("status"),
        "genres": data.get("genres", [])
    }

    # Upsert anime
    db_anime = supabase.table("animes").upsert(anime_payload, on_conflict="tmdb_id").execute()
    if not db_anime.data:
        raise RuntimeError(f"Falha ao persistir anime {tmdb_id} no Supabase.")
    anime_id = db_anime.data[0]["id"]
    print(f"[+] Anime persistido: {anime_payload['title']} [UUID: {anime_id}]")

    # Sincroniza temporadas e episódios
    for s in data.get("seasons", []):
        s_num = s["season_number"]
        if s_num == 0:
            continue  # Pular especiais por padrão

        s_payload = {
            "anime_id": anime_id,
            "tmdb_id": s.get("id"),
            "season_number": s_num,
            "name": s.get("name"),
            "overview": s.get("overview"),
            "poster_path": s.get("poster_path"),
            "episode_count": s.get("episode_count", 0)
        }
        db_s = supabase.table("seasons").upsert(s_payload, on_conflict="anime_id, season_number").execute()
        season_id = db_s.data[0]["id"]

        ep_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{s_num}?language=pt-BR"
        ep_res = requests.get(ep_url, headers=headers)
        if ep_res.status_code == 200:
            ep_data = ep_res.json()
            for ep in ep_data.get("episodes", []):
                ep_payload = {
                    "season_id": season_id,
                    "episode_number": ep["episode_number"],
                    "name": ep.get("name"),
                    "overview": ep.get("overview"),
                    "still_path": ep.get("still_path"),
                    "tmdb_id": ep.get("id"),
                    "air_date": ep.get("air_date") or None
                }
                supabase.table("episodes").upsert(ep_payload, on_conflict="season_id, episode_number").execute()
            print(f"  [+] Temporada {s_num}: {len(ep_data.get('episodes', []))} episódios indexados.")

    return anime_id

def link_stream_source(tmdb_id: int, season_num: int, episode_num: int, gdrive_file_id: str, file_name: str, file_size: int = 0):
    """Vincula o arquivo do Google Drive ao episódio correspondente."""
    supabase = get_supabase()
    
    # Localiza o ID interno do episódio
    anime = supabase.table("animes").select("id").eq("tmdb_id", tmdb_id).single().execute()
    season = supabase.table("seasons").select("id").eq("anime_id", anime.data["id"]).eq("season_number", season_num).single().execute()
    episode = supabase.table("episodes").select("id").eq("season_id", season.data["id"]).eq("episode_number", episode_num).single().execute()

    source_payload = {
        "episode_id": episode.data["id"],
        "storage_provider": "gdrive",
        "gdrive_file_id": gdrive_file_id,
        "file_name": file_name,
        "file_size": file_size,
        "mime_type": "video/mp4",
        "resolution": "1080p"
    }

    res = supabase.table("media_sources").insert(source_payload).execute()
    print(f"[+] Mídia associada: Episódio {episode_num} -> GDrive ID {gdrive_file_id}")
    return res.data

def main():
    parser = argparse.ArgumentParser(description="Indexer TMDB e Supabase")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Comando: sync
    sync_p = subparsers.add_parser("sync", help="Sincroniza um anime pelo TMDB ID")
    sync_p.add_argument("--tmdb-id", type=int, required=True, help="ID do TMDB")

    # Comando: search
    search_p = subparsers.add_parser("search", help="Busca animes pelo nome")
    search_p.add_argument("--query", type=str, required=True, help="Termo de busca")

    # Comando: link
    link_p = subparsers.add_parser("link", help="Vincula stream ao episódio")
    link_p.add_argument("--tmdb-id", type=int, required=True)
    link_p.add_argument("--season", type=int, required=True)
    link_p.add_argument("--episode", type=int, required=True)
    link_p.add_argument("--gdrive-id", type=str, required=True)
    link_p.add_argument("--filename", type=str, required=True)
    link_p.add_argument("--filesize", type=int, default=0)

    args = parser.parse_args()

    if args.command == "sync":
        sync_anime(args.tmdb_id)
    elif args.command == "search":
        results = search_anime_tmdb(args.query)
        for r in results:
            print(f"[{r['id']}] {r['name']} ({r.get('first_air_date', 'N/A')})")
    elif args.command == "link":
        link_stream_source(args.tmdb_id, args.season, args.episode, args.gdrive_id, args.filename, args.filesize)

if __name__ == "__main__":
    main()
