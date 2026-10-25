/**
 * Cloudflare Worker: Anata Stream Portal — Interface de Reprodução Dedicada (Cinema Mode)
 * Recursos:
 *  - Diferenciação visual e estrutural entre FILMES e SÉRIES (Badges, controles e player ajustados)
 *  - Player ArtPlayer com modo cinema, iluminação ambiente e suporte a mobile
 *  - Proxy Google Drive com Range HTTP, auto-resolução do token 'uuid' contra aviso de vírus de arquivos >100MB
 *  - Suporte a reprodução direta de stream mesmo enquanto o Google Drive processa o vídeo
 *  - Botão de link direto para download / player externo (VLC / navegador nativo)
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
      "Access-Control-Allow-Headers": "Range, Content-Type, Accept-Ranges",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // 1. Interface Web Principal (SPA)
    if (path === "/" || path === "/index.html" || path.startsWith("/watch")) {
      return handleFrontend(url.origin);
    }

    // 2. Catálogo Inicial
    if (path === "/api/catalog") {
      return handleCatalog(env, corsHeaders);
    }

    // 3. Busca de Animes
    if (path.startsWith("/api/search")) {
      const query = url.searchParams.get("q") || "";
      return handleSearch(query, env, corsHeaders);
    }

    // 4. Detalhes do Anime e Episódios
    if (path.startsWith("/api/anime/")) {
      const tmdbId = path.split("/")[3];
      return handleAnimeDetails(tmdbId, env, corsHeaders);
    }

    // 5. Proxy de Streaming com Range & Bypass de Vírus
    if (path.startsWith("/stream/")) {
      const gdriveId = path.split("/")[2];
      return handleStreamProxy(gdriveId, request);
    }

    return new Response("Not Found", { status: 404 });
  }
};

/* ================= FRONTEND WEB COMPLETO (CINEMA MODE) ================= */
function handleFrontend(origin) {
  const html = `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Anata Stream — Portal de Animes e Filmes</title>
  <!-- ArtPlayer Engine (Open-Source, Mobile-First) -->
  <script src="https://cdn.jsdelivr.net/npm/artplayer/dist/artplayer.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #07080c;
      --card-bg: #11131c;
      --card-hover: #181b29;
      --accent: #e11d48;
      --accent-hover: #be123c;
      --accent-glow: rgba(225, 29, 72, 0.35);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --border: #1e2235;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      padding: 0.85rem 1.5rem;
      background: rgba(7, 8, 12, 0.95);
      backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 50;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
    }
    .logo {
      font-size: 1.35rem;
      font-weight: 800;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 0.4rem;
      letter-spacing: -0.5px;
      cursor: pointer;
    }
    .logo span { color: var(--accent); }
    .search-box {
      flex: 1;
      max-width: 440px;
      position: relative;
    }
    .search-box input {
      width: 100%;
      padding: 0.6rem 1rem 0.6rem 2.4rem;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 9999px;
      color: #fff;
      font-size: 0.88rem;
      outline: none;
      transition: all 0.2s;
    }
    .search-box input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }
    .search-icon {
      position: absolute;
      left: 0.85rem;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 0.85rem;
    }

    /* BADGES */
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
      font-size: 0.68rem;
      font-weight: 700;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }
    .badge-movie {
      background: rgba(245, 158, 11, 0.2);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.4);
    }
    .badge-series {
      background: rgba(225, 29, 72, 0.2);
      color: #fb7185;
      border: 1px solid rgba(225, 29, 72, 0.4);
    }
    .badge-hentai {
      background: rgba(168, 85, 247, 0.2);
      color: #c084fc;
      border: 1px solid rgba(168, 85, 247, 0.4);
    }

    /* === VISTA 1: CATÁLOGO DE ANIMES E FILMES === */
    #catalogView {
      padding: 1.5rem;
      max-width: 1400px;
      margin: 0 auto;
      width: 100%;
      flex: 1;
    }
    h2.section-title {
      font-size: 1.25rem;
      font-weight: 700;
      margin-bottom: 1.25rem;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .anime-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 1.25rem;
    }
    @media (max-width: 640px) {
      .anime-grid {
        grid-template-columns: repeat(auto-fill, minmax(135px, 1fr));
        gap: 0.85rem;
      }
      #catalogView { padding: 1rem; }
    }
    .anime-card {
      background: var(--card-bg);
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid var(--border);
      cursor: pointer;
      transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
      display: flex;
      flex-direction: column;
    }
    .anime-card:hover {
      transform: translateY(-4px);
      box-shadow: 0 12px 24px rgba(0, 0, 0, 0.6);
      border-color: var(--accent);
    }
    .poster-wrapper {
      position: relative;
      width: 100%;
      padding-top: 145%;
      background: #141724;
    }
    .poster-wrapper img {
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      object-fit: cover;
    }
    .card-info { padding: 0.75rem; flex: 1; display: flex; flex-direction: column; justify-content: space-between; }
    .card-title {
      font-size: 0.88rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .card-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 0.4rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    /* === VISTA 2: TELA DEDICADA DE REPRODUÇÃO (CINEMA MODE) === */
    #watchView {
      display: none;
      flex: 1;
      width: 100%;
      max-width: 1500px;
      margin: 0 auto;
      padding: 1rem 1.5rem 3rem;
    }
    .watch-nav {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 1rem;
    }
    .back-btn {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.5rem 1rem;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 600;
      transition: all 0.2s;
    }
    .back-btn:hover {
      background: var(--card-hover);
      border-color: var(--accent);
    }
    .theater-container {
      width: 100%;
      background: #000;
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--border);
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8);
      aspect-ratio: 16 / 9;
      max-height: 75vh;
      margin-bottom: 1.25rem;
    }
    #artplayer-container { width: 100%; height: 100%; }
    
    .watch-details {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1.5rem;
      margin-bottom: 1.25rem;
      flex-wrap: wrap;
    }
    .anime-headline h1 {
      font-size: 1.35rem;
      font-weight: 800;
      color: #fff;
    }
    .anime-headline p {
      font-size: 0.92rem;
      color: var(--accent);
      font-weight: 600;
      margin-top: 0.2rem;
    }
    .ep-nav-controls {
      display: flex;
      gap: 0.5rem;
    }
    .nav-ep-btn {
      padding: 0.55rem 1.1rem;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: #fff;
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      transition: all 0.2s;
    }
    .nav-ep-btn:hover:not(:disabled) {
      background: var(--accent);
      border-color: var(--accent);
    }
    .nav-ep-btn:disabled {
      opacity: 0.35;
      cursor: not-allowed;
    }

    .direct-download-btn {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.55rem 1rem;
      background: #1e2235;
      color: #f8fafc;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: 0.82rem;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      transition: all 0.2s;
    }
    .direct-download-btn:hover {
      background: var(--accent);
      border-color: var(--accent);
    }

    .season-tabs {
      display: flex;
      gap: 0.5rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.75rem;
      margin-bottom: 1.25rem;
      overflow-x: auto;
    }
    .season-tab {
      padding: 0.5rem 1rem;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 600;
      white-space: nowrap;
      transition: all 0.2s;
    }
    .season-tab.active {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    .episodes-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 0.75rem;
    }
    .ep-card {
      padding: 0.85rem;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.2s;
      position: relative;
    }
    .ep-card:hover {
      border-color: var(--accent);
      background: var(--card-hover);
    }
    .ep-card.playing {
      border-color: var(--accent);
      background: rgba(225, 29, 72, 0.12);
    }
    .ep-card.playing::after {
      content: 'REPRODUZINDO';
      position: absolute;
      top: 0.6rem; right: 0.6rem;
      font-size: 0.65rem;
      font-weight: 800;
      background: var(--accent);
      color: #fff;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .ep-card-tag {
      font-size: 0.75rem;
      color: var(--accent);
      font-weight: 700;
      margin-bottom: 0.25rem;
    }
    .ep-card-title {
      font-size: 0.85rem;
      font-weight: 600;
      color: #fff;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    @media (max-width: 768px) {
      .theater-container { border-radius: 0; margin-left: -1rem; margin-right: -1rem; width: calc(100% + 2rem); }
      #watchView { padding: 0.5rem 1rem 3rem; }
      .episodes-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
      .watch-details { flex-direction: column; align-items: flex-start; }
    }
  </style>
</head>
<body>
  <header>
    <div class="logo" onclick="navigateToCatalog()">ANATA <span>STREAM</span></div>
    <div class="search-box">
      <span class="search-icon">🔍</span>
      <input type="text" id="searchInput" placeholder="Pesquisar anime ou filme..." />
    </div>
  </header>

  <!-- 1. ABA DO CATÁLOGO GERAL -->
  <main id="catalogView">
    <h2 class="section-title">
      <span id="gridTitle">Catálogo de Conteúdos (Google Drive)</span>
    </h2>
    <div class="anime-grid" id="animeGrid"></div>
  </main>

  <!-- 2. ABA DEDICADA DE REPRODUÇÃO (SALA DE CINEMA INDIVIDUAL) -->
  <main id="watchView">
    <div class="watch-nav">
      <button class="back-btn" onclick="navigateToCatalog()">
        ← Voltar ao Catálogo
      </button>
      <div class="ep-nav-controls" id="navControlsWrapper">
        <button class="nav-ep-btn" id="prevEpBtn" onclick="playAdjacentEpisode(-1)">
          ⏮ Anterior
        </button>
        <button class="nav-ep-btn" id="nextEpBtn" onclick="playAdjacentEpisode(1)">
          Próximo ⏭
        </button>
      </div>
    </div>

    <div class="theater-container">
      <div id="artplayer-container"></div>
    </div>

    <div id="playerBufferNotice" style="display:none; margin-bottom:1.25rem; padding:0.85rem 1.1rem; background:rgba(245, 158, 11, 0.12); border:1px solid rgba(245, 158, 11, 0.4); border-radius:8px; font-size:0.85rem; color:#fef3c7;">
      ⚡ <strong>Aviso de Streaming:</strong> O Google Drive ainda está gerando o transcode de pré-visualização deste vídeo. Você pode assistir ou abrir imediatamente via link direto de download: 
      <a id="playerDirectLinkNotice" target="_blank" style="color:#38bdf8; text-decoration:underline; font-weight:bold; margin-left:6px;" href="#">Abrir Stream Acelerado</a>
    </div>

    <div class="watch-details">
      <div class="anime-headline">
        <div style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">
          <span id="watchTypeBadge" class="badge badge-series">📺 SÉRIE</span>
          <h1 id="watchAnimeTitle">Nome do Anime</h1>
        </div>
        <p id="watchEpisodeHeadline">Temporada 1 • Episódio 1</p>
      </div>
      <div>
        <a id="directStreamBtn" class="direct-download-btn" target="_blank" href="#">
          ⬇️ Link Direto (Download / Player Externo)
        </a>
      </div>
    </div>

    <div class="season-tabs" id="seasonTabs"></div>
    <div class="episodes-grid" id="episodesGrid"></div>
  </main>

  <script>
    let art = null;
    let currentAnime = null;
    let currentSeason = null;
    let currentEpisode = null;
    let currentEpisodesList = [];

    function isMovie(anime) {
      if (!anime) return false;
      if (anime.title && (anime.title.toLowerCase().includes('filme') || anime.title.toLowerCase().includes('movie'))) return true;
      if (anime.seasons && anime.seasons.length === 1) {
        const s = anime.seasons[0];
        if (s.name && (s.name.toLowerCase() === 'filme' || s.name.toLowerCase().includes('movie'))) return true;
      }
      return false;
    }

    // === INICIALIZAÇÃO E NAVEGAÇÃO ===
    async function initApp() {
      await loadCatalog();
      checkHashRoute();
      window.addEventListener('hashchange', checkHashRoute);
    }

    function checkHashRoute() {
      const hash = window.location.hash;
      if (hash.startsWith('#/watch/')) {
        const parts = hash.replace('#/watch/', '').split('/');
        const tmdbId = parts[0];
        const seasonNum = parseInt(parts[1] || '1');
        const epNum = parseInt(parts[2] || '1');
        openWatchView(tmdbId, seasonNum, epNum);
      } else {
        showCatalogView();
      }
    }

    function navigateToCatalog() {
      window.location.hash = '';
      showCatalogView();
    }

    function showCatalogView() {
      document.getElementById('catalogView').style.display = 'block';
      document.getElementById('watchView').style.display = 'none';
      if (art) { art.pause(); }
      document.title = 'Anata Stream — Portal de Animes e Filmes';
    }

    async function openWatchView(tmdbId, seasonNum, epNum) {
      document.getElementById('catalogView').style.display = 'none';
      document.getElementById('watchView').style.display = 'block';
      window.scrollTo({ top: 0, behavior: 'smooth' });

      const res = await fetch('/api/anime/' + tmdbId);
      const anime = await res.json();
      if (!anime) {
        alert('Conteúdo não encontrado no banco de dados.');
        navigateToCatalog();
        return;
      }

      currentAnime = anime;
      renderWatchView(anime, seasonNum, epNum);
    }

    function renderWatchView(anime, targetSeasonNum, targetEpNum) {
      const isFilm = isMovie(anime);
      document.getElementById('watchAnimeTitle').innerText = anime.title;

      const typeBadge = document.getElementById('watchTypeBadge');
      const navControls = document.getElementById('navControlsWrapper');
      const seasonTabs = document.getElementById('seasonTabs');

      if (isFilm) {
        typeBadge.className = 'badge badge-movie';
        typeBadge.innerText = '🎬 FILME';
        navControls.style.display = 'none';
        seasonTabs.style.display = 'none';
      } else if (anime.tmdb_id >= 900000000) {
        typeBadge.className = 'badge badge-hentai';
        typeBadge.innerText = '🔞 +18';
        navControls.style.display = 'flex';
        seasonTabs.style.display = 'flex';
      } else {
        typeBadge.className = 'badge badge-series';
        typeBadge.innerText = '📺 SÉRIE';
        navControls.style.display = 'flex';
        seasonTabs.style.display = 'flex';
      }

      const seasons = (anime.seasons || []).sort((a,b) => a.season_number - b.season_number);
      let selectedSeason = seasons.find(s => s.season_number === targetSeasonNum) || seasons[0] || { season_number: 1, episodes: [] };
      currentSeason = selectedSeason;

      seasonTabs.innerHTML = '';
      if (!isFilm) {
        seasons.forEach(s => {
          const btn = document.createElement('button');
          btn.className = 'season-tab ' + (s.season_number === selectedSeason.season_number ? 'active' : '');
          btn.innerText = s.name || ('Temporada ' + s.season_number);
          btn.onclick = () => {
            document.querySelectorAll('.season-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSeason = s;
            renderWatchEpisodes(s, 1);
          };
          seasonTabs.appendChild(btn);
        });
      }

      renderWatchEpisodes(selectedSeason, targetEpNum);
    }

    function renderWatchEpisodes(season, targetEpNum) {
      const grid = document.getElementById('episodesGrid');
      grid.innerHTML = '';
      const isFilm = isMovie(currentAnime);
      currentEpisodesList = (season.episodes || []).sort((a,b) => a.episode_number - b.episode_number);

      let targetEp = currentEpisodesList.find(e => e.episode_number === targetEpNum) || currentEpisodesList[0];

      currentEpisodesList.forEach(ep => {
        const card = document.createElement('div');
        const hasMedia = ep.media_sources && ep.media_sources.length > 0;
        const isCurrent = targetEp && ep.id === targetEp.id;

        card.className = 'ep-card ' + (isCurrent ? 'playing' : '');
        if (isFilm) {
          card.innerHTML = \`
            <div class="ep-card-tag">🎬 FILME \${hasMedia ? '⚡' : '⏳'}</div>
            <div class="ep-card-title">\${currentAnime.title}</div>
          \`;
        } else {
          card.innerHTML = \`
            <div class="ep-card-tag">EPISÓDIO \${ep.episode_number} \${hasMedia ? '⚡' : '⏳'}</div>
            <div class="ep-card-title">\${ep.name || 'Episódio ' + ep.episode_number}</div>
          \`;
        }

        if (hasMedia) {
          card.onclick = () => playEpisode(ep);
        } else {
          card.style.opacity = '0.35';
          card.style.cursor = 'not-allowed';
        }
        grid.appendChild(card);
      });

      if (targetEp && targetEp.media_sources && targetEp.media_sources.length > 0) {
        playEpisode(targetEp);
      }
    }

    // === REPRODUÇÃO NO ARTPLAYER ===
    function playEpisode(ep) {
      currentEpisode = ep;
      const media = ep.media_sources[0];
      const streamUrl = '/stream/' + media.gdrive_file_id + '/video.mp4';
      const isFilm = isMovie(currentAnime);
      const epLabel = isFilm 
        ? ('🎬 Filme Completo • ' + currentAnime.title) 
        : ('T' + currentSeason.season_number + 'E' + ep.episode_number + ' • ' + (ep.name || 'Episódio ' + ep.episode_number));
      
      document.getElementById('watchEpisodeHeadline').innerText = epLabel;
      document.title = currentAnime.title + ' — ' + epLabel;
      window.location.hash = '#/watch/' + currentAnime.tmdb_id + '/' + currentSeason.season_number + '/' + ep.episode_number;

      // Atualiza botões diretos
      const directBtn = document.getElementById('directStreamBtn');
      if (directBtn) { directBtn.href = streamUrl; }
      const directNoticeLink = document.getElementById('playerDirectLinkNotice');
      if (directNoticeLink) { directNoticeLink.href = streamUrl; }

      // Atualiza estado visual dos cards
      document.querySelectorAll('.ep-card').forEach(c => c.classList.remove('playing'));
      const activeIdx = currentEpisodesList.findIndex(e => e.id === ep.id);
      const cards = document.querySelectorAll('.ep-card');
      if (cards[activeIdx]) { cards[activeIdx].classList.add('playing'); }

      // Atualiza botões Anterior / Próximo
      if (!isFilm) {
        document.getElementById('prevEpBtn').disabled = (activeIdx <= 0);
        document.getElementById('nextEpBtn').disabled = (activeIdx >= currentEpisodesList.length - 1);
      }

      if (!art) {
        art = new Artplayer({
          container: '#artplayer-container',
          url: streamUrl,
          title: epLabel,
          type: 'mp4',
          volume: 0.8,
          autoplay: true,
          pip: true,
          autoSize: true,
          setting: true,
          loop: false,
          playbackRate: true,
          aspectRatio: true,
          fullscreen: true,
          fullscreenWeb: true,
          playsInline: true,
          airplay: true,
          fastForward: true,
          theme: '#e11d48',
          icons: {
            loading: '<span style="color:#e11d48;font-weight:bold;">Carregando stream...</span>'
          }
        });

        art.on('error', () => {
          const notice = document.getElementById('playerBufferNotice');
          if (notice) notice.style.display = 'block';
        });

        art.on('video:ended', () => {
          if (!isMovie(currentAnime)) {
            playAdjacentEpisode(1);
          }
        });
      } else {
        art.switchUrl(streamUrl, epLabel);
        art.play();
      }
    }

    function playAdjacentEpisode(delta) {
      if (!currentEpisodesList || currentEpisodesList.length === 0) return;
      const currentIdx = currentEpisodesList.findIndex(e => e.id === currentEpisode.id);
      const targetIdx = currentIdx + delta;
      if (targetIdx >= 0 && targetIdx < currentEpisodesList.length) {
        const nextEp = currentEpisodesList[targetIdx];
        if (nextEp.media_sources && nextEp.media_sources.length > 0) {
          playEpisode(nextEp);
        }
      }
    }

    // === CATÁLOGO E BUSCA ===
    async function loadCatalog() {
      const res = await fetch('/api/catalog');
      const data = await res.json();
      renderAnimeGrid(data);
    }

    function renderAnimeGrid(animes) {
      const grid = document.getElementById('animeGrid');
      grid.innerHTML = '';
      if (!animes || animes.length === 0) {
        grid.innerHTML = '<p style="color: var(--text-muted); grid-column: 1/-1;">Nenhum conteúdo cadastrado no momento.</p>';
        return;
      }
      animes.forEach(a => {
        const card = document.createElement('div');
        card.className = 'anime-card';
        const posterUrl = a.poster_path ? 'https://image.tmdb.org/t/p/w500' + a.poster_path : 'https://via.placeholder.com/300x450/11131c/94a3b8?text=Sem+Capa';
        
        const isFilm = isMovie(a);
        const isHentai = (a.title && a.title.toLowerCase().includes('hentai')) || (a.genres && JSON.stringify(a.genres).toLowerCase().includes('hentai')) || a.tmdb_id >= 900000000;
        const badgeHtml = isFilm 
          ? '<span class="badge badge-movie">🎬 FILME</span>'
          : (isHentai ? '<span class="badge badge-hentai">🔞 +18</span>' : '<span class="badge badge-series">📺 SÉRIE</span>');

        card.innerHTML = \`
          <div class="poster-wrapper">
            <img src="\${posterUrl}" alt="\${a.title}" loading="lazy" />
          </div>
          <div class="card-info">
            <div class="card-title">\${a.title}</div>
            <div class="card-meta">
              \${badgeHtml}
              <span>\${a.first_air_date ? a.first_air_date.substring(0,4) : ''}</span>
            </div>
          </div>
        \`;
        card.onclick = () => {
          window.location.hash = '#/watch/' + a.tmdb_id + '/1/1';
        };
        grid.appendChild(card);
      });
    }

    let searchTimeout = null;
    document.getElementById('searchInput').addEventListener('input', (e) => {
      clearTimeout(searchTimeout);
      const q = e.target.value.trim();
      searchTimeout = setTimeout(async () => {
        if (!q) {
          document.getElementById('gridTitle').innerText = 'Catálogo de Conteúdos (Google Drive)';
          loadCatalog();
          return;
        }
        document.getElementById('gridTitle').innerText = 'Resultados para "' + q + '"';
        const res = await fetch('/api/search?q=' + encodeURIComponent(q));
        const data = await res.json();
        renderAnimeGrid(data);
      }, 300);
    });

    initApp();
  </script>
</body>
</html>`;

  return new Response(html, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "X-Frame-Options": "ALLOWALL",
      "Access-Control-Allow-Origin": "*"
    }
  });
}

/* ================= APIs DO SUPABASE ================= */

async function handleCatalog(env, corsHeaders) {
  const res = await fetch(`${env.SUPABASE_URL}/rest/v1/animes?select=*,seasons(id,name,season_number,episode_count)&order=created_at.desc&limit=60`, {
    headers: {
      "apikey": env.SUPABASE_ANON_KEY,
      "Authorization": `Bearer ${env.SUPABASE_ANON_KEY}`
    }
  });
  const data = await res.json();
  return new Response(JSON.stringify(data), {
    headers: { ...corsHeaders, "Content-Type": "application/json" }
  });
}

async function handleSearch(query, env, corsHeaders) {
  const res = await fetch(`${env.SUPABASE_URL}/rest/v1/animes?title=ilike.*${encodeURIComponent(query)}*&select=*,seasons(id,name,season_number,episode_count)&limit=30`, {
    headers: {
      "apikey": env.SUPABASE_ANON_KEY,
      "Authorization": `Bearer ${env.SUPABASE_ANON_KEY}`
    }
  });
  const data = await res.json();
  return new Response(JSON.stringify(data), {
    headers: { ...corsHeaders, "Content-Type": "application/json" }
  });
}

async function handleAnimeDetails(tmdbId, env, corsHeaders) {
  const res = await fetch(`${env.SUPABASE_URL}/rest/v1/animes?tmdb_id=eq.${tmdbId}&select=*,seasons(*,episodes(*,media_sources(*)))`, {
    headers: {
      "apikey": env.SUPABASE_ANON_KEY,
      "Authorization": `Bearer ${env.SUPABASE_ANON_KEY}`
    }
  });
  const data = await res.json();
  const anime = (data && data.length > 0) ? data[0] : null;
  return new Response(JSON.stringify(anime), {
    headers: { ...corsHeaders, "Content-Type": "application/json" }
  });
}

/* ================= PROXY DE STREAMING GOOGLE DRIVE COM RANGE & BYPASS DE VÍRUS ================= */

async function handleStreamProxy(gdriveId, request) {
  const cleanId = gdriveId.replace(/\.mp4$/i, "").split("/")[0];
  const clientRange = request.headers.get("Range");

  const commonHeaders = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*"
  };

  // 1. Tenta obter o link de download direto resolvendo o token 'uuid' do Google Drive
  let downloadUrl = `https://drive.usercontent.google.com/download?id=${cleanId}&export=download&confirm=t`;

  try {
    const probeRes = await fetch(`https://drive.google.com/uc?export=download&id=${cleanId}`, {
      headers: commonHeaders,
      redirect: "follow"
    });

    const probeType = probeRes.headers.get("content-type") || "";
    // Se retornou página HTML de aviso de vírus (> 100MB), extrai o parâmetro uuid e confirm
    if (probeType.includes("text/html")) {
      const html = await probeRes.text();
      const uuidMatch = html.match(/name="uuid"\s+value="([^"]+)"/i) || html.match(/uuid=([a-f0-9-]+)/i);
      if (uuidMatch) {
        const uuid = uuidMatch[1];
        downloadUrl = `https://drive.usercontent.google.com/download?id=${cleanId}&export=download&confirm=t&uuid=${uuid}`;
      }
    } else if (probeType.includes("video") || probeType.includes("binary") || probeType.includes("octet-stream")) {
      downloadUrl = probeRes.url || downloadUrl;
    }
  } catch (err) {
    // Fallback silencioso para URL padrão com confirm=t
  }

  // 2. Requisição do stream com Range repassado
  const fetchHeaders = new Headers(commonHeaders);
  if (clientRange) {
    fetchHeaders.set("Range", clientRange);
  }

  const driveRes = await fetch(downloadUrl, {
    method: "GET",
    headers: fetchHeaders,
    redirect: "follow"
  });

  const responseHeaders = new Headers();
  responseHeaders.set("Access-Control-Allow-Origin", "*");
  responseHeaders.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
  responseHeaders.set("Access-Control-Allow-Headers", "Range, Content-Type, Accept-Ranges");
  responseHeaders.set("Content-Type", "video/mp4");
  responseHeaders.set("Content-Disposition", "inline; filename=\"video.mp4\"");

  if (driveRes.headers.has("Content-Length")) {
    responseHeaders.set("Content-Length", driveRes.headers.get("Content-Length"));
  }
  if (driveRes.headers.has("Content-Range")) {
    responseHeaders.set("Content-Range", driveRes.headers.get("Content-Range"));
  }
  if (driveRes.headers.has("Accept-Ranges")) {
    responseHeaders.set("Accept-Ranges", driveRes.headers.get("Accept-Ranges"));
  } else {
    responseHeaders.set("Accept-Ranges", "bytes");
  }

  return new Response(driveRes.body, {
    status: driveRes.status,
    headers: responseHeaders
  });
}
