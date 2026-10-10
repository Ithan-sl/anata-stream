/**
 * Cloudflare Worker: Anata Stream Portal com JW Player & Google Drive Stream Proxy
 * Recursos:
 *  - Player JW Player 8 mobile-first com aceleração por hardware e seek avançado
 *  - Proxy de streaming direto do Google Drive com bypass de aviso de vírus (&confirm=t)
 *  - Suporte completo a cabeçalhos RFC 7233 (Range: bytes=) para avanço/retrocesso instantâneo
 *  - Busca em tempo real e catálogo de animes
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
      "Access-Control-Allow-Headers": "Range, Content-Type",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // 1. Interface Web Principal
    if (path === "/" || path === "/index.html") {
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

    // 5. Proxy de Streaming Google Drive com bypass de vírus e Range HTTP
    if (path.startsWith("/stream/")) {
      const gdriveId = path.split("/")[2];
      return handleStreamProxy(gdriveId, request);
    }

    return new Response("Not Found", { status: 404 });
  }
};

/* ================= FRONTEND WEB COM JW PLAYER ================= */
function handleFrontend(origin) {
  const html = `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Anata Stream — JW Player Anime Portal</title>
  <!-- JW Player 8 Core & Skin -->
  <script src="https://ssl.p.jwpcdn.com/player/v/8.26.2/jwplayer.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #07080c;
      --card-bg: #11131c;
      --card-hover: #181b29;
      --accent: #e11d48;
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
      padding: 1rem 1.5rem;
      background: rgba(7, 8, 12, 0.9);
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
    }
    .logo span { color: var(--accent); }
    .search-box {
      flex: 1;
      max-width: 440px;
      position: relative;
    }
    .search-box input {
      width: 100%;
      padding: 0.65rem 1rem 0.65rem 2.4rem;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 9999px;
      color: #fff;
      font-size: 0.9rem;
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
    main {
      flex: 1;
      padding: 1.5rem;
      max-width: 1400px;
      margin: 0 auto;
      width: 100%;
    }
    h2.section-title {
      font-size: 1.25rem;
      font-weight: 700;
      margin-bottom: 1.25rem;
      color: #fff;
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
      main { padding: 1rem; }
    }
    .anime-card {
      background: var(--card-bg);
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid var(--border);
      cursor: pointer;
      transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
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
    .card-info { padding: 0.75rem; }
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
      margin-top: 0.3rem;
      display: flex;
      justify-content: space-between;
    }
    /* Modal / Viewer */
    .modal {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.92);
      backdrop-filter: blur(10px);
      z-index: 100;
      overflow-y: auto;
      padding: 1rem;
    }
    .modal.active { display: flex; align-items: center; justify-content: center; }
    .modal-content {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      width: 100%;
      max-width: 950px;
      max-height: 94vh;
      overflow-y: auto;
      position: relative;
      padding: 1.5rem;
    }
    @media (max-width: 640px) {
      .modal { padding: 0; }
      .modal-content {
        max-height: 100vh;
        height: 100vh;
        border-radius: 0;
        padding: 1rem;
      }
    }
    .close-btn {
      position: absolute;
      top: 1rem; right: 1rem;
      background: var(--border);
      color: #fff;
      border: none;
      border-radius: 50%;
      width: 36px; height: 36px;
      cursor: pointer;
      font-size: 1.1rem;
      display: flex; align-items: center; justify-content: center;
      z-index: 20;
    }
    .close-btn:hover { background: var(--accent); }
    .player-area {
      width: 100%;
      aspect-ratio: 16 / 9;
      background: #000;
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 1.25rem;
    }
    #jwplayer-container { width: 100%; height: 100%; }
    .season-tabs {
      display: flex;
      gap: 0.5rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.75rem;
      margin-bottom: 1rem;
      overflow-x: auto;
    }
    .season-tab {
      padding: 0.45rem 0.9rem;
      background: var(--card-hover);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text);
      cursor: pointer;
      font-size: 0.82rem;
      white-space: nowrap;
    }
    .season-tab.active {
      background: var(--accent);
      border-color: var(--accent);
      font-weight: 700;
    }
    .episodes-list {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 0.65rem;
    }
    .episode-card {
      padding: 0.75rem;
      background: #0a0c12;
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .episode-card:hover, .episode-card.active {
      border-color: var(--accent);
      background: #151824;
    }
    .episode-title { font-size: 0.82rem; font-weight: 600; margin-bottom: 0.2rem; }
    .episode-number { font-size: 0.72rem; color: var(--accent); font-weight: 700; }
  </style>
</head>
<body>
  <header>
    <div class="logo">ANATA <span>STREAM</span></div>
    <div class="search-box">
      <span class="search-icon">🔍</span>
      <input type="text" id="searchInput" placeholder="Pesquisar anime..." />
    </div>
  </header>

  <main>
    <h2 class="section-title" id="gridTitle">Catálogo de Animes (Google Drive)</h2>
    <div class="anime-grid" id="animeGrid"></div>
  </main>

  <!-- Modal do Player e Episódios -->
  <div class="modal" id="playerModal">
    <div class="modal-content">
      <button class="close-btn" onclick="closeModal()">✕</button>
      
      <div class="player-area">
        <div id="jwplayer-container"></div>
      </div>

      <h2 id="modalAnimeTitle" style="margin-bottom: 0.4rem; font-size: 1.2rem;">Anime</h2>
      <p id="modalEpisodeTitle" style="color: var(--text-muted); margin-bottom: 1.25rem; font-size: 0.85rem;">Episódio</p>

      <div class="season-tabs" id="seasonTabs"></div>
      <div class="episodes-list" id="episodesList"></div>
    </div>
  </div>

  <script>
    let playerInstance = null;
    let activeAnimeData = null;

    function initJWPlayer(streamUrl, title) {
      if (!playerInstance) {
        playerInstance = jwplayer("jwplayer-container").setup({
          file: streamUrl,
          title: title,
          width: "100%",
          height: "100%",
          autostart: true,
          preload: "auto",
          controls: true,
          playbackRateControls: [0.75, 1, 1.25, 1.5, 2],
          skin: {
            controlbar: { iconsActive: "#e11d48" },
            timeslider: { progress: "#e11d48" }
          }
        });
      } else {
        playerInstance.load([{ file: streamUrl, title: title }]);
        playerInstance.play();
      }
    }

    async function loadCatalog() {
      const res = await fetch('/api/catalog');
      const data = await res.json();
      renderAnimeGrid(data);
    }

    function renderAnimeGrid(animes) {
      const grid = document.getElementById('animeGrid');
      grid.innerHTML = '';
      if (!animes || animes.length === 0) {
        grid.innerHTML = '<p style="color: var(--text-muted); grid-column: 1/-1;">Nenhum anime cadastrado no momento.</p>';
        return;
      }
      animes.forEach(a => {
        const card = document.createElement('div');
        card.className = 'anime-card';
        const posterUrl = a.poster_path ? 'https://image.tmdb.org/t/p/w500' + a.poster_path : 'https://via.placeholder.com/300x450/11131c/94a3b8?text=Sem+Capa';
        card.innerHTML = \`
          <div class="poster-wrapper">
            <img src="\${posterUrl}" alt="\${a.title}" loading="lazy" />
          </div>
          <div class="card-info">
            <div class="card-title">\${a.title}</div>
            <div class="card-meta">
              <span>\${a.first_air_date ? a.first_air_date.substring(0,4) : 'Anime'}</span>
              <span>TMDB #\${a.tmdb_id}</span>
            </div>
          </div>
        \`;
        card.onclick = () => openAnimeDetails(a.tmdb_id);
        grid.appendChild(card);
      });
    }

    async function openAnimeDetails(tmdbId) {
      const res = await fetch('/api/anime/' + tmdbId);
      const anime = await res.json();
      activeAnimeData = anime;

      document.getElementById('modalAnimeTitle').innerText = anime.title;
      renderSeasons(anime);
      document.getElementById('playerModal').classList.add('active');
    }

    function renderSeasons(anime) {
      const tabs = document.getElementById('seasonTabs');
      tabs.innerHTML = '';
      const seasons = anime.seasons || [];
      seasons.sort((a,b) => a.season_number - b.season_number);

      seasons.forEach((s, idx) => {
        const tab = document.createElement('button');
        tab.className = 'season-tab ' + (idx === 0 ? 'active' : '');
        tab.innerText = 'Temporada ' + s.season_number;
        tab.onclick = () => {
          document.querySelectorAll('.season-tab').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
          renderEpisodes(s);
        };
        tabs.appendChild(tab);
      });

      if (seasons.length > 0) {
        renderEpisodes(seasons[0]);
      }
    }

    function renderEpisodes(season) {
      const epList = document.getElementById('episodesList');
      epList.innerHTML = '';
      const eps = season.episodes || [];
      eps.sort((a,b) => a.episode_number - b.episode_number);

      eps.forEach((ep) => {
        const epCard = document.createElement('div');
        epCard.className = 'episode-card';
        const hasSource = ep.media_sources && ep.media_sources.length > 0;
        epCard.innerHTML = \`
          <div class="episode-number">EPISÓDIO \${ep.episode_number} \${hasSource ? '⚡ DISPONÍVEL' : '⏳ AGUARDANDO'}</div>
          <div class="episode-title">\${ep.name || 'Episódio ' + ep.episode_number}</div>
        \`;
        if (hasSource) {
          epCard.onclick = () => playEpisode(ep, season);
        } else {
          epCard.style.opacity = '0.4';
          epCard.style.cursor = 'not-allowed';
        }
        epList.appendChild(epCard);
      });

      // Toca o primeiro disponível
      const firstAvailable = eps.find(e => e.media_sources && e.media_sources.length > 0);
      if (firstAvailable) {
        playEpisode(firstAvailable, season);
      }
    }

    function playEpisode(ep, season) {
      const source = ep.media_sources[0];
      const streamUrl = '/stream/' + source.gdrive_file_id;
      const title = 'T' + season.season_number + 'E' + ep.episode_number + ' - ' + (ep.name || '');
      document.getElementById('modalEpisodeTitle').innerText = title;
      initJWPlayer(streamUrl, title);
    }

    function closeModal() {
      if (playerInstance) {
        playerInstance.stop();
      }
      document.getElementById('playerModal').classList.remove('active');
    }

    let searchTimeout = null;
    document.getElementById('searchInput').addEventListener('input', (e) => {
      clearTimeout(searchTimeout);
      const q = e.target.value.trim();
      searchTimeout = setTimeout(async () => {
        if (!q) {
          document.getElementById('gridTitle').innerText = 'Catálogo de Animes (Google Drive)';
          loadCatalog();
          return;
        }
        document.getElementById('gridTitle').innerText = 'Resultados para "' + q + '"';
        const res = await fetch('/api/search?q=' + encodeURIComponent(q));
        const data = await res.json();
        renderAnimeGrid(data);
      }, 300);
    });

    loadCatalog();
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
  const res = await fetch(`${env.SUPABASE_URL}/rest/v1/animes?select=*&order=created_at.desc&limit=50`, {
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
  const res = await fetch(`${env.SUPABASE_URL}/rest/v1/animes?title=ilike.*${encodeURIComponent(query)}*&select=*&limit=30`, {
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
  // O link com &confirm=t desvia do aviso de verificação de vírus para arquivos >100MB
  const targetUrl = `https://drive.usercontent.google.com/download?id=${gdriveId}&export=download&confirm=t`;

  const clientRange = request.headers.get("Range");
  const fetchHeaders = new Headers({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*"
  });

  if (clientRange) {
    fetchHeaders.set("Range", clientRange);
  }

  const driveRes = await fetch(targetUrl, {
    method: "GET",
    headers: fetchHeaders,
    redirect: "follow"
  });

  const responseHeaders = new Headers();
  responseHeaders.set("Access-Control-Allow-Origin", "*");
  responseHeaders.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
  responseHeaders.set("Access-Control-Allow-Headers", "Range");
  responseHeaders.set("Content-Type", driveRes.headers.get("Content-Type") || "video/mp4");
  
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
