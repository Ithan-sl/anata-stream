#!/usr/bin/env python3
"""
animeq_harvester.py — Harvester Inteligente & Reparador de Catálogo de Animes (AnimeQ.cloud)
Suporta seções:
  - Filmes (/filme)
  - Hentai (/genre/hentai)
  - Animes Dublados (/tipo/dublado)
  - Animes Legendados (/tipo/legendado)
  - Catálogo Geral (/anime)

Garante conclusão estrita de 100% das temporadas e episódios, limpeza automática de falhas
e bypass de loops em streams mortos ou bloqueados (403/404).
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
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
import socket
import indexer

# Força o flush imediato dos logs
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

BASE_URL = "https://animeq.cloud"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Ithan-sl/anata-stream")
TMDB_TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# Mapeamento oficial das seções do AnimeQ
SECTION_URLS = {
    "filme": f"{BASE_URL}/filme",
    "hentai": f"{BASE_URL}/genre/hentai",
    "dublado": f"{BASE_URL}/tipo/dublado",
    "legendado": f"{BASE_URL}/tipo/legendado",
    "anime": f"{BASE_URL}/anime"
}

# Configura sessão com retentativas automáticas e pool persistente
session = requests.Session()
retries = Retry(total=3, backoff_factor=1.5, status_forcelist=[500, 502, 503, 504, 429])
adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20)
session.mount("https://", adapter)
session.mount("http://", adapter)
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{BASE_URL}/"
})

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
        print("\n   MOTIVO: O projeto Supabase foi pausado ou o domínio não responde.")
        print("   Acesse https://supabase.com/dashboard e clique em 'Restore project'.")
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

def get_existing_episodes_set(tmdb_id: int) -> set:
    """Retorna episódios (season_number, episode_number) já presentes no Supabase e Google Drive."""
    if not tmdb_id or tmdb_id == 0:
        return set()

    url = f"{SUPABASE_URL}/rest/v1/animes?tmdb_id=eq.{tmdb_id}&select=seasons(season_number,episodes(episode_number,media_sources(id,gdrive_file_id)))"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    try:
        r = requests.get(url, headers=headers, timeout=15)
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
    except Exception as e:
        print(f"[-] Exceção ao consultar episódios existentes: {e}")
        return set()

def extract_page_metadata(html: str, anime_url: str, default_title: str) -> dict:
    """
    Extrai título canônico, sinopse real, poster/capa, backdrop e ano diretamente da página do AnimeQ.cloud.
    Garante que se o título não existir no TMDB, o cadastro no Supabase seja rico e completo (sem placeholders).
    """
    meta = {
        "title": default_title,
        "original_title": None,
        "overview": "",
        "poster_path": None,
        "backdrop_path": None,
        "release_date": None,
        "is_movie": "/filme/" in anime_url
    }

    # 1. Título canônico
    canonical_title = None
    if BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            canonical_title = h1.get_text(strip=True)
    if not canonical_title:
        m_h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
        if m_h1:
            canonical_title = re.sub(r'<[^>]+>', '', m_h1.group(1)).strip()
    if not canonical_title:
        m_og_title = re.search(r'<meta[^>]+property=[\'"]og:title[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', html, re.IGNORECASE)
        if m_og_title:
            canonical_title = re.sub(r'\s*[-|–]\s*AnimeQ.*', '', m_og_title.group(1)).strip()

    if canonical_title:
        clean = (
            canonical_title.replace("&acute;", "´")
            .replace("&ccedil;", "ç")
            .replace("&atilde;", "ã")
            .replace("&eacute;", "é")
            .replace("&ocirc;", "ô")
            .replace("&quot;", '"')
            .replace("&#039;", "'")
            .strip()
        )
        if clean:
            meta["title"] = clean

    # 2. Título original
    orig_m = re.search(r'Título Original\s*([^<]+)', html, re.IGNORECASE) or \
             re.search(r'class=[\'"]valor[\'"]>([^<]+)</span>', html, re.IGNORECASE)
    if orig_m:
        meta["original_title"] = orig_m.group(1).strip()

    # 3. Sinopse real
    overview_text = ""
    if BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        p_desc = soup.select_one(".wp-content p, #info .wp-content p, .sbox .wp-content p, .sinopse p, .entry-content p")
        if p_desc and p_desc.get_text(strip=True):
            overview_text = p_desc.get_text(strip=True)
    if not overview_text:
        m_desc = re.search(r'<meta[^>]+property=[\'"]og:description[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', html, re.IGNORECASE)
        if m_desc:
            overview_text = m_desc.group(1).strip()
    if not overview_text:
        m_p = re.search(r'<div[^>]*class=[\'"][^\'"]*wp-content[^\'"]*[\'"][^>]*>[\s\S]*?<p>(.*?)</p>', html, re.IGNORECASE)
        if m_p:
            overview_text = re.sub(r'<[^>]+>', '', m_p.group(1)).strip()

    if overview_text:
        clean_ov = (
            overview_text.replace("&acute;", "´")
            .replace("&ccedil;", "ç")
            .replace("&atilde;", "ã")
            .replace("&eacute;", "é")
            .replace("&ocirc;", "ô")
            .replace("&quot;", '"')
            .replace("&nbsp;", ' ')
            .replace("&#039;", "'")
            .strip()
        )
        if not any(ign in clean_ov.lower() for ign in ["assistir anime online completo", "assistir filmes online"]):
            meta["overview"] = clean_ov

    # 4. Poster real
    poster_src = None
    if BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        p_img = soup.select_one(".poster img, .sheader .poster img, article .poster img")
        if p_img:
            poster_src = p_img.get("src") or p_img.get("data-src") or p_img.get("data-lazy-src")
    if not poster_src:
        m_p_img = re.search(r'<div[^>]*class=[\'"][^\'"]*poster[^\'"]*[\'"][^>]*>[\s\S]*?<img[^>]+(?:src|data-src)=[\'"]([^\'"]+)[\'"]', html, re.IGNORECASE)
        if m_p_img:
            poster_src = m_p_img.group(1)
    if not poster_src:
        m_og_img = re.search(r'<meta[^>]+property=[\'"]og:image[\'"][^>]+content=[\'"]([^\'"]+)[\'"]', html, re.IGNORECASE)
        if m_og_img:
            poster_src = m_og_img.group(1)

    if poster_src:
        if poster_src.startswith("//"):
            poster_src = "https:" + poster_src
        meta["poster_path"] = poster_src

    # 5. Backdrop / Banner real
    backdrop_src = None
    if BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        b_img = soup.select_one(".sbackdrop img, .backdrop img")
        if b_img:
            backdrop_src = b_img.get("src") or b_img.get("data-src")
    if not backdrop_src:
        m_b = re.search(r'<div[^>]*class=[\'"][^\'"]*(?:sbackdrop|backdrop)[^\'"]*[\'"][^>]*>[\s\S]*?<img[^>]+(?:src|data-src)=[\'"]([^\'"]+)[\'"]', html, re.IGNORECASE)
        if m_b:
            backdrop_src = m_b.group(1)
    if backdrop_src:
        if backdrop_src.startswith("//"):
            backdrop_src = "https:" + backdrop_src
        meta["backdrop_path"] = backdrop_src
    else:
        meta["backdrop_path"] = meta["poster_path"]

    # 6. Ano de lançamento
    m_year = re.search(r'\((\d{4})\)', meta["title"]) or re.search(r'<span[^>]*class=[\'"]date[\'"][^>]*>.*?(\d{4}).*?</span>', html, re.IGNORECASE)
    if m_year:
        meta["release_date"] = f"{m_year.group(1)}-01-01"

    return meta

def resolve_tmdb(title: str, original_title: str = None, wp_post_id: str = None, is_movie: bool = False, meta: dict = None) -> int:
    """
    Resolve o TMDB ID oficial pesquisando no TheMovieDB com separação estrita entre filmes e séries.
    Se não for encontrado, registra como título customizado no Supabase usando a sinopse e capa reais da fonte.
    """
    clean_title = re.sub(r'[\(\)\[\]\-:]+', ' ', title).strip()
    search_query = re.sub(r'\b(dublado|legendado|filme|movie|2nd season|season \d+|\d+nd season)\b', '', clean_title, flags=re.I).strip()
    if not search_query:
        search_query = clean_title

    headers = {"Authorization": f"Bearer {TMDB_TOKEN}", "Accept": "application/json"}

    # 1. Pesquisa no TMDB com rota estrita
    endpoints = ["search/movie"] if is_movie else ["search/tv", "search/movie"]
    for ep in endpoints:
        try:
            r = requests.get(f"https://api.themoviedb.org/3/{ep}", headers=headers, params={"query": search_query, "language": "pt-BR"}, timeout=10)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    tmdb_id = int(results[0]["id"])
                    try:
                        indexer.sync_anime(tmdb_id, is_movie=is_movie, custom_meta=meta)
                    except Exception as sync_err:
                        print(f"      [!] Aviso ao sincronizar metadados TMDB: {sync_err}")
                    return tmdb_id
        except Exception:
            pass

    # 2. Tenta busca pelo título original
    if original_title and original_title != title:
        orig_clean = re.sub(r'[\(\)\[\]\-:]+', ' ', original_title).strip()
        for ep in endpoints:
            try:
                r = requests.get(f"https://api.themoviedb.org/3/{ep}", headers=headers, params={"query": orig_clean, "language": "pt-BR"}, timeout=10)
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    if results:
                        tmdb_id = int(results[0]["id"])
                        try:
                            indexer.sync_anime(tmdb_id, is_movie=is_movie, custom_meta=meta)
                        except Exception:
                            pass
                        return tmdb_id
            except Exception:
                pass

    # 3. Fallback: ID sintético único baseado no post_id do WordPress
    if wp_post_id and str(wp_post_id).isdigit():
        synthetic_id = 900000000 + int(wp_post_id)
    else:
        synthetic_id = 900000000 + (abs(hash(clean_title)) % 90000000)

    print(f"      [ℹ️ METADADOS DA FONTE] '{title}' não localizado no TMDB. Registrado com sinopse e capa da fonte AnimeQ (ID #{synthetic_id}).")
    try:
        m = meta or {}
        indexer.sync_custom_anime(
            synthetic_id,
            title=title,
            original_title=original_title or title,
            overview=m.get("overview", ""),
            poster_path=m.get("poster_path"),
            backdrop_path=m.get("backdrop_path"),
            is_movie=is_movie,
            first_air_date=m.get("release_date")
        )
    except Exception as e:
        print(f"      [-] Falha ao sincronizar registro customizado da fonte: {e}")

    return synthetic_id

def extract_stream_urls(page_url: str) -> list[str]:
    """
    Extrai todos os URLs de streaming válidos de um episódio ou filme no AnimeQ.cloud.
    """
    candidates = []
    try:
        r = session.get(page_url, timeout=35)
        if r.status_code != 200:
            return []
        html = r.text
    except Exception as e:
        print(f"      [-] Erro ao carregar página do player ({page_url}): {e}")
        return []

    # 1. Direct <source src="..."> tags
    source_matches = re.findall(r'<source[^>]+src=[\'"]([^\'"]+)[\'"]', html, re.I)
    for s in source_matches:
        if s.startswith("//"):
            s = "https:" + s
        if s not in candidates:
            candidates.append(s)

    # 2. Direct <video src="..."> tags
    video_matches = re.findall(r'<video[^>]+src=[\'"]([^\'"]+)[\'"]', html, re.I)
    for v in video_matches:
        if v.startswith("//"):
            v = "https:" + v
        if v not in candidates:
            candidates.append(v)

    # 3. Dooplay AJAX Player Options
    ajax_options = re.findall(r'data-type=[\'"]([^\'"]+)[\'"][^>]*data-post=[\'"](\d+)[\'"][^>]*data-nume=[\'"](\d+)[\'"]', html)
    if not ajax_options:
        ajax_options = re.findall(r'data-post=[\'"](\d+)[\'"][^>]*data-nume=[\'"](\d+)[\'"][^>]*data-type=[\'"]([^\'"]+)[\'"]', html)
        ajax_options = [(t, p, n) for (p, n, t) in ajax_options]

    for opt_type, post_id, nume in ajax_options:
        try:
            ajax_data = {
                "action": "doo_player_ajax",
                "post": post_id,
                "nume": nume,
                "type": opt_type
            }
            ajax_headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Referer": page_url
            }
            aj_res = session.post(f"{BASE_URL}/wp-admin/admin-ajax.php", data=ajax_data, headers=ajax_headers, timeout=15)
            if aj_res.status_code == 200:
                resp_json = aj_res.json()
                embed_url = resp_json.get("embed_url", "")
                if "source=" in embed_url:
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(embed_url).query)
                    if "source" in parsed:
                        real_url = parsed["source"][0]
                        if real_url not in candidates:
                            candidates.append(real_url)
                elif embed_url and not any(ign in embed_url for ign in ["youtube", "disqus"]):
                    if embed_url not in candidates:
                        candidates.append(embed_url)
        except Exception:
            pass

    # 4. Iframes
    iframe_matches = re.findall(r'<iframe[^>]+src=[\'"]([^\'"]+)[\'"]', html, re.I)
    for ifr in iframe_matches:
        if ifr.startswith("//"):
            ifr = "https:" + ifr
        if not any(ign in ifr for ign in ["youtube", "google.com/recaptcha", "disqus"]):
            if ifr not in candidates:
                candidates.append(ifr)

    # 5. Regex de arquivos de mídia embutidos
    media_regex = re.findall(r'(https?://[^\s\"\'<>]+(?:\.mp4|\.m3u8)[^\s\"\'<>]*)', html)
    for m in media_regex:
        if not any(ign in m for ign in ["wp-content", "dooplay"]):
            if m not in candidates:
                candidates.append(m)

    return candidates

def ingest_direct(stream_url: str, tmdb_id: int, season_num: int, ep_num: int, title_slug: str, is_movie: bool = False, custom_meta: dict = None) -> bool:
    """
    Executa a ingestão direta no runner com ffmpeg (-c copy) e upload Rclone.
    """
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
                    indexer.link_stream_source(int(tmdb_id), season_num, ep_num, existing_id, file_name, 0, is_movie=is_movie, custom_meta=custom_meta)
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

    print(f"      [*] Baixando e remuxando stream com ffmpeg (-c copy)...")
    ffmpeg_headers = f"Referer: {BASE_URL}/\r\nUser-Agent: {USER_AGENT}\r\n"
    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-headers", ffmpeg_headers,
        "-i", stream_url,
        "-c", "copy", "-movflags", "+faststart",
        local_temp
    ]
    try:
        subprocess.run(ffmpeg_cmd, check=True, timeout=300)
    except subprocess.CalledProcessError as e:
        print(f"      [-] Erro no ffmpeg ao baixar stream (exit {e.returncode}): {e}")
        if os.path.exists(local_temp):
            os.remove(local_temp)
        return False
    except subprocess.TimeoutExpired:
        print(f"      [-] Timeout no ffmpeg após 300 segundos.")
        if os.path.exists(local_temp):
            os.remove(local_temp)
        return False
    except Exception as e:
        print(f"      [-] Exceção no ffmpeg: {e}")
        if os.path.exists(local_temp):
            os.remove(local_temp)
        return False

    file_bytes = os.path.getsize(local_temp) if os.path.exists(local_temp) else 0
    if file_bytes < 10000:
        print(f"      [-] Arquivo baixado muito pequeno ({file_bytes} bytes). Stream inválido.")
        if os.path.exists(local_temp):
            os.remove(local_temp)
        return False

    # 4. Upload para o Google Drive via Rclone
    print(f"      [*] Enviando via Rclone para {dest_dir} ({file_bytes / (1024*1024):.1f} MB)...")
    rclone_cmd = [
        "rclone", "copy", local_temp, dest_dir,
        "--drive-chunk-size", "16M",
        "--transfers", "2",
        "--timeout", "60s",
        "--contimeout", "20s",
        "--low-level-retries", "10"
    ]
    try:
        subprocess.run(rclone_cmd, check=True, timeout=300)
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
            indexer.link_stream_source(int(tmdb_id), season_num, ep_num, gdrive_id, file_name, file_bytes, is_movie=is_movie, custom_meta=custom_meta)
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

def dispatch_to_github(stream_url: str, tmdb_id: int, season_num: int, ep_num: int, title_slug: str) -> bool:
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

def process_episode_candidates(stream_candidates: list[str], tmdb_id: int, season_num: int, ep_num: int, title_slug: str, mode: str = "direct", dead_urls: set = None, is_movie: bool = False, custom_meta: dict = None) -> bool:
    """Tenta ingerir o episódio percorrendo os streams candidatos com eliminação de URLs mortas."""
    if not stream_candidates:
        print(f"      [!] Nenhum link de vídeo extraído para este episódio.")
        return False

    if dead_urls is None:
        dead_urls = set()

    valid_candidates = [u for u in stream_candidates if u not in dead_urls]
    if not valid_candidates:
        print(f"      [!] Todos os links candidatos ({len(stream_candidates)}) já falharam anteriormente.")
        return False

    for idx, stream_url in enumerate(valid_candidates, 1):
        print(f"      ▶ Testando fonte {idx}/{len(valid_candidates)}: {stream_url[:75]}...")
        if mode == "direct" and is_rclone_available():
            ok = ingest_direct(stream_url, tmdb_id, season_num, ep_num, title_slug, is_movie=is_movie, custom_meta=custom_meta)
        else:
            ok = dispatch_to_github(stream_url, tmdb_id, season_num, ep_num, title_slug)

        if ok:
            return True

        print(f"      [-] Fonte {idx} falhou. Marcando como inativa.")
        dead_urls.add(stream_url)

    return False

def parse_post_episodes(anime_url: str, html: str) -> list[dict]:
    """
    Extrai as temporadas e episódios de uma página do AnimeQ.
    """
    is_movie = "/filme/" in anime_url
    if is_movie:
        return [{
            "season_num": 1,
            "season_name": "Filme",
            "ep_num": 1,
            "ep_title": "Filme Completo",
            "ep_url": anime_url,
            "is_movie": True
        }]

    episodes_list = []
    
    # 1. Padrão episode-card estruturado
    all_ep_cards = re.findall(
        r'<div class="episode-card"[^>]*data-episode-number=[\'"](\d+)[\'"][^>]*data-episode-title=[\'"]([^\'"]*)[\'"].*?<a href=[\'"]([^\'"]+)[\'"]',
        html,
        re.DOTALL
    )
    if all_ep_cards:
        for ep_num_str, ep_title, ep_href in all_ep_cards:
            ep_num = int(ep_num_str) if ep_num_str.isdigit() else 1
            s_match = re.search(r'temporada-(\d+)|s(\d+)', ep_href, re.I)
            s_num = int(s_match.group(1) or s_match.group(2)) if s_match else 1
            full_ep_url = ep_href if ep_href.startswith("http") else f"{BASE_URL}{ep_href}"
            episodes_list.append({
                "season_num": s_num,
                "season_name": f"Temporada {s_num}",
                "ep_num": ep_num,
                "ep_title": ep_title or f"Episódio {ep_num}",
                "ep_url": full_ep_url,
                "is_movie": False
            })
        return episodes_list

    # 2. Fallback: links de episódios padrão Dooplay
    ep_links = re.findall(r'<a href=[\'"](https?://animeq\.cloud/episodio/[^\'"]+)[\'"]>([^<]*)</a>', html)
    for idx, (ep_href, ep_label) in enumerate(ep_links, 1):
        num_match = re.search(r'episodio-(\d+)', ep_href)
        ep_num = int(num_match.group(1)) if num_match else idx
        episodes_list.append({
            "season_num": 1,
            "season_name": "Temporada 1",
            "ep_num": ep_num,
            "ep_title": ep_label.strip() or f"Episódio {ep_num}",
            "ep_url": ep_href,
            "is_movie": False
        })

    return episodes_list

def harvest_anime(anime_url: str, anime_title: str, mode: str = "direct", strict: bool = True) -> bool:
    """
    Colhe 100% dos episódios de um anime ou filme do AnimeQ.cloud.
    Garante limpeza no Supabase em caso de falha de todos os streams e previne loops.
    """
    html = None
    for r_try in range(1, 4):
        try:
            res = session.get(anime_url, timeout=40)
            if res.status_code == 200:
                html = res.text
                break
            print(f"  [!] HTTP {res.status_code} ao carregar {anime_url} (Tentativa {r_try}/3)")
            time.sleep(r_try * 3)
        except Exception as e:
            print(f"  [!] Timeout/Erro ao acessar {anime_url} (Tentativa {r_try}/3): {e}")
            time.sleep(r_try * 3)

    if not html:
        print(f"  [❌ ERRO] Não foi possível carregar a página de '{anime_title}'.")
        return False

    # Extrai metadados completos da página (título canônico, sinopse real, poster, backdrop e data)
    meta = extract_page_metadata(html, anime_url, anime_title)
    anime_title = meta["title"]
    is_movie = meta["is_movie"]
    original_title = meta["original_title"]

    print(f"\n================================================================")
    print(f"{'🎬 [FILME]' if is_movie else '📺 [ANIME]'} {anime_title}")
    print(f"   URL: {anime_url}")
    if meta.get("overview"):
        print(f"   Sinopse: {meta['overview'][:100]}...")
    if meta.get("poster_path"):
        print(f"   Poster: {meta['poster_path']}")
    print(f"================================================================")

    # Extrai Post ID do WordPress
    post_id_match = re.search(r'data-postid=[\'"](\d+)[\'"]|data-id=[\'"](\d+)[\'"]|data-post=[\'"](\d+)[\'"]', html)
    wp_post_id = post_id_match.group(1) or post_id_match.group(2) or post_id_match.group(3) if post_id_match else None

    # 1. Resolve TMDB ID com separação estrita de filme e metadados reais
    tmdb_id = resolve_tmdb(anime_title, original_title=original_title, wp_post_id=wp_post_id, is_movie=is_movie, meta=meta)

    # 2. Extrai episódios
    episodes = parse_post_episodes(anime_url, html)
    if not episodes:
        print(f"  [-] Nenhum episódio detectado para '{anime_title}'.")
        return False

    total_eps = len(episodes)
    print(f"  📋 Total de episódios catalogados no AnimeQ: {total_eps}")

    # 3. Checa episódios já existentes no Supabase e Google Drive
    existing_eps = get_existing_episodes_set(tmdb_id)
    missing = [ep for ep in episodes if (ep['season_num'], ep['ep_num']) not in existing_eps]

    if not missing:
        print(f"  [✓ 100% COMPLETO] Todos os {total_eps} episódios de '{anime_title}' já estão no Google Drive e Supabase.")
        return True

    print(f"  📊 Status atual: {total_eps - len(missing)}/{total_eps} episódios já no Drive. Faltam {len(missing)} episódio(s).")
    print(f"  🚀 Iniciando ingestão sequencial de '{anime_title}'...")

    clean_anime_slug = re.sub(r'[^a-zA-Z0-9]+', '-', anime_title).strip('-').lower()
    dead_urls_cache = set()

    # Até 2 rodadas dedicadas a este anime
    for anime_round in range(1, 3):
        existing_eps = get_existing_episodes_set(tmdb_id)
        pending = [ep for ep in episodes if (ep['season_num'], ep['ep_num']) not in existing_eps]

        if not pending:
            break

        if anime_round > 1:
            print(f"\n  🔄 [RODADA DE RETENTATIVA {anime_round}/2] Re-tentando {len(pending)} episódios pendentes de '{anime_title}'...")

        for p_idx, ep_item in enumerate(pending, 1):
            s_num = ep_item["season_num"]
            e_num = ep_item["ep_num"]
            ep_title = ep_item["ep_title"]
            ep_page_url = ep_item["ep_url"]

            print(f"\n    ▶ [{p_idx}/{len(pending)}] Ingerindo T{s_num:02d}E{e_num:02d} — {ep_title}...")

            slug = f"{clean_anime_slug}-filme" if ep_item["is_movie"] else f"{clean_anime_slug}-s{s_num:02d}e{e_num:02d}"

            candidates = extract_stream_urls(ep_page_url)

            success = False
            for attempt in range(1, 3):
                try:
                    if process_episode_candidates(candidates, tmdb_id, s_num, e_num, slug, mode=mode, dead_urls=dead_urls_cache, is_movie=is_movie, custom_meta=meta):
                        existing_eps.add((s_num, e_num))
                        success = True
                        break
                    else:
                        if attempt < 2:
                            print(f"      [!] [Tentativa {attempt}/2] Falha na ingestão. Verificando alternativas...")
                            time.sleep(2)
                except Exception as ep_err:
                    print(f"      [-] [Tentativa {attempt}/2] Erro no episódio: {ep_err}")
                    time.sleep(2)

            if not success:
                print(f"      [❌ ERRO] Não foi possível completar T{s_num:02d}E{e_num:02d}.")

            time.sleep(1)

    # Verificação Final
    final_existing = get_existing_episodes_set(tmdb_id)
    final_pending = [ep for ep in episodes if (ep['season_num'], ep['ep_num']) not in final_existing]

    if not final_pending:
        print(f"\n  [✓ SUCESSO TOTAL] '{anime_title}' 100% CONCLUÍDO ({total_eps}/{total_eps} episódios)!")
        return True
    else:
        print(f"\n  [⚠️ ATENÇÃO] '{anime_title}' finalizou com {len(final_pending)}/{total_eps} episódios pendentes.")
        
        # Se NENHUM episódio deste anime/filme foi concluído, remove o registro do Supabase
        # para nunca deixar animes fantasmas ou vazios no banco
        if not final_existing:
            print(f"  [🧹 LIMPEZA AUTOMÁTICA] Nenhum episódio de '{anime_title}' pôde ser baixado. Purgando registro vazio do Supabase...")
            try:
                requests.delete(
                    f"{SUPABASE_URL}/rest/v1/animes?tmdb_id=eq.{tmdb_id}",
                    headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
                    timeout=10
                )
                print(f"  [✓] Registro de '{anime_title}' removido com sucesso do Supabase.")
            except Exception as del_err:
                print(f"  [-] Erro ao limpar registro do Supabase: {del_err}")

        return False

def crawl_section(section_name: str, start_page: int = 1, max_pages: int = 3, mode: str = "direct", strict: bool = False) -> bool:
    """
    Percorre as páginas de uma seção específica do AnimeQ.cloud e ingere todos os animes.
    """
    sec_base_url = SECTION_URLS.get(section_name)
    if not sec_base_url:
        print(f"[-] Seção '{section_name}' desconhecida.")
        return False

    print(f"\n================================================================")
    print(f"🌐 [SEÇÃO: {section_name.upper()}] {sec_base_url} (Páginas {start_page} a {start_page + max_pages - 1})")
    print(f"================================================================\n")

    for page in range(start_page, start_page + max_pages):
        page_url = sec_base_url if page == 1 else f"{sec_base_url}/page/{page}"
        print(f"\n📄 [PÁGINA {page}] Acessando {page_url}...")

        html = None
        for try_p in range(1, 4):
            try:
                r = session.get(page_url, timeout=45)
                if r.status_code == 200:
                    html = r.text
                    break
                print(f"  [!] HTTP {r.status_code} na página {page} (Tentativa {try_p}/3)")
                time.sleep(try_p * 3)
            except Exception as e:
                print(f"  [!] Erro de conexão na página {page} (Tentativa {try_p}/3): {e}")
                time.sleep(try_p * 3)

        if not html:
            print(f"[-] Falha ao obter conteúdo da página {page}. Pulando...")
            continue

        # Extração limpa dos cards via BeautifulSoup ou fallback granular por article
        items = []
        if BeautifulSoup:
            soup = BeautifulSoup(html, "html.parser")
            # Seleciona artigos do catálogo principal excluindo barra lateral/recomendações
            for art in soup.select("#archive-content article, .animation-2 article, .content .items article, article.item"):
                if art.find_parent("aside") or art.find_parent(class_="sidebar"):
                    continue
                a_tag = art.find("a", href=True)
                if not a_tag:
                    continue
                href = a_tag["href"]

                # Filtro estrito: se a seção for 'filme', aceita SOMENTE /filme/
                if section_name == "filme" and "/filme/" not in href:
                    continue
                if section_name == "anime" and "/anime/" not in href:
                    continue
                if not ("/anime/" in href or "/filme/" in href):
                    continue
                
                t_tag = art.select_one(".data h3, .data .title, h3, .title")
                title = t_tag.get_text(strip=True) if t_tag else (a_tag.get("title") or "")
                if not title:
                    img = art.find("img", alt=True)
                    title = img["alt"] if img else ""

                clean_title = (
                    title.replace("&acute;", "´")
                    .replace("&ccedil;", "ç")
                    .replace("&atilde;", "ã")
                    .replace("&eacute;", "é")
                    .replace("&ocirc;", "ô")
                    .strip()
                )

                full_href = href if href.startswith("http") else f"{BASE_URL}{href}"
                if clean_title and not any(full_href == it[0] for it in items):
                    items.append((full_href, clean_title))
        else:
            main_html = html.split('<aside')[0] if '<aside' in html else html
            for art_block in re.findall(r'<article[^>]*>.*?</article>', main_html, re.DOTALL | re.IGNORECASE):
                m_href = re.search(r'href=["\']([^"\']*(?:/anime/|/filme/)[^"\']*)["\']', art_block)
                if not m_href:
                    continue
                href = m_href.group(1)
                if section_name == "filme" and "/filme/" not in href:
                    continue
                if section_name == "anime" and "/anime/" not in href:
                    continue
                m_title = (
                    re.search(r'<(?:h3|span)[^>]*class=["\'][^"\']*(?:title|data)[^"\']*["\'][^>]*>(.*?)</(?:h3|span)>', art_block, re.DOTALL | re.IGNORECASE)
                    or re.search(r'<h3[^>]*>(.*?)</h3>', art_block, re.DOTALL | re.IGNORECASE)
                    or re.search(r'title=["\']([^"\']+)["\']', art_block)
                    or re.search(r'alt=["\']([^"\']+)["\']', art_block)
                )
                if m_title:
                    raw_title = re.sub(r'<[^>]+>', '', m_title.group(1)).strip()
                    clean_title = (
                        raw_title.replace("&acute;", "´")
                        .replace("&ccedil;", "ç")
                        .replace("&atilde;", "ã")
                        .replace("&eacute;", "é")
                        .replace("&ocirc;", "ô")
                        .strip()
                    )
                    full_href = href if href.startswith("http") else f"{BASE_URL}{href}"
                    if clean_title and not any(full_href == it[0] for it in items):
                        items.append((full_href, clean_title))

        if not items:
            print(f"[-] Nenhum título encontrado na página {page}.")
            break

        print(f"[+] {len(items)} títulos encontrados na página {page}.\n")

        for idx, (item_url, item_title) in enumerate(items, 1):
            print(f"\n--- [Item {idx}/{len(items)} da Página {page}] ---")
            ok = harvest_anime(item_url, item_title, mode=mode, strict=strict)
            if not ok and strict:
                print(f"  [⛔ BLOQUEIO DE SEGURANÇA ESTRITO] Interrompendo execução para impedir avanços com falha.")
                return False

    return True

def repair_incomplete_animes(mode: str = "direct"):
    """
    Audita o Supabase em busca de animes com episódios faltando
    e colhe todos os episódios e temporadas pendentes no AnimeQ até 100% de conclusão.
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
        tmdb_id = anime.get("tmdb_id")
        title = anime.get("title", "")
        print(f"\n================================================================")
        print(f"⚡ [REPARANDO {idx}/{len(incomplete_list)}] {title} (TMDB {tmdb_id})")
        print(f"   Status: {uploaded_eps}/{total_eps} episódios no Drive (Faltam {missing} episódios)")
        print(f"================================================================")

        clean_slug = re.sub(r'[^a-zA-Z0-9]+', '-', title).strip('-').lower()
        candidate_urls = [
            f"{BASE_URL}/anime/{clean_slug}",
            f"{BASE_URL}/filme/{clean_slug}"
        ]

        found_url = None
        for curl in candidate_urls:
            try:
                res = session.head(curl, timeout=15)
                if res.status_code == 200:
                    found_url = curl
                    break
            except Exception:
                pass

        if not found_url:
            print(f"   [-] Não foi possível resolver URL direta para '{title}' ({candidate_urls[0]}).")
            continue

        harvest_anime(found_url, title, mode=mode, strict=False)

def main():
    parser = argparse.ArgumentParser(description="Anata Stream — AnimeQ Harvester & Repair")
    parser.add_argument("--action", choices=["all", "repair", "crawl"], default="all",
                        help="Ação a executar: repair (reparar banco), crawl (varrer catálogo), all (ambos)")
    parser.add_argument("--section", choices=["all", "filme", "hentai", "dublado", "legendado", "anime"], default="all",
                        help="Seção do AnimeQ a varrer: filme, hentai, dublado, legendado, anime ou all")
    parser.add_argument("--mode", choices=["direct", "dispatch"], default="direct",
                        help="Modo de processamento: direct (no próprio runner) ou dispatch (GitHub Actions)")
    parser.add_argument("--start", type=int, default=1, help="Página inicial")
    parser.add_argument("--pages", type=int, default=3, help="Total de páginas por seção")
    parser.add_argument("--strict", action="store_true", help="Ativa interrupção imediata da varredura caso um anime falhe")

    args = parser.parse_args()

    print("================================================================")
    print(f"  ANATA STREAM — ANIME-Q HARVESTER")
    print(f"  AÇÃO: {args.action.upper()} | SEÇÃO: {args.section.upper()} | MODO: {args.mode.upper()}")
    print("================================================================")

    if not check_supabase_health():
        sys.exit(1)

    if args.action in ["all", "repair"]:
        repair_incomplete_animes(mode=args.mode)

    if args.action in ["all", "crawl"]:
        sections_to_crawl = ["filme", "hentai", "dublado", "legendado"] if args.section == "all" else [args.section]
        for sec in sections_to_crawl:
            ok = crawl_section(sec, start_page=args.start, max_pages=args.pages, mode=args.mode, strict=args.strict)
            if not ok and args.strict:
                print(f"[!] Execução interrompida na seção {sec} devido ao bloqueio estrito.")
                sys.exit(1)

    print("\n[✓] Execução do AnimeQ Harvester concluída com sucesso!")

if __name__ == "__main__":
    main()
