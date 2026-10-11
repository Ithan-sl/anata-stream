#!/usr/bin/env python3
"""
smartplay_harvester.py — Harvester com Filtro Estrito de Animação (Séries & Filmes)
Regras de Filtragem no TheMovieDB:
 - PERMITIDO: Qualquer Anime Japonês (Séries e Filmes de Anime)
 - PERMITIDO: Animações como Rick and Morty, Arcane, Castlevania, Invincible (Gênero 16: Animação)
 - ESTRITAMENTE BLOQUEADO: Filmes normais com atores reais (Live-Action)
 - ESTRITAMENTE BLOQUEADO: Séries normais com atores reais (Live-Action)
"""

import os
import sys
import time
import re
import urllib.parse
import json
import requests

BASE_URL = "https://smartplayliteapk.net"
USER_AGENT = "Mozilla/5.0 (Linux; Android 10; NEN-LX1 Build/HUAWEINEN-LX1; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/83.0.4103.106 Mobile Safari/537.36"
PACKAGE_NAME = "com.visionvibes2v2.trailer"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT") or "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"
GITHUB_REPO = "Ithan-sl/anata-stream"
TMDB_TOKEN = os.environ.get(
    "TMDB_READ_ACCESS_TOKEN",
    "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI5YzMxYjNhZWIyZTU5YWEyY2FmNzRjNzQ1Y2UxNTg4NyIsIm5iZiI6MTc2NjA3MTQ0MC40MDMsInN1YiI6IjY5NDQxYzkwNjRhOWQ4N2RiYzcwNTZlNiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.Pa2-x5hvsHeepw5f70ffBGX9L-4AaU7NBYtp8qSTQDA"
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://vazcfgkdbqnurankimcd.supabase.co")
SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZhemNmZ2tkYnFudXJhbmtpbWNkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MTY1Nzg5NiwiZXhwIjoyMTA3MjMzODk2fQ.IenjvA6Pj1ZcXOIFBrNQ5PlxoP42vHGcZ3nzRAy1Wjo"
)

session = requests.Session()
BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "X-Requested-With": PACKAGE_NAME,
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"
}

def clean_session():
    """Limpa cookies acumulados para impedir o erro HTTP 431."""
    session.cookies.clear()
    session.headers.clear()
    session.headers.update(BASE_HEADERS)

def get_existing_episodes_set(tmdb_id: str) -> set:
    """Retorna episódios que já possuem mídia no Google Drive/Supabase."""
    if not tmdb_id or tmdb_id == "0":
        return set()

    url = f"{SUPABASE_URL}/rest/v1/animes?tmdb_id=eq.{tmdb_id}&select=seasons(season_number,episodes(episode_number,media_sources(id,gdrive_file_id)))"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200:
            return set()
        data = r.json()
        if not data or not data[0].get("seasons"):
            return set()

        existing = set()
        for s in data[0]["seasons"]:
            s_num = s.get("season_number")
            for ep in s.get("episodes", []):
                e_num = ep.get("episode_number")
                sources = ep.get("media_sources", [])
                if sources and len(sources) > 0:
                    existing.add((s_num, e_num))
        return existing
    except Exception:
        return set()

def is_allowed_animation(tmdb_id: str, title: str) -> tuple[bool, str]:
    """
    Verifica se o item é uma ANIMAÇÃO (Anime ou Animação Ocidental como Rick and Morty).
    Retorna (permitido: bool, tipo: 'tv' | 'movie' | 'none')
    """
    headers = {"Authorization": f"Bearer {TMDB_TOKEN}", "Accept": "application/json"}

    # 1. Tenta validar como Série/Anime no endpoint /tv/
    if tmdb_id and tmdb_id != "0":
        try:
            r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}", headers=headers, params={"language": "pt-BR"}, timeout=8)
            if r.status_code == 200:
                data = r.json()
                genre_ids = [g.get("id") for g in data.get("genres", [])]
                # 16 = Gênero Animação no TMDB
                if 16 in genre_ids:
                    return True, "tv"
        except Exception:
            pass

        # 2. Tenta validar como Filme de Animação no endpoint /movie/
        try:
            r = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}", headers=headers, params={"language": "pt-BR"}, timeout=8)
            if r.status_code == 200:
                data = r.json()
                genre_ids = [g.get("id") for g in data.get("genres", [])]
                if 16 in genre_ids:
                    return True, "movie"
        except Exception:
            pass

    # 3. Busca pelo título no TMDB (caso o ID original seja divergente)
    clean_search = re.sub(r'[\(\)\[\]\-]+', ' ', title).strip()
    try:
        r = requests.get("https://api.themoviedb.org/3/search/multi", headers=headers, params={"query": clean_search, "language": "pt-BR"}, timeout=8)
        if r.status_code == 200:
            results = r.json().get("results", [])
            for res in results:
                m_type = res.get("media_type") # 'tv' ou 'movie'
                g_ids = res.get("genre_ids", [])
                if 16 in g_ids:
                    return True, m_type
    except Exception:
        pass

    # Se não contém o gênero 16 (Animação), é filme ou série live-action com atores reais -> BLOQUEADO!
    return False, "none"

def dispatch_to_github(stream_url: str, tmdb_id: str, season_num: int, ep_num: int, title_slug: str):
    """Envia o episódio para o runner do GitHub Actions com retentativa."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT") or "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"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/ingest_stream.yml/dispatches"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "ref": "main",
        "inputs": {
            "stream_url": stream_url,
            "tmdb_id": str(tmdb_id),
            "season_number": str(season_num),
            "episode_number": str(ep_num),
            "title_slug": title_slug
        }
    }
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=12)
            if r.status_code == 204:
                print(f"      [✓] Enfileirado no GitHub Actions com sucesso!")
                return True
            elif r.status_code == 403 and "rate limit" in r.text.lower():
                print(f"      [!] Rate limit atingido. Aguardando 10 segundos...")
                time.sleep(10)
            else:
                print(f"      [-] Resposta da API (Tentativa {attempt+1}): {r.status_code} {r.text}")
                time.sleep(3)
        except Exception:
            time.sleep(2)
    return False

def harvest_movie(movie_id: str, title: str, tmdb_id: str):
    """Processa e enfileira um filme de anime ou filme de animação."""
    existing = get_existing_episodes_set(tmdb_id)
    if (1, 1) in existing:
        print(f"  [✓ Já no Drive] Filme '{title}' já armazenado no Google Drive. Pulando...")
        return

    player_url = f"{BASE_URL}/player/movie"
    player_payload = {"movie_id": str(movie_id), "action_type": "PLAY"}
    clean_session()
    
    try:
        p_res = session.post(player_url, json=player_payload, timeout=15)
        p_data = p_res.json()
    except Exception as e:
        print(f"  [-] Erro ao carregar player do filme: {e}")
        return

    if not p_data.get("success") or not p_data.get("players"):
        print(f"  [-] Nenhum stream disponível para o filme '{title}'")
        return

    video_stream = p_data["players"][0].get("file")
    clean_slug = re.sub(r'[^a-zA-Z0-9]+', '-', title).strip('-').lower()
    slug = f"{clean_slug}-filme"

    print(f"  ▶ Enfileirando Filme de Animação: {title} (TMDB {tmdb_id})...")
    dispatch_to_github(video_stream, tmdb_id, 1, 1, slug)
    time.sleep(3)

def harvest_anime_post(post_id: str, anime_title: str):
    clean_session()
    post_url = f"{BASE_URL}/posts/animes/post/{post_id}"
    
    try:
        res = session.get(post_url, timeout=15)
    except Exception as e:
        print(f"[-] Falha ao conectar ao título #{post_id}: {e}")
        return

    if res.status_code != 200:
        # Tenta rota de filme se não for post de anime
        post_url = f"{BASE_URL}/posts/filmes/post/{post_id}"
        res = session.get(post_url, timeout=15)
        if res.status_code != 200:
            print(f"[-] Erro ao carregar #{post_id}: HTTP {res.status_code}")
            return

    # Extrai temporadas dos cookies (se for série/anime)
    set_cookie_header = res.headers.get("Set-Cookie", "")
    seasons_key = f"seasons_{post_id}"
    m = re.search(rf'{seasons_key}=([^;]+)', set_cookie_header)
    raw_seasons = m.group(1) if m else session.cookies.get(seasons_key)

    sample_tmdb = None
    if raw_seasons:
        try:
            seasons_data = json.loads(urllib.parse.unquote(raw_seasons))
            if seasons_data:
                sample_tmdb = seasons_data[0].get("tmdb")
        except Exception:
            pass

    # FILTRO: Valida se é Animação (Anime japonês ou animação como Rick and Morty)
    is_anim, media_kind = is_allowed_animation(sample_tmdb, anime_title)
    if not is_anim:
        print(f"  [🚫 BLOQUEADO] '{anime_title}' NÃO é animação (Filme/Série live-action normal detectado). Pulando...")
        return

    print(f"  [🎨 ANIMAÇÃO VALIDADA] {anime_title} (TMDB: {sample_tmdb or 'Auto'})")

    # CASO 1: É um Filme de Animação
    movie_match = re.search(r"loadMoviePlayers\(['\"](\d+)['\"],\s*['\"]PLAY['\"]\)", res.text)
    if movie_match:
        movie_id = movie_match.group(1)
        harvest_movie(movie_id, anime_title, sample_tmdb or post_id)
        return

    # CASO 2: É uma Série de Anime / Animação
    if not raw_seasons:
        print(f"[-] Nenhuma temporada encontrada para '{anime_title}' (#{post_id})")
        return

    existing_eps = get_existing_episodes_set(sample_tmdb)
    if existing_eps:
        print(f"  📊 Status no banco: {len(existing_eps)} episódio(s) já cadastrado(s).")

    seasons_data.sort(key=lambda s: int(s.get("t", 1)))

    for s in seasons_data:
        season_id = s.get("ID")
        season_num = int(s.get("t", 1))
        season_name = s.get("nome", f"Temporada {season_num}")
        tmdb_id = s.get("tmdb") or sample_tmdb

        clean_session()
        ep_url = f"{BASE_URL}/season/{season_id}/episodes"
        
        try:
            ep_res = session.get(ep_url, timeout=15)
        except Exception as e:
            print(f"  [-] Timeout na temporada {season_id}: {e}")
            continue

        if ep_res.status_code != 200:
            continue

        pattern = re.findall(
            r'loadEpisodePlayers\([\'"](\d+)[\'"],\s*[\'"]PLAY[\'"]\).*?<div class="episode-title">(.*?)</div>',
            ep_res.text,
            re.DOTALL
        )

        if not pattern:
            continue

        total_eps = len(pattern)
        season_existing = [e for (s_idx, e) in existing_eps if s_idx == season_num]
        
        if len(season_existing) == total_eps and total_eps > 0:
            print(f"  [✓ COMPLETO] {season_name} ({total_eps}/{total_eps} eps já no Google Drive).")
            continue

        missing_count = total_eps - len(season_existing)
        print(f"\n  📂 {season_name} ({len(season_existing)}/{total_eps} disponíveis | ⚡ Faltam {missing_count} episódios)")

        for ep_id, ep_label in pattern:
            ep_label = ep_label.strip()
            ep_match = re.search(r'(\d+)x(\d+)', ep_label)
            if ep_match:
                ep_num = int(ep_match.group(2))
            else:
                num_only = re.search(r'\d+', ep_label)
                ep_num = int(num_only.group(0)) if num_only else 1

            if (season_num, ep_num) in existing_eps:
                print(f"    [✓ Já no Drive] T{season_num:02d}E{ep_num:02d} - Ignorado.")
                continue

            print(f"    [⚡ LACUNA DETECTADA] T{season_num:02d}E{ep_num:02d} não encontrado no banco. Baixando...")

            player_url = f"{BASE_URL}/player/episode"
            player_payload = {"ep_id": str(ep_id), "action_type": "PLAY"}
            
            clean_session()
            try:
                p_res = session.post(player_url, json=player_payload, timeout=15)
                p_data = p_res.json()
            except Exception:
                continue

            if not p_data.get("success") or not p_data.get("players"):
                continue

            video_stream = p_data["players"][0].get("file")
            clean_anime_slug = re.sub(r'[^a-zA-Z0-9]+', '-', anime_title).strip('-').lower()
            slug = f"{clean_anime_slug}-s{season_num:02d}e{ep_num:02d}"

            print(f"      ▶ Enfileirando T{season_num:02d}E{ep_num:02d} no GitHub Actions...")
            dispatch_to_github(video_stream, tmdb_id, season_num, ep_num, slug)
            
            existing_eps.add((season_num, ep_num))
            time.sleep(3)

def crawl_catalog(start_page=1, max_pages=10):
    print("================================================================")
    print("  ANATA STREAM — HARVESTER DE ANIMAÇÕES & FILMES DE ANIME")
    print("================================================================")

    for page in range(start_page, max_pages + 1):
        print(f"\n🌐 [PÁGINA {page}] Varrendo catálogo...")
        clean_session()
        page_url = f"{BASE_URL}/posts/animes/{page}"
        
        try:
            res = session.get(page_url, timeout=15)
        except Exception as e:
            print(f"[-] Erro na página {page}: {e}")
            break

        if res.status_code != 200:
            print(f"[-] Erro ao carregar página {page}: HTTP {res.status_code}")
            break

        matches = re.findall(
            r'<article class="item tvshows">.*?<a href="/posts/animes/post/(\d+)".*?<h3><a [^>]*>(.*?)</a></h3>',
            res.text,
            re.DOTALL
        )

        if not matches:
            print(f"[-] Nenhum anime encontrado na página {page}.")
            break

        print(f"[+] {len(matches)} títulos encontrados na página {page}.")
        for post_id, title in matches:
            clean_title = (
                title.replace("&acute;", "´")
                .replace("&ccedil;", "ç")
                .replace("&atilde;", "ã")
                .replace("&eacute;", "é")
                .replace("&ocirc;", "ô")
                .strip()
            )
            print(f"\n🎬 Analisando integridade: {clean_title} (#{post_id})")
            harvest_anime_post(post_id, clean_title)

if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    total_p = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    crawl_catalog(start_page=start, max_pages=total_p)
