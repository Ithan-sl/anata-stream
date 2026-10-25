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
import socket

# Força o flush imediato dos logs no terminal e no runner do GitHub Actions
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)


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

# Credenciais carregadas estritamente de variáveis de ambiente (sem valores expostos)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Ithan-sl/anata-stream")
TMDB_TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

session = requests.Session()
BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "X-Requested-With": PACKAGE_NAME,
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"
}
session.headers.update(BASE_HEADERS)

def check_supabase_health() -> bool:
    """Valida se o Supabase está online e com DNS ativo antes de iniciar qualquer operação."""
    if not SUPABASE_URL:
        print("[❌ ERRO] SUPABASE_URL não configurada.")
        return False
    host = urllib.parse.urlparse(SUPABASE_URL).netloc
    try:
        socket.gethostbyname(host)
    except socket.gaierror:
        print("\n" + "=" * 70)
        print("❌ [ERRO CRÍTICO SUPABASE] DNS NÃO ENCONTRADO PARA:")
        print(f"   {SUPABASE_URL}")
        print("\n   MOTIVO:")
        print("   O projeto Supabase foi PAUSADO por inatividade (Free Tier pausa após 7 dias sem acesso).")
        print("   Por isso, nenhuma conexão ou inserção de episódios no banco consegue ser realizada.")
        print("\n   COMO REATIVAR:")
        print("   1. Acesse o painel da Supabase: https://supabase.com/dashboard")
        print("   2. Selecione seu projeto e clique no botão 'Restore project' (ou 'Unpause').")
        print("   3. Aguarde 1 a 2 minutos para o banco e o DNS restabelecerem.")
        print("   4. Execute o workflow do GitHub Actions novamente.")
        print("=" * 70 + "\n")
        return False
    except Exception as e:
        print(f"[-] Erro ao verificar DNS do Supabase: {e}")
        return False

    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/animes?select=id&limit=1",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            timeout=10
        )
        if r.status_code in [200, 206]:
            print(f"[✓] Conexão com Supabase validada com sucesso ({host}).")
            return True
        else:
            print(f"[-] Supabase retornou status HTTP {r.status_code}: {r.text}")
            return False
    except Exception as e:
        print(f"[-] Falha na requisição ao Supabase: {e}")
        return False

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
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"[-] Erro ao consultar Supabase (status {r.status_code}): {r.text}")
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
    except Exception as e:
        print(f"[-] Exceção ao consultar episódios existentes: {e}")
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
            r = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}", headers=headers, params={"language": "pt-BR"}, timeout=10)
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
            r = requests.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}", headers=headers, params={"language": "pt-BR"}, timeout=10)
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
        r = requests.get("https://api.themoviedb.org/3/search/multi", headers=headers, params={"query": clean_search, "language": "pt-BR"}, timeout=10)
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
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT")
    if not token:
        print("      [-] Erro: GITHUB_TOKEN / GH_PAT não definido para despacho.")
        return False

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
        except Exception as e:
            print(f"      [-] Erro na conexão com GitHub (Tentativa {attempt+1}): {e}")
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
            capture_output=True, text=True, timeout=45
        )
        existing_id = check_res.stdout.strip().splitlines()[0] if check_res.stdout.strip() else ""
        if existing_id:
            print(f"      [✓ Já no Drive] Arquivo existente detectado (ID: {existing_id}). Vinculando no Supabase...")
            linked = False
            for sub_attempt in range(1, 4):
                try:
                    indexer.link_stream_source(int(tmdb_id), season_num, ep_num, existing_id, file_name, 0)
                    print(f"      [✓ SUCESSO] T{season_num:02d}E{ep_num:02d} vinculado ao Supabase!")
                    linked = True
                    break
                except Exception as link_err:
                    print(f"      [-] Erro ao vincular ao Supabase (Tentativa {sub_attempt}/3): {link_err}")
                    time.sleep(sub_attempt * 2)
            if linked:
                return True
            else:
                print(f"      [❌ ERRO] Falha ao registrar arquivo existente no Supabase. O episódio NÃO será ignorado.")
                return False
    except Exception as e:
        print(f"      [!] Falha na checagem anti-duplicação: {e}")

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
            capture_output=True, text=True, check=True, timeout=45
        )
        gdrive_id = id_res.stdout.strip().splitlines()[0]
        subprocess.run(["rclone", "link", f"{dest_dir}/{file_name}"], capture_output=True, timeout=45)
    except Exception as e:
        print(f"      [-] Falha ao obter ID do arquivo no Google Drive: {e}")
        if os.path.exists(local_temp):
            os.remove(local_temp)
        return False

    # 6. Sincroniza Metadados no Supabase
    print(f"      [+] Sincronizando com Supabase...")
    supabase_ok = False
    for sub_attempt in range(1, 4):
        try:
            indexer.link_stream_source(int(tmdb_id), season_num, ep_num, gdrive_id, file_name, file_bytes)
            print(f"      [✓ SUCESSO] T{season_num:02d}E{ep_num:02d} enviado e registrado no Supabase!")
            supabase_ok = True
            break
        except Exception as e:
            print(f"      [-] Erro ao atualizar Supabase (Tentativa {sub_attempt}/3): {e}")
            time.sleep(sub_attempt * 2)

    # 7. Limpeza do arquivo temporário
    if os.path.exists(local_temp):
        os.remove(local_temp)

    if not supabase_ok:
        print(f"      [❌ ERRO] Episódio T{season_num:02d}E{ep_num:02d} NÃO foi registrado no Supabase.")
        return False

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

    success = False
    for attempt in range(1, 4):
        try:
            p_res = session.post(player_url, json=player_payload, timeout=20)
            p_data = p_res.json()
            if not p_data.get("success") or not p_data.get("players"):
                print(f"  [!] [Tentativa {attempt}/3] Nenhum stream retornado para o filme '{title}'.")
                time.sleep(3)
                continue

            video_stream = p_data["players"][0].get("file")
            clean_slug = re.sub(r'[^a-zA-Z0-9]+', '-', title).strip('-').lower()
            slug = f"{clean_slug}-filme"

            print(f"  ▶ [Tentativa {attempt}/3] Processando Filme de Animação: {title} (TMDB {tmdb_id})...")
            if process_episode(video_stream, tmdb_id, 1, 1, slug, mode=mode):
                success = True
                break
            time.sleep(3)
        except Exception as e:
            print(f"  [-] [Tentativa {attempt}/3] Erro no player do filme: {e}")
            time.sleep(3)

    if not success:
        print(f"  [❌ ERRO] Não foi possível colher o filme '{title}' após 3 tentativas.")

def get_post_tmdb_id(post_id: str, url_path: str = None) -> str | None:
    """Extrai o TMDB ID do post a partir do Set-Cookie seasons_{post_id}."""
    url = f"{BASE_URL}{url_path}" if url_path else f"{BASE_URL}/posts/animes/post/{post_id}"
    try:
        pr = session.get(url, timeout=12)
        sc = pr.headers.get("Set-Cookie", "")
        m = re.search(rf'seasons_{post_id}=([^;]+)', sc)
        if m:
            sd = json.loads(urllib.parse.unquote(m.group(1)))
            if sd and sd[0].get("tmdb"):
                return str(sd[0].get("tmdb"))
    except Exception:
        pass
    return None

def find_smartplay_post(title: str, original_title: str, target_tmdb: str, extra_hints: list = None) -> tuple[str, str]:
    """
    Localiza o post exato no SmartPlay Lite para um anime.
    Gera múltiplas consultas (título PT, título original, título canônico em inglês no TMDB,
    títulos alternativos e dicas de arquivos já upados) e valida pelo TMDB ID embutido no post.
    """
    candidate_queries = []
    if extra_hints:
        for h in extra_hints:
            if h and len(h) >= 3:
                candidate_queries.append(h)

    if title:
        c1 = re.sub(r'[\(\)\[\]\-:]+', ' ', title).strip()
        candidate_queries.append(c1)
        w1 = c1.split()
        if len(w1) > 3:
            candidate_queries.append(' '.join(w1[:3]))
        if len(w1) > 2:
            candidate_queries.append(' '.join(w1[:2]))

    # Consulta TMDB para obter o nome canônico em inglês (SmartPlay Lite costuma indexar títulos em inglês)
    if target_tmdb and target_tmdb != "0":
        try:
            tmdb_headers = {"Authorization": f"Bearer {TMDB_TOKEN}", "Accept": "application/json"}
            tmdb_r = requests.get(f"https://api.themoviedb.org/3/tv/{target_tmdb}", headers=tmdb_headers, timeout=8)
            if tmdb_r.status_code == 200:
                t_data = tmdb_r.json()
                en_name = t_data.get("name")
                if en_name:
                    c_en = re.sub(r'[\(\)\[\]\-:]+', ' ', en_name).strip()
                    candidate_queries.append(c_en)
                    w_en = c_en.split()
                    if len(w_en) > 3:
                        candidate_queries.append(' '.join(w_en[:3]))
                    if len(w_en) > 2:
                        candidate_queries.append(' '.join(w_en[:2]))
            elif tmdb_r.status_code == 404:
                # Caso filme de animação
                tmdb_m = requests.get(f"https://api.themoviedb.org/3/movie/{target_tmdb}", headers=tmdb_headers, timeout=8)
                if tmdb_m.status_code == 200:
                    m_data = tmdb_m.json()
                    en_m_name = m_data.get("title")
                    if en_m_name:
                        c_en_m = re.sub(r'[\(\)\[\]\-:]+', ' ', en_m_name).strip()
                        candidate_queries.append(c_en_m)
        except Exception:
            pass

    if original_title:
        c2 = re.sub(r'[\(\)\[\]\-:]+', ' ', original_title).strip()
        candidate_queries.append(c2)
        w2 = c2.split()
        if len(w2) > 3:
            candidate_queries.append(' '.join(w2[:3]))
        if len(w2) > 2:
            candidate_queries.append(' '.join(w2[:2]))

    # Adiciona palavras-chave individuais relevantes (>= 5 letras) para capturar títulos longos
    for word in (title or '').split():
        clean_w = re.sub(r'[^a-zA-Z0-9]+', '', word)
        if len(clean_w) >= 5 and clean_w.lower() not in ["season", "series", "episodio", "episode"]:
            candidate_queries.append(clean_w)

    seen = set()
    queries = []
    for q in candidate_queries:
        q_clean = q.strip()
        if q_clean.lower() not in seen and len(q_clean) >= 2:
            seen.add(q_clean.lower())
            queries.append(q_clean)

    # 1. Procura com validação de TMDB ID exato
    for query in queries:
        prune_cookies()
        for retry in range(2):
            try:
                s_res = session.get(f"{BASE_URL}/search/1", params={"search": query}, timeout=20)
                matches = re.findall(r'<a href=\"(/posts/[^/]+/post/(\d+))\".*?<h3><a [^>]*>(.*?)</a></h3>', s_res.text, re.DOTALL)
                for url_path, pid, m_title in matches:
                    if "/posts/animes/" in url_path or "/posts/filmes/" in url_path:
                        post_tmdb = get_post_tmdb_id(pid, url_path)
                        if post_tmdb and str(post_tmdb) == str(target_tmdb):
                            return pid, m_title.strip()
                break
            except Exception:
                time.sleep(2)
                continue

    # 2. Fallback de busca caso o TMDB ID não tenha sido extraído do cookie
    for query in queries[:3]:
        for retry in range(2):
            try:
                s_res = session.get(f"{BASE_URL}/search/1", params={"search": query}, timeout=20)
                matches = re.findall(r'<a href=\"(/posts/[^/]+/post/(\d+))\".*?<h3><a [^>]*>(.*?)</a></h3>', s_res.text, re.DOTALL)
                for url_path, pid, m_title in matches:
                    if "/posts/animes/" in url_path:
                        return pid, m_title.strip()
                break
            except Exception:
                time.sleep(2)
                continue

    return None, None

def extract_episodes_from_html(html: str) -> list[tuple[str, str]]:
    """
    Extrai todos os episódios disponíveis de uma temporada no SmartPlay Lite de forma 100% precisa.
    Retorna lista de (ep_id, ep_label).
    """
    pattern = []
    # 1. Extração robusta por bloco episode-header (garante que 100% dos episódios sejam capturados)
    for ep_match in re.finditer(r'<div class="episode-header">(.*?)<div class="episode-right">', html, re.DOTALL):
        block = ep_match.group(1)
        m_id = re.search(r'loadEpisodePlayers\([\'"](\d+)[\'"],\s*[\'"]PLAY[\'"]\)', block)
        if not m_id:
            continue
        ep_id = m_id.group(1)
        m_title = re.search(r'<div class="episode-title">(.*?)</div>', block)
        label = m_title.group(1).strip() if m_title else ""
        if not label:
            m_alt = re.search(r'alt=[\'"](.*?)[\'"]', block)
            label = m_alt.group(1).strip() if m_alt else f"Episódio {len(pattern)+1}"
        pattern.append((ep_id, label))

    if pattern:
        return pattern

    # 2. Fallback caso a estrutura HTML mude ligeiramente
    play_calls = re.findall(r'loadEpisodePlayers\([\'"](\d+)[\'"],\s*[\'"]PLAY[\'"]\)', html)
    unique_ids = list(dict.fromkeys(play_calls))
    for idx, ep_id in enumerate(unique_ids, 1):
        m_title = re.search(rf'loadEpisodePlayers\([\'"]{ep_id}[\'"].*?<div class="episode-title">(.*?)</div>', html, re.DOTALL)
        label = m_title.group(1).strip() if m_title else f"Episódio {idx}"
        pattern.append((ep_id, label))

    return pattern

def parse_episode_number(ep_label: str, fallback_idx: int) -> int:
    """Extrai com máxima precisão o número do episódio de qualquer formato textual do SmartPlay Lite."""
    label = ep_label.strip()

    # 1. S01E05 / T01E05 format
    m_sxe = re.search(r'[st]\d+\s*e(\d+)', label, re.I)
    if m_sxe:
        return int(m_sxe.group(1))

    # 2. Season x Episode: 1x05, 01x12
    m_sx = re.search(r'\b\d+\s*x\s*(\d+)\b', label, re.I)
    if m_sx:
        return int(m_sx.group(1))

    # 3. Explicit episode marker: EP 5, Episódio 12, Cap 3
    m_ep = re.search(r'(?:epis[oó]dio|cap[ií]tulo|\bep)\s*[:#\.\-]?\s*(\d+)\b', label, re.I)
    if m_ep:
        return int(m_ep.group(1))

    # 4. Trailing number at the end of the string: e.g. 'BanG Dream! 05'
    m_end = re.search(r'\b(\d+)\s*$', label)
    if m_end:
        return int(m_end.group(1))

    # 5. Standalone E + number: e.g. 'E05', 'E 5'
    m_e = re.search(r'\be\s*(\d+)\b', label, re.I)
    if m_e:
        return int(m_e.group(1))

    # 6. Any standalone number in string
    m_any = re.search(r'\b(\d+)\b', label)
    if m_any:
        return int(m_any.group(1))

    return fallback_idx

def harvest_anime_post(post_id: str, anime_title: str, mode: str = "direct", target_tmdb: str = None) -> bool:
    """
    Colhe todas as temporadas e episódios de um post do SmartPlay Lite.
    Garante que TODOS os episódios e temporadas sejam processados sequencialmente com retentativas estritas.
    NÃO avança para o próximo anime enquanto houver episódios pendentes que possam ser baixados.
    """
    prune_cookies(keep_post_id=str(post_id))
    post_url = f"{BASE_URL}/posts/animes/post/{post_id}"

    res = None
    for retry in range(1, 4):
        try:
            res = session.get(post_url, timeout=20)
            if res.status_code == 200:
                break
        except Exception as e:
            print(f"  [!] Conexão ao post #{post_id} falhou (Tentativa {retry}/3): {e}")
            time.sleep(retry * 2)

    if not res or res.status_code != 200:
        post_url = f"{BASE_URL}/posts/filmes/post/{post_id}"
        try:
            res = session.get(post_url, timeout=20)
        except Exception:
            pass
        if not res or res.status_code != 200:
            print(f"[-] Erro ao carregar #{post_id}: HTTP {res.status_code if res else 'Timeout'}")
            return False

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
        return False

    print(f"  [🎨 ANIMAÇÃO VALIDADA] {anime_title} (TMDB: {sample_tmdb or 'Auto'})")

    # CASO 1: É um Filme de Animação
    movie_match = re.search(r"loadMoviePlayers\(['\"](\d+)['\"],\s*['\"]PLAY['\"]\)", res.text)
    if movie_match:
        movie_id = movie_match.group(1)
        harvest_movie(movie_id, anime_title, sample_tmdb or post_id, mode=mode)
        return True

    # CASO 2: É uma Série de Anime / Animação
    if not seasons_data:
        print(f"[-] Nenhuma temporada encontrada para '{anime_title}' (#{post_id})")
        return False

    seasons_data.sort(key=lambda s: int(s.get("t", 1)))

    print(f"  📋 Mapeando temporadas e episódios de '{anime_title}' ({len(seasons_data)} temporada(s))...")
    all_episodes_items = []

    for s in seasons_data:
        season_id = s.get("ID")
        season_num = int(s.get("t", 1))
        season_name = s.get("nome", f"Temporada {season_num}")
        s_tmdb_id = s.get("tmdb") or sample_tmdb

        ep_url = f"{BASE_URL}/season/{season_id}/episodes"
        ep_res = None
        for s_retry in range(1, 6):
            try:
                prune_cookies(keep_post_id=str(post_id))
                ep_res = session.get(ep_url, timeout=25)
                if ep_res.status_code == 200:
                    break
                print(f"    [!] HTTP {ep_res.status_code} na {season_name} (ID {season_id}) [Tentativa {s_retry}/5]. Retentando...")
                time.sleep(s_retry * 2)
            except Exception as e:
                print(f"    [!] Timeout/Erro na {season_name} (ID {season_id}) [Tentativa {s_retry}/5]: {e}")
                time.sleep(s_retry * 2)

        if not ep_res or ep_res.status_code != 200:
            print(f"    [-] [ERRO CRÍTICO] Falha ao carregar episódios da {season_name}. Temporada inacessível.")
            continue

        season_eps = extract_episodes_from_html(ep_res.text)
        if not season_eps:
            print(f"    [-] Nenhum episódio encontrado na {season_name} (ID {season_id}).")
            continue

        for ep_idx, (ep_id, ep_label) in enumerate(season_eps, 1):
            ep_num = parse_episode_number(ep_label, ep_idx)
            all_episodes_items.append({
                "season_num": season_num,
                "season_name": season_name,
                "season_id": season_id,
                "ep_num": ep_num,
                "ep_id": ep_id,
                "ep_label": ep_label,
                "tmdb_id": s_tmdb_id
            })

    total_found = len(all_episodes_items)
    if total_found == 0:
        print(f"  [-] Nenhum episódio disponível para '{anime_title}' (#{post_id}).")
        return False

    # Sincroniza metadados gerais do TMDB uma única vez no Supabase
    if sample_tmdb and str(sample_tmdb) != "0":
        try:
            import indexer
            indexer.sync_anime(int(sample_tmdb))
        except Exception as e:
            print(f"  [!] Aviso ao sincronizar metadados do TMDB {sample_tmdb}: {e}")

    # Checa episódios já existentes no Google Drive e Supabase
    existing_eps = get_existing_episodes_set(sample_tmdb)
    missing = [item for item in all_episodes_items if (item['season_num'], item['ep_num']) not in existing_eps]

    if not missing:
        print(f"  [✓ 100% COMPLETO] Todos os {total_found} episódios de '{anime_title}' já estão no Google Drive e Supabase.")
        return True

    print(f"  📊 Status atual: {total_found - len(missing)}/{total_found} episódios já no Drive. Faltam {len(missing)} episódio(s).")
    print(f"  🚀 Iniciando ingestão sequencial estrita de '{anime_title}' (bloqueio até 100% concluído)...")

    # GATE DE CONCLUSÃO ESTRITO: Até 3 rodadas completas dedicadas a este anime
    for anime_round in range(1, 4):
        existing_eps = get_existing_episodes_set(sample_tmdb)
        pending = [item for item in all_episodes_items if (item['season_num'], item['ep_num']) not in existing_eps]

        if not pending:
            break

        if anime_round > 1:
            print(f"\n  🔄 [RODADA DE RETENTATIVA {anime_round}/3] Re-tentando {len(pending)} episódios pendentes de '{anime_title}'...")

        for p_idx, item in enumerate(pending, 1):
            s_num = item["season_num"]
            e_num = item["ep_num"]
            ep_id = item["ep_id"]
            ep_label = item["ep_label"]
            tmdb_id = item["tmdb_id"]

            print(f"\n    ▶ [{p_idx}/{len(pending)}] Ingerindo T{s_num:02d}E{e_num:02d} ({ep_label})...")

            player_url = f"{BASE_URL}/player/episode"
            player_payload = {"ep_id": str(ep_id), "action_type": "PLAY"}

            ep_success = False
            for attempt in range(1, 4):
                try:
                    prune_cookies(keep_post_id=str(post_id))
                    p_res = session.post(player_url, json=player_payload, timeout=30)
                    p_data = p_res.json()
                    if not p_data.get("success") or not p_data.get("players"):
                        msg = p_data.get("message", "Sem players disponíveis")
                        print(f"      [!] [Tentativa {attempt}/3] {msg}. Aguardando retentativa...")
                        time.sleep(attempt * 3)
                        continue

                    video_stream = p_data["players"][0].get("file")
                    clean_anime_slug = re.sub(r'[^a-zA-Z0-9]+', '-', anime_title).strip('-').lower()
                    slug = f"{clean_anime_slug}-s{s_num:02d}e{e_num:02d}"

                    ok = process_episode(video_stream, tmdb_id, s_num, e_num, slug, mode=mode)
                    if ok:
                        existing_eps.add((s_num, e_num))
                        ep_success = True
                        break
                    else:
                        print(f"      [-] [Tentativa {attempt}/3] Falha na ingestão do episódio. Retentando...")
                        time.sleep(attempt * 3)
                except Exception as ep_err:
                    print(f"      [-] [Tentativa {attempt}/3] Erro: {ep_err}")
                    time.sleep(attempt * 3)

            if not ep_success:
                print(f"      [❌ ERRO] Não foi possível completar T{s_num:02d}E{e_num:02d} nesta rodada.")

            time.sleep(1)

    # Verificação Final
    final_existing = get_existing_episodes_set(sample_tmdb)
    final_pending = [item for item in all_episodes_items if (item['season_num'], item['ep_num']) not in final_existing]

    if not final_pending:
        print(f"\n  [✓ SUCESSO TOTAL] '{anime_title}' 100% CONCLUÍDO ({total_found}/{total_found} episódios em todas as temporadas)!")
        return True
    else:
        print(f"\n  [⚠️ ATENÇÃO] '{anime_title}' finalizou com {len(final_pending)}/{total_found} episódios pendentes.")
        return False

def repair_incomplete_animes(mode: str = "direct"):
    """
    Audita o Supabase em busca de animes com episódios faltando (ex: 0 ou apenas 1 enviado)
    e colhe todos os episódios e temporadas pendentes no SmartPlay Lite até 100% de conclusão.
    """
    print("\n================================================================")
    print("  ANATA STREAM — AUDITORIA & REPARAÇÃO DE LACUNAS NO BANCO")
    print("================================================================\n")

    url = f"{SUPABASE_URL}/rest/v1/animes?select=id,tmdb_id,title,original_title,seasons(id,season_number,episodes(id,episode_number,media_sources(id,file_name,gdrive_file_id)))"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    try:
        r = requests.get(url, headers=headers, timeout=25)
        if r.status_code != 200:
            print(f"[-] Erro fatal ao consultar Supabase (status {r.status_code}): {r.text}")
            return
        animes = r.json()
    except Exception as e:
        print(f"[-] Erro fatal de conexão com Supabase: {e}")
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
        if total_eps == 0 or uploaded_eps < total_eps:
            missing = (total_eps - uploaded_eps) if total_eps > 0 else 0
            incomplete_list.append((a, total_eps, uploaded_eps, missing))

    if not incomplete_list:
        print("[✓] Todos os animes cadastrados estão 100% completos! Nenhuma lacuna detectada.")
        return

    print(f"[!] Detectados {len(incomplete_list)} animes com episódios faltando no Google Drive!")

    for idx, (anime, total_eps, uploaded_eps, missing) in enumerate(incomplete_list, 1):
        tmdb_id = str(anime.get("tmdb_id"))
        title = anime.get("title", "")
        original_title = anime.get("original_title", "")
        clean_title = (
            title.replace("&acute;", "´")
            .replace("&ccedil;", "ç")
            .replace("&atilde;", "ã")
            .replace("&eacute;", "é")
            .replace("&ocirc;", "ô")
            .strip()
        )
        print(f"\n================================================================")
        print(f"⚡ [REPARANDO {idx}/{len(incomplete_list)}] {clean_title} (TMDB {tmdb_id})")
        print(f"   Status: {uploaded_eps}/{total_eps} episódios no Drive (Faltam {missing} episódios)")
        print(f"================================================================")

        # Extrai pistas de nomes de arquivos anteriores para busca precisa no SmartPlay
        extra_hints = []
        for s in anime.get("seasons", []):
            for ep in s.get("episodes", []):
                for m in ep.get("media_sources", []):
                    fname = m.get("file_name", "")
                    slug_match = re.match(r'^(.*?)-s\d+e\d+', fname, re.I)
                    if slug_match:
                        h = slug_match.group(1).replace('-', ' ').strip()
                        if h and h not in extra_hints:
                            extra_hints.append(h)

        # Localiza o post com correspondência inteligente e validação por TMDB ID
        post_match = find_smartplay_post(clean_title, original_title, tmdb_id, extra_hints=extra_hints)
        matched_post_id, matched_title = post_match if (post_match and len(post_match) == 2) else (None, None)

        if not matched_post_id:
            print(f"   [-] Anime não encontrado no catálogo do SmartPlay Lite.")
            continue

        print(f"   [+] Post correspondente: #{matched_post_id} ('{matched_title}'). Colhendo episódios faltantes...")
        harvest_anime_post(matched_post_id, clean_title, mode=mode, target_tmdb=tmdb_id)

def crawl_catalog(start_page: int = 1, max_pages: int = 3, mode: str = "direct"):
    """
    Percorre páginas do catálogo SmartPlay Lite processando cada anime estritamente
    até que todas as suas temporadas e episódios sejam 100% concluídos.
    """
    print("\n================================================================")
    print("  ANATA STREAM — VARREDURA DE CATÁLOGO (PÁGINAS)")
    print("================================================================\n")

    for page in range(start_page, start_page + max_pages):
        print(f"\n🌐 [PÁGINA {page}] Varrendo catálogo...")
        prune_cookies()
        page_url = f"{BASE_URL}/posts/animes/{page}"

        try:
            res = session.get(page_url, timeout=20)
        except Exception as e:
            print(f"[-] Erro de conexão na página {page}: {e}")
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

        print(f"[+] {len(matches)} títulos encontrados na página {page}.\n")
        for idx, (post_id, title) in enumerate(matches, 1):
            clean_title = (
                title.replace("&acute;", "´")
                .replace("&ccedil;", "ç")
                .replace("&atilde;", "ã")
                .replace("&eacute;", "é")
                .replace("&ocirc;", "ô")
                .strip()
            )
            print(f"\n================================================================")
            print(f"🎬 [ANIME {idx}/{len(matches)} DA PÁGINA {page}] {clean_title} (#{post_id})")
            print(f"================================================================")
            anime_ok = harvest_anime_post(post_id, clean_title, mode=mode)
            if not anime_ok:
                print(f"  [⛔ BLOQUEIO DE SEGURANÇA] Anime '{clean_title}' (#{post_id}) não pôde ter todos os episódios concluídos.")
                print("  -> Interrompendo a varredura para NUNCA pular episódios nem avançar com dados incompletos.")
                return False

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

    # Pré-validação estrita do Supabase antes de iniciar qualquer trabalho
    if not check_supabase_health():
        sys.exit(1)

    if args.action in ["all", "repair"]:
        repair_incomplete_animes(mode=args.mode)

    if args.action in ["all", "crawl"]:
        crawl_catalog(start_page=args.start, max_pages=args.pages, mode=args.mode)

    print("\n[✓] Execução do Harvester concluída com sucesso!")

if __name__ == "__main__":
    main()
