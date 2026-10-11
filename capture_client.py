#!/usr/bin/env python3
"""
capture_client.py — Cliente Inteligente de Captura, Filtragem e Ingestão de Animes
Integração: Smart Play Lite -> Filtro Anime (TMDB) -> Disparo Automático GitHub Actions / Google Drive
"""

import os
import sys
import json
import re
import requests
import subprocess
from PyQt6.QtCore import Qt, QUrl, QThread, pyqtSignal
from PyQt6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QStatusBar,
)

# Constantes do Tráfego do App
URL_INICIAL = "https://smartplayliteapk.net/"
USER_AGENT_APP = (
    "Mozilla/5.0 (Linux; Android 10; NEN-LX1 Build/HUAWEINEN-LX1; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/83.0.4103.106 Mobile Safari/537.36"
)
PACKAGE_NAME = b"com.visionvibes2v2.trailer"
APP_VERSION = "smart-play-lite-apk-1.4"
EXOPLAYER_UA = "KlPlayerView/smart-play-lite-apk-1.4 (Linux;Android 10) ExoPlayerLib/2.16.1"

# Credenciais e Endpoints
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")
GITHUB_REPO = "Ithan-sl/anata-stream"
TMDB_TOKEN = os.environ.get(
    "TMDB_READ_ACCESS_TOKEN",
    "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI5YzMxYjNhZWIyZTU5YWEyY2FmNzRjNzQ1Y2UxNTg4NyIsIm5iZiI6MTc2NjA3MTQ0MC40MDMsInN1YiI6IjY5NDQxYzkwNjRhOWQ4N2RiYzcwNTZlNiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.Pa2-x5hvsHeepw5f70ffBGX9L-4AaU7NBYtp8qSTQDA"
)

JS_BRIDGE_MOCK = f"""
Object.defineProperty(window, 'RoboTemplatesWebViewApp', {{
    value: {{
        getVersionName: function() {{
            return "{APP_VERSION}";
        }}
    }},
    writable: false,
    configurable: false
}});

Object.defineProperty(window, 'WebApp', {{
    value: {{
        onPlayersCallback: function(dados) {{
            var str = typeof dados === 'string' ? dados : JSON.stringify(dados);
            console.log("PLAY_STREAM:::" + str);
        }}
    }},
    writable: false,
    configurable: false
}});
"""

def extract_season_episode(titulo: str):
    """Extrai número da temporada e episódio a partir do título."""
    # Padrão: T01 E02, S01E02, Temporada 1 Episodio 2, etc.
    s_match = re.search(r'(?:temp(?:orada)?|s|t)\s*[-:]?\s*(\d+)', titulo, re.IGNORECASE)
    e_match = re.search(r'(?:ep(?:isodio)?|e)\s*[-:]?\s*(\d+)', titulo, re.IGNORECASE)

    season = int(s_match.group(1)) if s_match else 1
    episode = int(e_match.group(1)) if e_match else 1

    # Remove padrões de episódio/temporada do título para buscar o nome limpo no TMDB
    clean_title = re.sub(r'(?:temp(?:orada)?|s|t)\s*[-:]?\s*\d+', '', titulo, flags=re.IGNORECASE)
    clean_title = re.sub(r'(?:ep(?:isodio)?|e)\s*[-:]?\s*\d+', '', clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r'[\(\)\[\]\-]+', ' ', clean_title).strip()

    return clean_title, season, episode

class IngestionWorker(QThread):
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, raw_title: str, video_url: str):
        super().__init__()
        self.raw_title = raw_title
        self.video_url = video_url

    def run(self):
        clean_title, season_num, ep_num = extract_season_episode(self.raw_title)
        self.status_signal.emit(f"🔍 Consultando TMDB: '{clean_title}'...")

        # 1. Busca no TMDB
        tmdb_url = "https://api.themoviedb.org/3/search/tv"
        headers = {
            "Authorization": f"Bearer {TMDB_TOKEN}",
            "Accept": "application/json"
        }
        params = {"query": clean_title, "language": "pt-BR"}

        try:
            r = requests.get(tmdb_url, headers=headers, params=params, timeout=10)
            data = r.json()
            results = data.get("results", [])

            if not results:
                self.finished_signal.emit(False, f"Título '{clean_title}' não encontrado no TMDB.")
                return

            anime = None
            for item in results:
                genres = item.get("genre_ids", [])
                origin_country = item.get("origin_country", [])

                # FILTRO ESTRITO DE ANIME: Animação (16) + Origem Japão ('JP')
                is_animation = 16 in genres
                is_japanese = "JP" in origin_country

                if is_animation or is_japanese:
                    anime = item
                    break

            if not anime:
                self.finished_signal.emit(False, f"'{clean_title}' NÃO é anime (Filtrado: Apenas animes permitidos).")
                return

            tmdb_id = anime["id"]
            anime_name = anime.get("name", clean_title)
            title_slug = f"{re.sub(r'[^a-zA-Z0-9]+', '-', anime_name).strip('-').lower()}-s{season_num:02d}e{ep_num:02d}"

            self.status_signal.emit(f"⚡ Anime Validado: {anime_name} (TMDB {tmdb_id}) | T{season_num:02d}E{ep_num:02d}")
            self.status_signal.emit("🚀 Disparando GitHub Actions para upload no Google Drive...")

            # 2. Dispara Workflow no GitHub Actions
            dispatch_url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/ingest_stream.yml/dispatches"
            gh_headers = {
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            payload = {
                "ref": "main",
                "inputs": {
                    "stream_url": self.video_url,
                    "tmdb_id": str(tmdb_id),
                    "season_number": str(season_num),
                    "episode_number": str(ep_num),
                    "title_slug": title_slug
                }
            }

            dispatch_res = requests.post(dispatch_url, headers=gh_headers, json=payload, timeout=10)
            if dispatch_res.status_code == 204:
                self.finished_signal.emit(
                    True,
                    f"Sucesso! {anime_name} - T{season_num}E{ep_num} enviado para a fila do GitHub Actions -> Google Drive!"
                )
            else:
                self.finished_signal.emit(False, f"Falha ao acionar GitHub: {dispatch_res.status_code} {dispatch_res.text}")

        except Exception as err:
            self.finished_signal.emit(False, f"Erro no processamento: {str(err)}")

class IntercetorRequisicoes(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        info.setHttpHeader(b"X-Requested-With", PACKAGE_NAME)
        info.setHttpHeader(b"Accept-Language", b"pt-PT,pt;q=0.9,en;q=0.8")

class CustomWebPage(QWebEnginePage):
    def __init__(self, profile, parent=None, callback_stream=None):
        super().__init__(profile, parent)
        self.callback_stream = callback_stream

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message.startswith("PLAY_STREAM:::"):
            dados_brutos = message.replace("PLAY_STREAM:::", "")
            if self.callback_stream:
                self.callback_stream(dados_brutos)
        else:
            super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

class JanelaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Play Anime Harvester — Linux")
        self.resize(480, 880)

        self.worker = None

        # Container Central
        central_widget = QWidget()
        self.layout = QVBoxLayout(central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Barra de Status do Pipeline
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Aguardando seleção de anime no aplicativo...")

        # Perfil Web e Injeção
        self.perfil = QWebEngineProfile.defaultProfile()
        self.perfil.setHttpUserAgent(USER_AGENT_APP)

        self.intercetor = IntercetorRequisicoes()
        self.perfil.setUrlRequestInterceptor(self.intercetor)

        script = QWebEngineScript()
        script.setName("AndroidBridgeMock")
        script.setSourceCode(JS_BRIDGE_MOCK)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        self.perfil.scripts().insert(script)

        # Navegador
        self.navegador = QWebEngineView()
        self.pagina = CustomWebPage(self.perfil, self.navegador, self.on_stream_captured)
        self.navegador.setPage(self.pagina)
        self.navegador.load(QUrl(URL_INICIAL))

        self.layout.addWidget(self.navegador)
        self.setCentralWidget(central_widget)

    def on_stream_captured(self, dados_json: str):
        try:
            dados = json.loads(dados_json)
            if not dados.get("success") or not dados.get("players"):
                self.status_bar.showMessage("[-] Nenhum leitor ativo retornado para este item.")
                return

            player = dados["players"][0]
            url_video = player.get("file")
            titulo = dados.get("title", "Anime")

            self.status_bar.showMessage(f"Capturado: {titulo}. Validando filtro de anime...")

            # Opcional: abre player nativo mpv em background para preview se desejado
            # subprocess.Popen(["mpv", f"--user-agent={EXOPLAYER_UA}", "--force-window=immediate", url_video])

            # Dispara thread assíncrona de validação TMDB e envio para o GitHub Actions
            self.worker = IngestionWorker(titulo, url_video)
            self.worker.status_signal.connect(self.update_status)
            self.worker.finished_signal.connect(self.on_worker_finished)
            self.worker.start()

        except Exception as e:
            self.status_bar.showMessage(f"[-] Erro ao decodificar JSON: {e}")

    def update_status(self, msg: str):
        self.status_bar.showMessage(msg)

    def on_worker_finished(self, success: bool, msg: str):
        self.status_bar.showMessage(msg)
        if success:
            QMessageBox.information(self, "Pipeline Concluído", msg)
        else:
            QMessageBox.warning(self, "Filtro / Erro", msg)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Back or (
            event.key() == Qt.Key.Key_Left and event.modifiers() == Qt.KeyboardModifier.AltModifier
        ):
            if self.navegador.history().canGoBack():
                self.navegador.back()
                return
        super().keyPressEvent(event)

def main():
    app = QApplication(sys.argv)
    janela = JanelaPrincipal()
    janela.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
