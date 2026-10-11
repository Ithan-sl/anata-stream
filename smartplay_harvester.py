#!/usr/bin/env python3
"""
smartplay_harvester.py — Harvester Inteligente & Reparador de Catálogo de Animes
Funcionalidades:
 1. Auditoria e Reparação: Detecta animes no Supabase com episódios faltando (0 eps ou apenas 1 ep)
    e colhe todos os episódios e temporadas pendentes sem duplicar nada.
 2. Varredura do Catálogo: Percorre as páginas de animes e filmes do SmartPlay Lite,
    filtrando estritamente conteúdos animados (Anime & Animação Ocidental como Rick and Morty).
    Bloqueia filmes e séries normais com atores reais (Live-Action).
 3. Modo Direto (Direct Ingest): Baixa com ffmpeg (-c copy), envia ao Google Drive via Rclone,
    e sincroniza no Supabase diretamente no runner. Elimina filas descartadas e sobrecarga de VMs.
 4. Modo Despacho (Dispatch): Permite enfileirar tarefas individuais no GitHub Actions.
"""

import os
import sys
import time
import re
import urllib.parse
import json
import argparse
import subprocess
import requests

# Carrega arquivo .env local se existir
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
if os.path.isfile(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ:
                    os.environ[k] = v

BASE_URL = "https://smartplayliteapk.net"
USER_AGENT = "Mozilla/5.0 (Linux; Android 10; NEN-LX1 Build/HUAWEINEN-LX1; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/83.0.4103.106 Mobile Safari/537.36"
EXOPLAYER_UA = "KlPlayerView/smart-play-lite-apk-1.4 (Linux;Android 10) ExoPlayerLib/2.16.1"
PACKAGE_NAME = "com.visionvibes2v2.trailer"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT") or "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"
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Ithan-sl/anata-stream")
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
session.headers.update(BASE_HEADERS)

def prune_cookies(keep_post_id: str = None):
    """Remove cookies de temporadas de outros posts para evitar erro HTTP 431."""
    keys_to_del = []
    for k in session.cookies.keys():
        if k.startswith("seasons_") or k.startswith("current_season_"):
            if not keep_post_id or (keep_post_id not in k):
                keys_to_del.append(k)
    for k in keys_to_del:
        del session.cookies[k]

def is_rclone_available() -> bool:
    """Verifica se rclone está instalado e configurado com o remote gdrive:."""
    try:
        res = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True, timeout=5)
        return "gdrive:" in res.stdout
    except Exception:
        return False

def check_gdrive_storage_limit() -> bool:
    """Verifica se o espaço usado no Google Drive excedeu o limite de segurança de 4TB."""
    try:
        res = subprocess.run(
            ["rclone", "size", "gdrive:Animes", "--json"],
            capture_output=True, text=True, timeout=15
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)
            bytes_used = data.get("bytes", 0)
            max_bytes = 4 * 1024 * 1024 * 1024 * 1024  # 4TB
            if bytes_used >= max_bytes:
                print(f"[-] LIMITE 4TB ATINGIDO no Google Drive: {bytes_used} >= {max_bytes} bytes. Abortando.")
                return False
        return True
    except Exception:
        return True

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
                m_type = res.get("media_type")
                g_ids = res.get("genre_ids", [])
                if 16 in g_ids:
                    return True, m_type
    except Exception:
        pass

    return False, "none"

def dispatch_to_github(stream_url: str, tmdb_id: str, season_num: int, ep_num: int, title_slug: str) -> bool:
    """Envia o episódio para o runner do GitHub Actions via workflow_dispatch."""
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

def ingest_direct(stream_url: str, tmdb_id: str, season_num: int, ep_num: int, title_slug: str) -> bool:
    """
    Executa a ingestão completa no próprio runner:
    1. Verifica se já está no Google Drive
    2. Baixa com ffmpeg (-c copy)
    3. Envia para o Google Drive com rclone
    4. Sincroniza metadados e vincula no Supabase
    """
    import indexer

    dest_dir = f"gdrive:Animes/{tmdb_id}/Season_{season_num}"
    file_name = f"{title_slug}.mp4"

    # 1. Verifica limite de 4TB
    if not check_gdrive_storage_limit():
        return False

    # 2. Anti-duplicação: verifica se já existe no Google Drive
    try:
        check_res = subprocess.run(
            ["rclone", "lsf", dest_dir, "--format", "i", "--files-only", "--filter", f"+ {file_name}"],
            capture_output=True, text=True, timeout=15
        )
        existing_id = check_res.stdout.strip().splitlines()[0] if check_res.stdout.strip() else ""
        if existing_id:
            print(f"      [✓ Já no Drive] Arquivo existente detectado (ID: {existing_id}). Vinculando no Supabase...")
            indexer.sync_anime(int(tmdb_id))
            indexer.link_stream_source(int(tmdb_id), season_num, ep_num, existing_id, file_name, 0)
            return True
    except Exception:
        pass

    # 3. Download e Remux direto via ffmpeg
    local_temp = f"/tmp/{file_name}"
    if os.path.exists(local_temp):
        os.remove(local_temp)

    print(f"      [*] Baixando e remuxando stream (-c copy)...")
    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-user_agent", EXOPLAYER_UA,
        "-i", stream_url,
        "-c", "copy", "-movflags", "+faststart",
        local_temp
    ]
    try:
        subprocess.run(ffmpeg_cmd, check=True, timeout=300)
    except Exception as e:
        print(f"      [-] Erro no ffmpeg ao baixar stream: {e}")
        if os.path.exists(local_temp):
            os.remove(local_temp)
        return False

    file_bytes = os.path.getsize(local_temp) if os.path.exists(local_temp) else 0

    # 4. Upload para o Google Drive via Rclone
    print(f"      [*] Enviando via Rclone para {dest_dir} ({file_bytes / (1024*1024):.1f} MB)...")
    rclone_cmd = [
        "rclone", "copy", local_temp, dest_dir,
        "--drive-chunk-size", "64M",
        "--transfers", "4"
    ]
    try:
        subprocess.run(rclone_cmd, check=True, timeout=600)
    except Exception as e:
        print(f"      [-] Erro no upload via Rclone: {e}")
        if os.path.exists(local_temp):
            os.remove(local_temp)
        return False

    # 5. Obtém ID do Google Drive e compartilha link
    try:
        id_res = subprocess.run(
            ["rclone", "lsf", dest_dir, "--format", "i", "--files-only", "--filter", f"+ {file_name}"],
            capture_output=True, text=True, check=True, timeout=15
        )
        gdrive_id = id_res.stdout.strip().splitlines()[0]
        subprocess.run(["rclone", "link", f"{dest_dir}/{file_name}"], capture_output=True, timeout=15)
    except Exception as e:
        print(f"      [-] Falha ao obter ID do arquivo no Google Drive: {e}")
        if os.path.exists(local_temp):
            os.remove(local_temp)
        return False

    # 6. Sincroniza Metadados no Supabase
    print(f"      [+] Sincronizando com Supabase...")
    try:
        indexer.sync_anime(int(tmdb_id))
        indexer.link_stream_source(int(tmdb_id), season_num, ep_num, gdrive_id, file_name, file_bytes)
        print(f"      [✓ SUCESSO] T{season_num:02d}E{ep_num:02d} enviado e registrado no Supabase!")
    except Exception as e:
        print(f"      [-] Erro ao atualizar Supabase: {e}")

    # 7. Limpeza do arquivo temporário
    if os.path.exists(local_temp):
        os.remove(local_temp)

    return True

def process_episode(stream_url: str, tmdb_id: str, season_num: int, ep_num: int, title_slug: str, mode: str = "direct") -> bool:
    """Roteia para direct ou dispatch com base no modo e disponibilidade."""
    if mode == "direct" and is_rclone_available():
        return ingest_direct(stream_url, tmdb_id, season_num, ep_num, title_slug)
    else:
        return dispatch_to_github(stream_url, tmdb_id, season_num, ep_num, title_slug)

def harvest_movie(movie_id: str, title: str, tmdb_id: str, mode: str = "direct"):
    """Processa e ingere um filme de animação."""
    existing = get_existing_episodes_set(tmdb_id)
    if (1, 1) in existing:
        print(f"  [✓ Já no Drive] Filme '{title}' já armazenado no Google Drive. Pulando...")
        return

    player_url = f"{BASE_URL}/player/movie"
    player_payload = {"movie_id": str(movie_id), "action_type": "PLAY"}
    prune_cookies()

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

    print(f"  ▶ Processando Filme de Animação: {title} (TMDB {tmdb_id})...")
    process_episode(video_stream, tmdb_id, 1, 1, slug, mode=mode)
    time.sleep(2)

def harvest_anime_post(post_id: str, anime_title: str, mode: str = "direct", target_tmdb: str = None):
    """
    Colhe todas as temporadas e episódios de um post do SmartPlay Lite.
    Garante que TODOS os episódios faltantes sejam processados.
    """
    prune_cookies(keep_post_id=str(post_id))
    post_url = f"{BASE_URL}/posts/animes/post/{post_id}"

    try:
        res = session.get(post_url, timeout=15)
    except Exception as e:
        print(f"[-] Falha ao conectar ao título #{post_id}: {e}")
        return

    if res.status_code != 200:
        post_url = f"{BASE_URL}/posts/filmes/post/{post_id}"
        res = session.get(post_url, timeout=15)
        if res.status_code != 200:
            print(f"[-] Erro ao carregar #{post_id}: HTTP {res.status_code}")
            return

    # Extrai temporadas dos cookies
    set_cookie_header = res.headers.get("Set-Cookie", "")
    seasons_key = f"seasons_{post_id}"
    m = re.search(rf'{seasons_key}=([^;]+)', set_cookie_header)
    raw_seasons = m.group(1) if m else session.cookies.get(seasons_key)

    sample_tmdb = target_tmdb
    seasons_data = []
    if raw_seasons:
        try:
            seasons_data = json.loads(urllib.parse.unquote(raw_seasons))
            if seasons_data and not sample_tmdb:
                sample_tmdb = seasons_data[0].get("tmdb")
        except Exception:
            pass

    # Validação do filtro de animação
    is_anim, media_kind = is_allowed_animation(sample_tmdb, anime_title)
    if not is_anim:
        print(f"  [🚫 BLOQUEADO] '{anime_title}' NÃO é animação (Live-action detectado). Pulando...")
        return

    print(f"  [🎨 ANIMAÇÃO VALIDADA] {anime_title} (TMDB: {sample_tmdb or 'Auto'})")

    # CASO 1: É um Filme de Animação
    movie_match = re.search(r"loadMoviePlayers\(['\"](\d+)['\"],\s*['\"]PLAY['\"]\)", res.text)
    if movie_match:
        movie_id = movie_match.group(1)
        harvest_movie(movie_id, anime_title, sample_tmdb or post_id, mode=mode)
        return

    # CASO 2: É uma Série de Anime / Animação
    if not seasons_data:
        print(f"[-] Nenhuma temporada encontrada para '{anime_title}' (#{post_id})")
        return

    existing_eps = get_existing_episodes_set(sample_tmdb)
    if existing_eps:
        print(f"  📊 Status no banco: {len(existing_eps)} episódio(s) já armazenado(s).")

    seasons_data.sort(key=lambda s: int(s.get("t", 1)))

    for s in seasons_data:
        season_id = s.get("ID")
        season_num = int(s.get("t", 1))
        season_name = s.get("nome", f"Temporada {season_num}")
        tmdb_id = s.get("tmdb") or sample_tmdb

        prune_cookies(keep_post_id=str(post_id))
        ep_url = f"{BASE_URL}/season/{season_id}/episodes"

        try:
            ep_res = session.get(ep_url, timeout=15)
        except Exception as e:
            print(f"  [-] Timeout na temporada {season_id}: {e}")
            continue

        if ep_res.status_code != 200:
            print(f"  [-] Erro HTTP {ep_res.status_code} na temporada {season_id}")
            continue

        # Regex para capturar todos os episódios da temporada
        pattern = re.findall(
            r'loadEpisodePlayers\([\'"](\d+)[\'"],\s*[\'"]PLAY[\'"]\).*?<div class="episode-title">(.*?)</div>',
            ep_res.text,
            re.DOTALL
        )

        # Fallback caso a tag da classe div seja ligeiramente diferente
        if not pattern:
            raw_eps = re.findall(r'loadEpisodePlayers\([\'"](\d+)[\'"],\s*[\'"]PLAY[\'"]\)', ep_res.text)
            pattern = [(ep_id, f"Episódio {idx+1}") for idx, ep_id in enumerate(raw_eps)]

        if not pattern:
            print(f"  [-] Nenhum episódio encontrado na temporada {season_name} (ID {season_id})")
            continue

        total_eps = len(pattern)
        season_existing = [e for (s_idx, e) in existing_eps if s_idx == season_num]

        if len(season_existing) == total_eps and total_eps > 0:
            print(f"  [✓ COMPLETO] {season_name} ({total_eps}/{total_eps} eps já no Google Drive).")
            continue

        missing_count = total_eps - len(season_existing)
        print(f"\n  📂 {season_name} ({len(season_existing)}/{total_eps} disponíveis | ⚡ Faltam {missing_count} episódios)")

        for ep_idx, (ep_id, ep_label) in enumerate(pattern, 1):
            ep_label = ep_label.strip()
            ep_match = re.search(r'(\d+)x(\d+)', ep_label)
            if ep_match:
                ep_num = int(ep_match.group(2))
            else:
                num_only = re.search(r'(?:ep|episodio|\b)(\d+)\b', ep_label, re.IGNORECASE)
                ep_num = int(num_only.group(1)) if num_only else ep_idx

            if (season_num, ep_num) in existing_eps:
                print(f"    [✓ Já no Drive] T{season_num:02d}E{ep_num:02d} - Ignorado.")
                continue

            print(f"    [⚡ LACUNA DETECTADA] T{season_num:02d}E{ep_num:02d} não encontrado no banco. Baixando...")

            player_url = f"{BASE_URL}/player/episode"
            player_payload = {"ep_id": str(ep_id), "action_type": "PLAY"}

            try:
                p_res = session.post(player_url, json=player_payload, timeout=15)
                p_data = p_res.json()
            except Exception as e:
                print(f"      [-] Falha ao obter stream do episódio {ep_id}: {e}")
                continue

            if not p_data.get("success") or not p_data.get("players"):
                print(f"      [-] Stream indisponível para episódio {ep_id}")
                continue

            video_stream = p_data["players"][0].get("file")
            clean_anime_slug = re.sub(r'[^a-zA-Z0-9]+', '-', anime_title).strip('-').lower()
            slug = f"{clean_anime_slug}-s{season_num:02d}e{ep_num:02d}"

            print(f"      ▶ Processando T{season_num:02d}E{ep_num:02d}...")
            ok = process_episode(video_stream, tmdb_id, season_num, ep_num, slug, mode=mode)
            if ok:
                existing_eps.add((season_num, ep_num))
            time.sleep(2)

def repair_incomplete_animes(mode: str = "direct"):
    """
    Audita o Supabase em busca de animes com episódios faltando (ex: 0 ou apenas 1 enviado)
    e colhe todos os episódios e temporadas pendentes no SmartPlay Lite.
    """
    print("\n================================================================")
    print("  ANATA STREAM — AUDITORIA & REPARAÇÃO DE LACUNAS NO BANCO")
    print("================================================================\n")

    url = f"{SUPABASE_URL}/rest/v1/animes?select=id,tmdb_id,title,original_title,seasons(id,season_number,episodes(id,episode_number,media_sources(id,gdrive_file_id)))"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"[-] Erro ao consultar Supabase: {r.status_code}")
            return
        animes = r.json()
    except Exception as e:
        print(f"[-] Erro de conexão com Supabase: {e}")
        return

    print(f"[*] Auditando {len(animes)} animes cadastrados no Supabase...\n")

    incomplete_list = []
    for a in animes:
        tmdb_id = str(a.get("tmdb_id"))
        title = a.get("title", "")
        seasons = a.get("seasons", [])
        total_eps = sum(len(s.get("episodes", [])) for s in seasons)
        uploaded_eps = sum(
            1 for s in seasons for ep in s.get("episodes", [])
            if ep.get("media_sources") and len(ep["media_sources"]) > 0
        )
        if total_eps > 0 and uploaded_eps < total_eps:
            missing = total_eps - uploaded_eps
            incomplete_list.append((a, total_eps, uploaded_eps, missing))

    if not incomplete_list:
        print("[✓] Todos os animes cadastrados estão 100% completos! Nenhuma lacuna detectada.")
        return

    print(f"[!] Detectados {len(incomplete_list)} animes com episódios faltando no Google Drive!")

    for anime, total_eps, uploaded_eps, missing in incomplete_list:
        tmdb_id = str(anime.get("tmdb_id"))
        title = anime.get("title", "")
        clean_title = (
            title.replace("&acute;", "´")
            .replace("&ccedil;", "ç")
            .replace("&atilde;", "ã")
            .replace("&eacute;", "é")
            .replace("&ocirc;", "ô")
            .strip()
        )
        print(f"\n⚡ [REPARANDO] {clean_title} (TMDB {tmdb_id})")
        print(f"   Status: {uploaded_eps}/{total_eps} episódios disponíveis (Faltam {missing} episódios)")

        # Busca no catálogo SmartPlay Lite
        search_query = re.sub(r'[\(\)\[\]\-:]+', ' ', clean_title).strip()
        words = search_query.split()
        short_query = ' '.join(words[:4]) if len(words) > 4 else search_query

        prune_cookies()
        try:
            s_res = session.get(f"{BASE_URL}/search/1", params={"search": short_query}, timeout=15)
            matches = re.findall(r'<a href=\"(/posts/[^/]+/post/(\d+))\".*?<h3><a [^>]*>(.*?)</a></h3>', s_res.text, re.DOTALL)
        except Exception as e:
            print(f"   [-] Falha ao buscar no SmartPlay: {e}")
            continue

        matched_post_id = None
        for url_path, pid, m_title in matches:
            if "/posts/animes/" in url_path or "/posts/filmes/" in url_path:
                matched_post_id = pid
                break

        if not matched_post_id:
            print(f"   [-] Não encontrado no catálogo SmartPlay Lite via busca '{short_query}'")
            continue

        print(f"   [+] Post encontrado no SmartPlay Lite: #{matched_post_id}. Iniciando colheita de episódios...")
        harvest_anime_post(matched_post_id, clean_title, mode=mode, target_tmdb=tmdb_id)

def crawl_catalog(start_page: int = 1, max_pages: int = 3, mode: str = "direct"):
    """Percorre páginas do catálogo SmartPlay Lite."""
    print("\n================================================================")
    print("  ANATA STREAM — VARREDURA DE CATÁLOGO (PÁGINAS)")
    print("================================================================\n")

    for page in range(start_page, start_page + max_pages):
        print(f"\n🌐 [PÁGINA {page}] Varrendo catálogo...")
        prune_cookies()
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
            print(f"\n🎬 Analisando: {clean_title} (#{post_id})")
            harvest_anime_post(post_id, clean_title, mode=mode)

def main():
    parser = argparse.ArgumentParser(description="Anata Stream — Anime Harvester & Repair")
    parser.add_argument("--action", choices=["all", "repair", "crawl"], default="all",
                        help="Ação a executar: repair (reparar banco), crawl (varrer catálogo), all (ambos)")
    parser.add_argument("--mode", choices=["direct", "dispatch"], default="direct",
                        help="Modo de processamento: direct (no próprio runner) ou dispatch (GitHub Actions)")
    parser.add_argument("--start", type=int, default=1, help="Página inicial")
    parser.add_argument("--pages", type=int, default=3, help="Total de páginas")
    parser.add_argument("pos_args", nargs="*", help="Compatibilidade com argumentos posicionais antigos")

    args = parser.parse_args()

    # Suporte a argumentos posicionais antigos: python3 smartplay_harvester.py 1 3
    if args.pos_args:
        try:
            args.start = int(args.pos_args[0])
            if len(args.pos_args) > 1:
                args.pages = int(args.pos_args[1])
        except ValueError:
            pass

    print("================================================================")
    print(f"  ANATA STREAM — MODO: {args.action.upper()} | INGESTÃO: {args.mode.upper()}")
    print("================================================================")

    if args.action in ["all", "repair"]:
        repair_incomplete_animes(mode=args.mode)

    if args.action in ["all", "crawl"]:
        crawl_catalog(start_page=args.start, max_pages=args.pages, mode=args.mode)

    print("\n[✓] Execução do Harvester concluída com sucesso!")

if __name__ == "__main__":
    main()
