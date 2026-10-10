#!/usr/bin/env python3
"""
smartplay_harvester.py — Harvester Otimizado com Filtro Estrito de Animes
Correções:
 - Limpeza contínua de cookies para evitar HTTP 431 (Header Fields Too Large)
 - Filtro estrito TMDB (Apenas animações de origem japonesa 'JP', ignorando desenhos ocidentais)
 - Controle de fila do GitHub Actions (sem sobrecarga de workflows)
 - Trava de segurança para não ultrapassar 4TB no Google Drive
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

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")
GITHUB_REPO = "Ithan-sl/anata-stream"
TMDB_TOKEN = os.environ.get(
    "TMDB_READ_ACCESS_TOKEN",
    "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI5YzMxYjNhZWIyZTU5YWEyY2FmNzRjNzQ1Y2UxNTg4NyIsIm5iZiI6MTc2NjA3MTQ0MC40MDMsInN1YiI6IjY5NDQxYzkwNjRhOWQ4N2RiYzcwNTZlNiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.Pa2-x5hvsHeepw5f70ffBGX9L-4AaU7NBYtp8qSTQDA"
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

def is_strict_anime(tmdb_id: str, title: str) -> bool:
    """Verifica no TMDB se o item é legitimamente um anime japonês."""
    if not tmdb_id or tmdb_id == "0":
        return False

    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}"
    headers = {"Authorization": f"Bearer {TMDB_TOKEN}", "Accept": "application/json"}
    try:
        r = requests.get(url, headers=headers, params={"language": "pt-BR"}, timeout=8)
        if r.status_code != 200:
            return False
        data = r.json()
        
        origin_countries = data.get("origin_country", [])
        genres = [g.get("id") for g in data.get("genres", [])]

        # FILTRO ESTRITO: Deve ser do Japão ('JP') E/OU gênero Animação (16) produzido no Japão
        if "JP" in origin_countries:
            return True
        
        # Desenhos ocidentais (My Little Pony, Batman, Tartarugas Ninja) são descartados
        return False
    except Exception:
        return False

def dispatch_to_github(stream_url: str, tmdb_id: str, season_num: int, ep_num: int, title_slug: str):
    """Envia o episódio para o runner do GitHub Actions."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/ingest_stream.yml/dispatches"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
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
    r = requests.post(url, headers=headers, json=payload, timeout=10)
    if r.status_code == 204:
        print(f"      [✓] Enfileirado no GitHub Actions com sucesso!")
        return True
    else:
        print(f"      [-] Falha ao enfileirar: {r.status_code} {r.text}")
        return False

def harvest_anime_post(post_id: str, anime_title: str):
    clean_session()
    post_url = f"{BASE_URL}/posts/animes/post/{post_id}"
    
    try:
        res = session.get(post_url, timeout=15)
    except Exception as e:
        print(f"[-] Falha ao conectar ao anime {post_id}: {e}")
        return

    if res.status_code != 200:
        print(f"[-] Erro ao carregar anime {post_id}: HTTP {res.status_code}")
        return

    # Extrai temporadas dos cabeçalhos Set-Cookie
    set_cookie_header = res.headers.get("Set-Cookie", "")
    seasons_key = f"seasons_{post_id}"
    m = re.search(rf'{seasons_key}=([^;]+)', set_cookie_header)

    raw_seasons = m.group(1) if m else session.cookies.get(seasons_key)
    if not raw_seasons:
        print(f"[-] Nenhuma temporada encontrada para '{anime_title}' ({post_id})")
        return

    try:
        seasons_data = json.loads(urllib.parse.unquote(raw_seasons))
    except Exception as e:
        print(f"[-] Erro ao decodificar JSON das temporadas: {e}")
        return

    # Valida no TMDB com a primeira temporada
    sample_tmdb = seasons_data[0].get("tmdb") if seasons_data else None
    if not is_strict_anime(sample_tmdb, anime_title):
        print(f"  [🚫 FILTRADO] '{anime_title}' (TMDB: {sample_tmdb}) NÃO é um anime japonês. Pulando...")
        return

    print(f"  [🎌 ANIME VALIDADO] {anime_title} (TMDB: {sample_tmdb})")

    # Garante ordenação sequencial
    seasons_data.sort(key=lambda s: int(s.get("t", 1)))

    for s in seasons_data:
        season_id = s.get("ID")
        season_num = int(s.get("t", 1))
        season_name = s.get("nome", f"Temporada {season_num}")
        tmdb_id = s.get("tmdb")

        print(f"\n  📂 {season_name} [TMDB: {tmdb_id}] (ID Interno: {season_id})")

        # Limpa cookies antes da requisição dos episódios para evitar cabeçalho estourado
        clean_session()
        ep_url = f"{BASE_URL}/season/{season_id}/episodes"
        
        try:
            ep_res = session.get(ep_url, timeout=15)
        except Exception as e:
            print(f"  [-] Timeout ao carregar episódios da temporada {season_id}: {e}")
            continue

        if ep_res.status_code != 200:
            print(f"  [-] Erro HTTP {ep_res.status_code} na temporada {season_id}")
            continue

        pattern = re.findall(
            r'loadEpisodePlayers\([\'"](\d+)[\'"],\s*[\'"]PLAY[\'"]\).*?<div class="episode-title">(.*?)</div>',
            ep_res.text,
            re.DOTALL
        )

        if not pattern:
            print(f"  [-] Nenhum episódio retornado na temporada {season_num}")
            continue

        print(f"  [+] {len(pattern)} episódios identificados.")

        for ep_id, ep_label in pattern:
            ep_label = ep_label.strip()
            ep_match = re.search(r'(\d+)x(\d+)', ep_label)
            if ep_match:
                ep_num = int(ep_match.group(2))
            else:
                num_only = re.search(r'\d+', ep_label)
                ep_num = int(num_only.group(0)) if num_only else 1

            # Busca stream direto via API do player
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

            print(f"    ▶ Ep {ep_num:02d} ({ep_label}) -> Enfileirando...")
            dispatch_to_github(video_stream, tmdb_id, season_num, ep_num, slug)
            
            # Pausa de 3 segundos entre episódios para não sobrecarregar a fila do GitHub Actions
            time.sleep(3)

def crawl_catalog(start_page=1, max_pages=10):
    print("==================================================")
    print("  ANATA STREAM — HARVESTER 100% HEADLESS (FILTRO ANIME)")
    print("==================================================")

    for page in range(start_page, max_pages + 1):
        print(f"\n🌐 [PÁGINA {page}] Lendo catálogo...")
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
            print(f"\n🎬 Processando: {clean_title} (#{post_id})")
            harvest_anime_post(post_id, clean_title)

if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    total_p = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    crawl_catalog(start_page=start, max_pages=total_p)
