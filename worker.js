/**
 * Cloudflare Worker: Portal Completo de Streaming e Pesquisa de Animes
 * Recursos:
 *  - Interface Web (SPA) responsiva estilo Netflix/Crunchyroll
 *  - Busca em tempo real por título no catálogo
 *  - Seletor organizado por Temporadas e Episódios
 *  - Player moderno (Plyr) com busca rápida (Seek / RFC 7233 Range)
 *  - Proxy de streaming do Google Drive
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

    // 1. Interface Web Principal (Home / Catálogo / Player)
    if (path === "/" || path === "/index.html") {
      return handleFrontend(url.origin);
    }

    // 2. API de Catálogo Inicial (Últimos Animes Atualizados)
    if (path === "/api/catalog") {
      return handleCatalog(env, corsHeaders);
    }

    // 3. API de Busca
    if (path.startsWith("/api/search")) {
      const query = url.searchParams.get("q") || "";
      return handleSearch(query, env, corsHeaders);
    }

    // 4. API de Detalhes do Anime e Episódios Estruturados
    if (path.startsWith("/api/anime/")) {
      const tmdbId = path.split("/")[3];
      return handleAnimeDetails(tmdbId, env, corsHeaders);
    }

    // 5. Proxy de Streaming com suporte a Range (Seek rápido)
    if (path.startsWith("/stream/")) {
      const gdriveId = path.split("/")[2];
      return handleStreamProxy(gdriveId, request, env);
    }

    return new Response("Not Found", { status: 404 });
  }
};

/* ================= FRONTEND WEB COMPLETO (SPA) ================= */
function handleFrontend(origin) {
  const html = `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Anata Stream — Catálogo de Animes</title>
  <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090a0f;
      --card-bg: #13151f;
      --card-hover: #1c1f2e;
      --accent: #6366f1;
      --accent-hover: #4f46e5;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --border: #232738;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: 'Inter', sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      padding: 1.25rem 2rem;
      background: rgba(9, 10, 15, 0.85);
      backdrop-filter: blur(12px);
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
      font-size: 1.4rem;
      font-weight: 800;
      letter-spacing: -0.5px;
      color: #fff;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .logo span { color: var(--accent); }
    .search-box {
      flex: 1;
      max-width: 480px;
      position: relative;
    }
    .search-box input {
      width: 100%;
      padding: 0.65rem 1rem 0.65rem 2.5rem;
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
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
    }
    .search-icon {
      position: absolute;
      left: 0.85rem;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 0.9rem;
    }
    main {
      flex: 1;
      padding: 2rem;
      max-width: 1400px;
      margin: 0 auto;
      width: 100%;
    }
    h2.section-title {
      font-size: 1.3rem;
      font-weight: 700;
      margin-bottom: 1.5rem;
      color: #fff;
    }
    .anime-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 1.5rem;
    }
    .anime-card {
      background: var(--card-bg);
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid var(--border);
      cursor: pointer;
      transition: transform 0.2s, box-shadow 0.2s;
      position: relative;
    }
    .anime-card:hover {
      transform: translateY(-4px);
      box-shadow: 0 10px 20px rgba(0, 0, 0, 0.5);
      border-color: var(--accent);
    }
    .poster-wrapper {
      position: relative;
      width: 100%;
      padding-top: 145%;
      background: #1a1c26;
    }
    .poster-wrapper img {
      position: absolute;
      top: 0; left: 0;
      width: 100%; height: 100%;
      object-fit: cover;
    }
    .card-info { padding: 0.85rem; }
    .card-title {
      font-size: 0.95rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .card-meta {
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 0.35rem;
      display: flex;
      justify-content: space-between;
    }
    /* Modal / Viewer de Episódios */
    .modal {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.88);
      backdrop-filter: blur(8px);
      z-index: 100;
      overflow-y: auto;
      padding: 2rem 1rem;
    }
    .modal.active { display: flex; align-items: center; justify-content: center; }
    .modal-content {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      width: 100%;
      max-width: 900px;
      max-height: 90vh;
      overflow-y: auto;
      position: relative;
      padding: 2rem;
    }
    .close-btn {
      position: absolute;
      top: 1.25rem; right: 1.25rem;
      background: var(--border);
      color: #fff;
      border: none;
      border-radius: 50%;
      width: 36px; height: 36px;
      cursor: pointer;
      font-size: 1.2rem;
      display: flex; align-items: center; justify-content: center;
      transition: background 0.2s;
    }
    .close-btn:hover { background: var(--accent); }
    .player-area {
      width: 100%;
      border-radius: 8px;
      overflow: hidden;
      background: #000;
      margin-bottom: 1.5rem;
    }
    .season-tabs {
      display: flex;
      gap: 0.5rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.75rem;
      margin-bottom: 1rem;
      overflow-x: auto;
    }
    .season-tab {
      padding: 0.5rem 1rem;
      background: var(--card-hover);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text);
      cursor: pointer;
      font-size: 0.85rem;
      white-space: nowrap;
    }
    .season-tab.active {
      background: var(--accent);
      border-color: var(--accent);
      font-weight: 600;
    }
    .episodes-list {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 0.75rem;
    }
    .episode-card {
      padding: 0.75rem;
      background: #0f111a;
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .episode-card:hover, .episode-card.active {
      border-color: var(--accent);
      background: #191c2b;
    }
    .episode-title { font-size: 0.85rem; font-weight: 600; margin-bottom: 0.25rem; }
    .episode-number { font-size: 0.75rem; color: var(--accent); font-weight: 700; }
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
    <h2 class="section-title" id="gridTitle">Todos os Animes Catalogados</h2>
    <div class="anime-grid" id="animeGrid"></div>
  </main>

  <!-- Modal do Player e Episódios -->
  <div class="modal" id="playerModal">
    <div class="modal-content">
      <button class="close-btn" onclick="closeModal()">✕</button>
      
      <div class="player-area" id="playerArea">
        <video id="videoPlayer" playsinline controls></video>
      </div>

      <h2 id="modalAnimeTitle" style="margin-bottom: 0.5rem;">Anime Title</h2>
      <p id="modalEpisodeTitle" style="color: var(--text-muted); margin-bottom: 1.5rem; font-size: 0.9rem;">Episódio</p>

      <div class="season-tabs" id="seasonTabs"></div>
      <div class="episodes-list" id="episodesList"></div>
    </div>
  </div>

  <script src="https://cdn.plyr.io/3.7.8/plyr.polyfilled.js"></script>
  <script>
    let player = new Plyr('#videoPlayer', {
      controls: ['play-large', 'play', 'progress', 'current-time', 'duration', 'mute', 'volume', 'captions', 'settings', 'pip', 'airplay', 'fullscreen'],
      seekTime: 10
    });

    let activeAnimeData = null;

    async function loadCatalog() {
      const res = await fetch('/api/catalog');
      const data = await res.json();
      renderAnimeGrid(data);
    }

    function renderAnimeGrid(animes) {
      const grid = document.getElementById('animeGrid');
      grid.innerHTML = '';
      if (!animes || animes.length === 0) {
        grid.innerHTML = '<p style="color: var(--text-muted);">Nenhum anime cadastrado no momento.</p>';
        return;
      }
      animes.forEach(a => {
        const card = document.createElement('div');
        card.className = 'anime-card';
        const posterUrl = a.poster_path ? 'https://image.tmdb.org/t/p/w500' + a.poster_path : 'https://via.placeholder.com/300x450/13151f/94a3b8?text=Sem+Capa';
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

      eps.forEach((ep, idx) => {
        const epCard = document.createElement('div');
        epCard.className = 'episode-card';
        const hasSource = ep.media_sources && ep.media_sources.length > 0;
        epCard.innerHTML = \`
          <div class="episode-number">EPISÓDIO \${ep.episode_number} \${hasSource ? '⚡ Disponível' : '⏳ Aguardando'}</div>
          <div class="episode-title">\${ep.name || 'Episódio ' + ep.episode_number}</div>
        \`;
        if (hasSource) {
          epCard.onclick = () => playEpisode(ep, season);
        } else {
          epCard.style.opacity = '0.5';
          epCard.style.cursor = 'not-allowed';
        }
        epList.appendChild(epCard);
      });

      // Dá auto-play no primeiro com mídia se houver
      const firstAvailable = eps.find(e => e.media_sources && e.media_sources.length > 0);
      if (firstAvailable) {
        playEpisode(firstAvailable, season);
      }
    }

    function playEpisode(ep, season) {
      const source = ep.media_sources[0];
      const streamUrl = '/stream/' + source.gdrive_file_id;
      document.getElementById('modalEpisodeTitle').innerText = 'Temporada ' + season.season_number + ' • Episódio ' + ep.episode_number + ' - ' + (ep.name || '');

      player.source = {
        type: 'video',
        sources: [{ src: streamUrl, type: 'video/mp4' }]
      };
      player.play();
    }

    function closeModal() {
      player.stop();
      document.getElementById('playerModal').classList.remove('active');
    }

    // Busca com Debounce
    let searchTimeout = null;
    document.getElementById('searchInput').addEventListener('input', (e) => {
      clearTimeout(searchTimeout);
      const query = e.target.value.trim();
      searchTimeout = setTimeout(async () => {
        if (!query) {
          document.getElementById('gridTitle').innerText = 'Todos os Animes Catalogados';
          loadCatalog();
          return;
        }
        document.getElementById('gridTitle').innerText = 'Resultados para "' + query + '"';
        const res = await fetch('/api/search?q=' + encodeURIComponent(query));
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

/* ================= PROXY DE STREAMING GOOGLE DRIVE COM SEEK ================= */

async function handleStreamProxy(gdriveId, request, env) {
  const apiKey = env.GOOGLE_DRIVE_API_KEY;
  // Endpoint de mídia do Google Drive com chave de API
  const driveUrl = apiKey
    ? `https://www.googleapis.com/drive/v3/files/${gdriveId}?alt=media&key=${apiKey}`
    : `https://drive.google.com/uc?export=download&id=${gdriveId}`;

  const clientRange = request.headers.get("Range");
  const headers = new Headers();
  if (clientRange) {
    headers.set("Range", clientRange);
  }

  const driveRes = await fetch(driveUrl, { headers });

  const responseHeaders = new Headers(driveRes.headers);
  responseHeaders.set("Access-Control-Allow-Origin", "*");
  responseHeaders.set("Access-Control-Allow-Headers", "Range");
  responseHeaders.set("Accept-Ranges", "bytes");

  return new Response(driveRes.body, {
    status: driveRes.status,
    headers: responseHeaders
  });
}
