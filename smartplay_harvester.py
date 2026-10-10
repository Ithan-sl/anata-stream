#!/usr/bin/env python3
"""
smartplay_harvester.py — Harvester 100% Headless via API Direta do Smart Play Lite
Sem navegadores, sem PyQt6, sem erros de GPU/Mesa.
Varre temporadas e episódios de forma estritamente ordenada e enfileira no GitHub Actions.
"""

import os
import sys
import time
import re
import urllib.parse
import json
import requests

# Configurações do App e Headers de Emulação
BASE_URL = "https://smartplayliteapk.net"
USER_AGENT = "Mozilla/5.0 (Linux; Android 10; NEN-LX1 Build/HUAWEINEN-LX1; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/83.0.4103.106 Mobile Safari/537.36"
PACKAGE_NAME = "com.visionvibes2v2.trailer"

# GitHub Repo & Secrets
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")
GITHUB_REPO = "Ithan-sl/anata-stream"

session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "X-Requested-With": PACKAGE_NAME,
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"
})

def dispatch_to_github(stream_url: str, tmdb_id: str, season_num: int, ep_num: int, title_slug: str):
    """Envia o episódio para o runner do GitHub Actions baixar e subir para o Google Drive."""
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
    """Extrai todas as temporadas e episódios de um anime específico."""
    post_url = f"{BASE_URL}/posts/animes/post/{post_id}"
    res = session.get(post_url, timeout=15)
    if res.status_code != 200:
        print(f"[-] Erro ao carregar anime {post_id}: HTTP {res.status_code}")
        return

    # 1. Recupera as temporadas dos cookies de resposta
    seasons_cookie_key = f"seasons_{post_id}"
    raw_seasons = session.cookies.get(seasons_cookie_key)
    
    if not raw_seasons:
        # Tenta extrair direto dos cabeçalhos se não estiver no jar
        set_cookie = res.headers.get("Set-Cookie", "")
        m = re.search(rf'{seasons_cookie_key}=([^;]+)', set_cookie)
        if m:
            raw_seasons = m.group(1)

    if not raw_seasons:
        print(f"[-] Nenhuma temporada identificada para o anime '{anime_title}' ({post_id})")
        return

    try:
        seasons_data = json.loads(urllib.parse.unquote(raw_seasons))
    except Exception as e:
        print(f"[-] Erro ao decodificar temporadas: {e}")
        return

    # Garante ordenação por temporada
    seasons_data.sort(key=lambda s: int(s.get("t", 1)))

    for s in seasons_data:
        season_id = s.get("ID")
        season_num = int(s.get("t", 1))
        season_name = s.get("nome", f"Temporada {season_num}")
        tmdb_id = s.get("tmdb")

        print(f"\n  📂 {season_name} [TMDB: {tmdb_id}] (ID Interno: {season_id})")

        # 2. Carrega a lista de episódios da temporada
        ep_url = f"{BASE_URL}/season/{season_id}/episodes"
        ep_res = session.get(ep_url, timeout=15)
        if ep_res.status_code != 200:
            print(f"  [-] Erro ao carregar episódios da temporada {season_id}")
            continue

        # Regex para extrair episódios: loadEpisodePlayers('284960', 'PLAY') e <div class="episode-title">EP 1x1</div>
        # Encontra blocos de episódio
        pattern = re.findall(
            r'loadEpisodePlayers\([\'"](\d+)[\'"],\s*[\'"]PLAY[\'"]\).*?<div class="episode-title">(.*?)</div>',
            ep_res.text,
            re.DOTALL
        )

        if not pattern:
            print(f"  [-] Nenhum episódio encontrado na página da temporada {season_num}")
            continue

        print(f"  [+] {len(pattern)} episódios identificados. Processando em ordem...")

        for ep_id, ep_label in pattern:
            ep_label = ep_label.strip()
            # Extrai número do episódio a partir de 'EP 1x1' ou 'EP 1'
            ep_match = re.search(r'(\d+)x(\d+)', ep_label)
            if ep_match:
                ep_num = int(ep_match.group(2))
            else:
                num_only = re.search(r'\d+', ep_label)
                ep_num = int(num_only.group(0)) if num_only else 1

            # 3. Faz requisição à API do player para extrair o stream direto (.mp4)
            player_url = f"{BASE_URL}/player/episode"
            player_payload = {"ep_id": str(ep_id), "action_type": "PLAY"}
            try:
                p_res = session.post(player_url, json=player_payload, timeout=15)
                p_data = p_res.json()
            except Exception as e:
                print(f"    [-] Erro na chamada do player do Ep {ep_num}: {e}")
                continue

            if not p_data.get("success") or not p_data.get("players"):
                print(f"    [-] Nenhum stream disponível para o Ep {ep_num}")
                continue

            video_stream = p_data["players"][0].get("file")
            clean_anime_slug = re.sub(r'[^a-zA-Z0-9]+', '-', anime_title).strip('-').lower()
            slug = f"{clean_anime_slug}-s{season_num:02d}e{ep_num:02d}"

            print(f"    ▶ {anime_title} - T{season_num:02d}E{ep_num:02d} ({ep_label})")
            print(f"      Stream: {video_stream[:60]}...")
            
            # Envia para a fila do GitHub Actions
            dispatch_to_github(video_stream, tmdb_id, season_num, ep_num, slug)
            
            # Pequeno intervalo para respeitar o limite de taxa do GitHub
            time.sleep(2)

def crawl_catalog(start_page=1, max_pages=10):
    """Percorre as páginas do catálogo de animes e colhe todos os títulos."""
    print("==================================================")
    print("  ANATA STREAM — RASTREADOR HEADLESS DE ANIMES")
    print("==================================================")

    for page in range(start_page, max_pages + 1):
        print(f"\n🌐 [PÁGINA {page}] Lendo catálogo de animes...")
        page_url = f"{BASE_URL}/posts/animes/{page}"
        res = session.get(page_url, timeout=15)
        if res.status_code != 200:
            print(f"[-] Fim do catálogo ou erro na página {page}")
            break

        # Extrai links de animes: <a href="/posts/animes/post/21540">Nome</a>
        matches = re.findall(
            r'<article class="item tvshows">.*?<a href="/posts/animes/post/(\d+)".*?<h3><a [^>]*>(.*?)</a></h3>',
            res.text,
            re.DOTALL
        )

        if not matches:
            print(f"[-] Nenhum anime encontrado na página {page}.")
            break

        print(f"[+] {len(matches)} animes encontrados na página {page}:")
        for post_id, title in matches:
            clean_title = title.replace("&acute;", "´").replace("&ccedil;", "ç").replace("&atilde;", "ã").strip()
            print(f"\n🎬 Iniciando colheita: {clean_title} (Post #{post_id})")
            harvest_anime_post(post_id, clean_title)

if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    total_p = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    crawl_catalog(start_page=start, max_pages=total_p)
