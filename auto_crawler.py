#!/usr/bin/env python3
"""
auto_crawler.py — Rastreador e Disparador em Lote de Animes
Varre o catálogo de animes do Smart Play Lite de forma ordenada (T01E01 -> T01E02...),
valida cada item no TMDB e enfileira os downloads no GitHub Actions.
"""

import os
import sys
import json
import time
import re
import requests
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow

URL_ANIMES = "https://smartplayliteapk.net/animes"
USER_AGENT_APP = (
    "Mozilla/5.0 (Linux; Android 10; NEN-LX1 Build/HUAWEINEN-LX1; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/83.0.4103.106 Mobile Safari/537.36"
)
PACKAGE_NAME = b"com.visionvibes2v2.trailer"
APP_VERSION = "smart-play-lite-apk-1.4"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Ithan-sl/anata-stream")
TMDB_TOKEN = os.environ.get("TMDB_READ_ACCESS_TOKEN")

JS_HOOKS = f"""
Object.defineProperty(window, 'RoboTemplatesWebViewApp', {{
    value: {{ getVersionName: function() {{ return "{APP_VERSION}"; }} }},
    writable: false, configurable: false
}});

Object.defineProperty(window, 'WebApp', {{
    value: {{
        onPlayersCallback: function(dados) {{
            var str = typeof dados === 'string' ? dados : JSON.stringify(dados);
            console.log("AUTO_STREAM:::" + str);
        }}
    }},
    writable: false, configurable: false
}});
"""

class Interceptor(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        info.setHttpHeader(b"X-Requested-With", PACKAGE_NAME)
        info.setHttpHeader(b"Accept-Language", b"pt-PT,pt;q=0.9,en;q=0.8")

class AutoCrawlerPage(QWebEnginePage):
    def __init__(self, profile, parent=None, callback=None):
        super().__init__(profile, parent)
        self.callback = callback

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message.startswith("AUTO_STREAM:::"):
            dados_brutos = message.replace("AUTO_STREAM:::", "")
            if self.callback:
                self.callback(dados_brutos)
        else:
            super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

class CrawlerEngine(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Anata Auto Crawler — Headless Ingestor")
        self.resize(500, 800)

        self.queue = []
        self.current_item = None

        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpUserAgent(USER_AGENT_APP)

        self.interceptor = Interceptor()
        profile.setUrlRequestInterceptor(self.interceptor)

        script = QWebEngineScript()
        script.setName("AutoHooks")
        script.setSourceCode(JS_HOOKS)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        profile.scripts().insert(script)

        self.view = QWebEngineView()
        self.page = AutoCrawlerPage(profile, self.view, self.on_stream_intercepted)
        self.view.setPage(self.page)
        self.setCentralWidget(self.view)

        # Inicia carregamento
        self.view.load(QUrl(URL_ANIMES))

    def on_stream_intercepted(self, dados_json: str):
        try:
            dados = json.loads(dados_json)
            if not dados.get("players"):
                return
            url_video = dados["players"][0].get("file")
            titulo = dados.get("title", "Anime")
            print(f"[CRAWLER] Fluxo detectado: {titulo}")
            self.dispatch_to_github(titulo, url_video)
        except Exception as e:
            print(f"[-] Erro ao processar stream: {e}")

    def dispatch_to_github(self, raw_title: str, video_url: str):
        # Extrai temporada e episódio
        s_match = re.search(r'(?:temp|s|t)\s*[-:]?\s*(\d+)', raw_title, re.IGNORECASE)
        e_match = re.search(r'(?:ep|e)\s*[-:]?\s*(\d+)', raw_title, re.IGNORECASE)
        season = int(s_match.group(1)) if s_match else 1
        episode = int(e_match.group(1)) if e_match else 1

        clean = re.sub(r'(?:temp|s|t)\s*[-:]?\s*\d+', '', raw_title, flags=re.IGNORECASE)
        clean = re.sub(r'(?:ep|e)\s*[-:]?\s*\d+', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'[\(\)\[\]\-]+', ' ', clean).strip()

        # Validação TMDB
        headers = {"Authorization": f"Bearer {TMDB_TOKEN}", "Accept": "application/json"}
        res = requests.get("https://api.themoviedb.org/3/search/tv", headers=headers, params={"query": clean, "language": "pt-BR"})
        data = res.json()
        results = data.get("results", [])

        anime = None
        for a in results:
            if 16 in a.get("genre_ids", []) or "JP" in a.get("origin_country", []):
                anime = a
                break

        if not anime:
            print(f"[-] Ignorando '{clean}': Não classificado como anime no TMDB.")
            return

        tmdb_id = anime["id"]
        slug = f"{re.sub(r'[^a-zA-Z0-9]+', '-', anime['name']).strip('-').lower()}-s{season:02d}e{episode:02d}"

        print(f"[+] DISPARANDO: {anime['name']} | T{season:02d}E{episode:02d} (TMDB {tmdb_id})")

        # Disparo GitHub Actions
        gh_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/ingest_stream.yml/dispatches"
        gh_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        payload = {
            "ref": "main",
            "inputs": {
                "stream_url": video_url,
                "tmdb_id": str(tmdb_id),
                "season_number": str(season),
                "episode_number": str(episode),
                "title_slug": slug
            }
        }
        r = requests.post(gh_url, headers=gh_headers, json=payload)
        if r.status_code == 204:
            print(f"[✓] Enfileirado com sucesso no GitHub Actions: {slug}")
        else:
            print(f"[-] Erro ao enfileirar: {r.status_code} {r.text}")

def main():
    app = QApplication(sys.argv)
    engine = CrawlerEngine()
    engine.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
