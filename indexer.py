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

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ:
                    os.environ[k] = v

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
TMDB_TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN")

def get_supabase() -> Client:
    global SUPABASE_URL, SUPABASE_KEY
    if not SUPABASE_URL:
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
    if not SUPABASE_KEY:
        SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY devem estar definidos.")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_tmdb_headers() -> dict:
    global TMDB_TOKEN
    if not TMDB_TOKEN:
        TMDB_TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN")
    if not TMDB_TOKEN:
        raise ValueError("TMDB_READ_ACCESS_TOKEN deve estar definido.")
    return {
        "Authorization": f"Bearer {TMDB_TOKEN}",
        "accept": "application/json"
    }

def search_anime_tmdb(query: str, is_movie: bool = False) -> list:
    """Pesquisa série de anime ou filme no TMDB por nome."""
    ep = "search/movie" if is_movie else "search/tv"
    url = f"https://api.themoviedb.org/3/{ep}"
    params = {"query": query, "language": "pt-BR", "include_adult": "false"}
    res = requests.get(url, headers=get_tmdb_headers(), params=params)
    res.raise_for_status()
    return res.json().get("results", [])

def sync_custom_anime(
    tmdb_id: int,
    title: str,
    original_title: str = None,
    overview: str = "",
    poster_path: str = None,
    backdrop_path: str = None,
    is_movie: bool = False,
    first_air_date: str = None,
    status: str = "Ended"
) -> str:
    """Registra ou atualiza um anime ou filme customizado no Supabase com metadados reais da fonte."""
    supabase = get_supabase()
    anime_payload = {
        "tmdb_id": tmdb_id,
        "title": title,
        "original_title": original_title or title,
        "overview": overview or "",
        "poster_path": poster_path,
        "backdrop_path": backdrop_path or poster_path,
        "first_air_date": first_air_date or None,
        "status": status,
        "genres": []
    }
    db_anime = supabase.table("animes").upsert(anime_payload, on_conflict="tmdb_id").execute()
    if not db_anime.data:
        raise RuntimeError(f"Falha ao persistir anime customizado {tmdb_id} no Supabase.")
    anime_id = db_anime.data[0]["id"]
    print(f"[+] Título customizado persistido: {title} [TMDB: {tmdb_id} | UUID: {anime_id}]")

    # Se for filme, já provisiona a Temporada 1 e Episódio 1 no banco
    if is_movie:
        s_payload = {
            "anime_id": anime_id,
            "tmdb_id": tmdb_id,
            "season_number": 1,
            "name": "Filme",
            "overview": overview or "",
            "poster_path": poster_path,
            "episode_count": 1
        }
        db_s = supabase.table("seasons").upsert(s_payload, on_conflict="anime_id, season_number").execute()
        season_id = db_s.data[0]["id"]

        ep_payload = {
            "season_id": season_id,
            "episode_number": 1,
            "name": title,
            "overview": overview or "",
            "still_path": backdrop_path or poster_path,
            "tmdb_id": tmdb_id,
            "air_date": first_air_date or None
        }
        supabase.table("episodes").upsert(ep_payload, on_conflict="season_id, episode_number").execute()
        print(f"  [+] Filme customizado indexado como T01E01 (Filme Completo).")

    return anime_id

def _sync_movie_payload(supabase: Client, tmdb_id: int, m_data: dict, meta: dict) -> str:
    """Persiste dados oficiais de filme do TMDB com enriquecimento da fonte se faltar algo."""
    title = m_data.get("title") or meta.get("title")
    original_title = m_data.get("original_title") or meta.get("original_title") or title
    overview = m_data.get("overview") or meta.get("overview") or ""
    poster_path = m_data.get("poster_path") or meta.get("poster_path")
    backdrop_path = m_data.get("backdrop_path") or meta.get("backdrop_path")
    release_date = m_data.get("release_date") or meta.get("release_date")

    movie_payload = {
        "tmdb_id": m_data.get("id", tmdb_id),
        "title": title,
        "original_title": original_title,
        "overview": overview,
        "poster_path": poster_path,
        "backdrop_path": backdrop_path or poster_path,
        "first_air_date": release_date or None,
        "status": m_data.get("status", "Ended"),
        "genres": m_data.get("genres", [])
    }
    db_movie = supabase.table("animes").upsert(movie_payload, on_conflict="tmdb_id").execute()
    if not db_movie.data:
        raise RuntimeError(f"Falha ao persistir filme {tmdb_id} no Supabase.")
    anime_id = db_movie.data[0]["id"]
    print(f"[+] Filme persistido no Supabase: {title} [UUID: {anime_id}]")

    # Cria Temporada 1 fictícia para o filme
    s_payload = {
        "anime_id": anime_id,
        "tmdb_id": m_data.get("id", tmdb_id),
        "season_number": 1,
        "name": "Filme",
        "overview": overview,
        "poster_path": poster_path,
        "episode_count": 1
    }
    db_s = supabase.table("seasons").upsert(s_payload, on_conflict="anime_id, season_number").execute()
    season_id = db_s.data[0]["id"]

    # Cria Episódio 1 fictício para o filme
    ep_payload = {
        "season_id": season_id,
        "episode_number": 1,
        "name": title,
        "overview": overview,
        "still_path": backdrop_path or poster_path,
        "tmdb_id": m_data.get("id", tmdb_id),
        "air_date": release_date or None
    }
    supabase.table("episodes").upsert(ep_payload, on_conflict="season_id, episode_number").execute()
    print(f"  [+] Filme indexado no Supabase como T01E01 (Filme Completo).")
    return anime_id

def _sync_tv_payload(supabase: Client, headers: dict, tmdb_id: int, data: dict, meta: dict) -> str:
    """Persiste dados oficiais de série de TV do TMDB com temporadas e episódios."""
    title = data.get("name") or meta.get("title")
    original_title = data.get("original_name") or meta.get("original_title") or title
    overview = data.get("overview") or meta.get("overview") or ""
    poster_path = data.get("poster_path") or meta.get("poster_path")
    backdrop_path = data.get("backdrop_path") or meta.get("backdrop_path")
    first_air_date = data.get("first_air_date") or meta.get("release_date")

    anime_payload = {
        "tmdb_id": data.get("id", tmdb_id),
        "title": title,
        "original_title": original_title,
        "overview": overview,
        "poster_path": poster_path,
        "backdrop_path": backdrop_path or poster_path,
        "first_air_date": first_air_date or None,
        "status": data.get("status", "Ended"),
        "genres": data.get("genres", [])
    }
    db_anime = supabase.table("animes").upsert(anime_payload, on_conflict="tmdb_id").execute()
    if not db_anime.data:
        raise RuntimeError(f"Falha ao persistir anime {tmdb_id} no Supabase.")
    anime_id = db_anime.data[0]["id"]
    print(f"[+] Anime persistido no Supabase: {title} [UUID: {anime_id}]")

    for s in data.get("seasons", []):
        s_num = s["season_number"]
        if s_num == 0:
            continue
        s_payload = {
            "anime_id": anime_id,
            "tmdb_id": s.get("id"),
            "season_number": s_num,
            "name": s.get("name"),
            "overview": s.get("overview") or "",
            "poster_path": s.get("poster_path") or poster_path,
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
                    "overview": ep.get("overview") or "",
                    "still_path": ep.get("still_path"),
                    "tmdb_id": ep.get("id"),
                    "air_date": ep.get("air_date") or None
                }
                supabase.table("episodes").upsert(ep_payload, on_conflict="season_id, episode_number").execute()
            print(f"  [+] Temporada {s_num}: {len(ep_data.get('episodes', []))} episódios indexados.")
    return anime_id

def sync_anime(tmdb_id: int, is_movie: bool = False, custom_meta: dict = None) -> str:
    """Busca dados da série ou filme no TMDB e sincroniza no Supabase."""
    supabase = get_supabase()
    meta = custom_meta or {}

    # Se for um ID sintético, reaproveita ou cria registro customizado com metadados reais
    if tmdb_id >= 900000000:
        existing = supabase.table("animes").select("id").eq("tmdb_id", tmdb_id).execute()
        if existing.data:
            return existing.data[0]["id"]
        return sync_custom_anime(
            tmdb_id,
            title=meta.get("title", f"Anime {tmdb_id}"),
            original_title=meta.get("original_title"),
            overview=meta.get("overview", ""),
            poster_path=meta.get("poster_path"),
            backdrop_path=meta.get("backdrop_path"),
            is_movie=is_movie,
            first_air_date=meta.get("release_date")
        )

    headers = get_tmdb_headers()

    if is_movie:
        # Sincronização direta de FILME no TMDB (evita colisão de IDs com séries)
        m_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?language=pt-BR"
        m_res = requests.get(m_url, headers=headers)
        if m_res.status_code == 200:
            return _sync_movie_payload(supabase, tmdb_id, m_res.json(), meta)
        
        # Fallback para TV se for erro no endpoint de filme
        t_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?language=pt-BR"
        t_res = requests.get(t_url, headers=headers)
        if t_res.status_code == 200:
            return _sync_tv_payload(supabase, headers, tmdb_id, t_res.json(), meta)

        # Se não achou em nenhum, cria com metadados reais da fonte
        return sync_custom_anime(
            tmdb_id,
            title=meta.get("title", f"Filme {tmdb_id}"),
            original_title=meta.get("original_title"),
            overview=meta.get("overview", ""),
            poster_path=meta.get("poster_path"),
            backdrop_path=meta.get("backdrop_path"),
            is_movie=True,
            first_air_date=meta.get("release_date")
        )
    else:
        # Sincronização prioritária de SÉRIE / ANIME no TMDB
        url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?language=pt-BR"
        res = requests.get(url, headers=headers)
        if res.status_code == 200:
            return _sync_tv_payload(supabase, headers, tmdb_id, res.json(), meta)

        # Fallback para Filme de Animação
        m_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?language=pt-BR"
        m_res = requests.get(m_url, headers=headers)
        if m_res.status_code == 200:
            return _sync_movie_payload(supabase, tmdb_id, m_res.json(), meta)

        # Se não achou no TMDB, cria custom com metadados reais da fonte
        return sync_custom_anime(
            tmdb_id,
            title=meta.get("title", f"Anime {tmdb_id}"),
            original_title=meta.get("original_title"),
            overview=meta.get("overview", ""),
            poster_path=meta.get("poster_path"),
            backdrop_path=meta.get("backdrop_path"),
            is_movie=False,
            first_air_date=meta.get("release_date")
        )

def link_stream_source(tmdb_id: int, season_num: int, episode_num: int, gdrive_file_id: str, file_name: str, file_size: int = 0, is_movie: bool = False, custom_meta: dict = None):
    """Vincula o arquivo do Google Drive ao episódio correspondente com tolerância a falhas."""
    supabase = get_supabase()
    
    # 1. Localiza ou cria registro do Anime
    anime_res = supabase.table("animes").select("id").eq("tmdb_id", tmdb_id).execute()
    if not anime_res.data:
        anime_id = sync_anime(tmdb_id, is_movie=is_movie, custom_meta=custom_meta)
    else:
        anime_id = anime_res.data[0]["id"]

    # 2. Localiza ou cria registro da Temporada
    season_res = supabase.table("seasons").select("id").eq("anime_id", anime_id).eq("season_number", season_num).execute()
    if not season_res.data:
        s_payload = {
            "anime_id": anime_id,
            "season_number": season_num,
            "name": "Filme" if is_movie else f"Temporada {season_num}",
            "episode_count": 1 if is_movie else 0
        }
        s_ins = supabase.table("seasons").upsert(s_payload, on_conflict="anime_id, season_number").execute()
        season_id = s_ins.data[0]["id"]
    else:
        season_id = season_res.data[0]["id"]

    # 3. Localiza ou cria registro do Episódio
    ep_res = supabase.table("episodes").select("id").eq("season_id", season_id).eq("episode_number", episode_num).execute()
    if not ep_res.data:
        ep_name = "Filme Completo" if is_movie else f"Episódio {episode_num}"
        if is_movie and custom_meta and custom_meta.get("title"):
            ep_name = custom_meta["title"]
        ep_payload = {
            "season_id": season_id,
            "episode_number": episode_num,
            "name": ep_name
        }
        ep_ins = supabase.table("episodes").upsert(ep_payload, on_conflict="season_id, episode_number").execute()
        episode_id = ep_ins.data[0]["id"]
    else:
        episode_id = ep_res.data[0]["id"]

    source_payload = {
        "episode_id": episode_id,
        "storage_provider": "gdrive",
        "gdrive_file_id": gdrive_file_id,
        "file_name": file_name,
        "file_size": file_size,
        "mime_type": "video/mp4",
        "resolution": "1080p"
    }

    existing = supabase.table("media_sources").select("id").eq("episode_id", episode_id).execute()
    if existing.data:
        res = supabase.table("media_sources").update(source_payload).eq("id", existing.data[0]["id"]).execute()
        print(f"[+] Mídia atualizada (sem duplicata): Episódio {episode_num} -> GDrive ID {gdrive_file_id}")
    else:
        res = supabase.table("media_sources").insert(source_payload).execute()
        print(f"[+] Mídia associada: Episódio {episode_num} -> GDrive ID {gdrive_file_id}")
    return res.data

def main():
    parser = argparse.ArgumentParser(description="Indexer TMDB e Supabase")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Comando: sync
    sync_p = subparsers.add_parser("sync", help="Sincroniza um anime pelo TMDB ID")
    sync_p.add_argument("--tmdb-id", type=int, required=True, help="ID do TMDB")
    sync_p.add_argument("--movie", action="store_true", default=False, help="Indica se é um filme")

    # Comando: search
    search_p = subparsers.add_parser("search", help="Busca animes pelo nome")
    search_p.add_argument("--query", type=str, required=True, help="Termo de busca")
    search_p.add_argument("--movie", action="store_true", default=False, help="Buscar filmes")

    # Comando: link
    link_p = subparsers.add_parser("link", help="Vincula stream ao episódio")
    link_p.add_argument("--tmdb-id", type=int, required=True)
    link_p.add_argument("--season", type=int, required=True)
    link_p.add_argument("--episode", type=int, required=True)
    link_p.add_argument("--gdrive-id", type=str, required=True)
    link_p.add_argument("--filename", type=str, required=True)
    link_p.add_argument("--filesize", type=int, default=0)
    link_p.add_argument("--movie", action="store_true", default=False, help="Indica se é um filme")

    args = parser.parse_args()

    if args.command == "sync":
        sync_anime(args.tmdb_id, is_movie=args.movie)
    elif args.command == "search":
        results = search_anime_tmdb(args.query, is_movie=args.movie)
        for r in results:
            t = r.get("title") or r.get("name")
            d = r.get("release_date") or r.get("first_air_date", "N/A")
            print(f"[{r['id']}] {t} ({d})")
    elif args.command == "link":
        link_stream_source(args.tmdb_id, args.season, args.episode, args.gdrive_id, args.filename, args.filesize, is_movie=args.movie)

if __name__ == "__main__":
    main()
