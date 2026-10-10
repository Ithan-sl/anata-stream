/**
 * Cloudflare Worker: Anime Gateway & Custom Streaming Player
 * Rotas:
 *  - GET /api/anime/:tmdb_id  -> Retorna dados e episódios
 *  - GET /player/:episode_id  -> Renderiza o player Plyr em tela cheia (embeddable)
 *  - GET /stream/:gdrive_id   -> Proxy com suporte a Range requests para stream contínuo
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS Headers
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
      "Access-Control-Allow-Headers": "Range, Content-Type",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // 1. Rota de Embed do Player
    if (path.startsWith("/player/")) {
      const episodeId = path.split("/")[2];
      return handlePlayerView(episodeId, env, url.origin);
    }

    // 2. Rota de Stream com suporte a Range (Google Drive Direct / Proxy)
    if (path.startsWith("/stream/")) {
      const gdriveId = path.split("/")[2];
      return handleStreamProxy(gdriveId, request, env);
    }

    // 3. API de Metadados de Episódios
    if (path.startsWith("/api/anime/")) {
      const tmdbId = path.split("/")[3];
      return handleAnimeMetadata(tmdbId, env, corsHeaders);
    }

    return new Response("Not Found", { status: 404 });
  }
};

async function handlePlayerView(episodeId, env, origin) {
  // Busca metadados da fonte no Supabase
  const supabaseUrl = env.SUPABASE_URL;
  const supabaseKey = env.SUPABASE_ANON_KEY;

  const res = await fetch(`${supabaseUrl}/rest/v1/media_sources?episode_id=eq.${episodeId}&select=*,episodes(name,episode_number,seasons(season_number,animes(title)))`, {
    headers: {
      "apikey": supabaseKey,
      "Authorization": `Bearer ${supabaseKey}`
    }
  });

  const sources = await res.json();
  if (!sources || sources.length === 0) {
    return new Response("<h1>Episódio sem mídia disponível.</h1>", {
      status: 404,
      headers: { "Content-Type": "text/html; charset=utf-8" }
    });
  }

  const media = sources[0];
  const streamUrl = `${origin}/stream/${media.gdrive_file_id}`;
  const epInfo = media.episodes || {};
  const animeTitle = epInfo.seasons?.animes?.title || "Anime";
  const epTitle = `T${epInfo.seasons?.season_number || 1}:E${epInfo.episode_number || 1} - ${epInfo.name || ''}`;

  const html = `<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${animeTitle} - ${epTitle}</title>
  <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
  <style>
    * { box-sizing: border-box; }
    html, body {
      margin: 0; padding: 0;
      width: 100%; height: 100%;
      background: #0b0c10;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .player-container {
      width: 100%; height: 100%;
      display: flex; align-items: center; justify-content: center;
    }
    .plyr {
      width: 100%; height: 100%;
      --plyr-color-main: #45f3ff;
    }
    .info-overlay {
      position: absolute; top: 16px; left: 16px;
      color: #fff; text-shadow: 0 2px 4px rgba(0,0,0,0.8);
      z-index: 10; pointer-events: none;
    }
    .info-overlay h1 { font-size: 1.1rem; margin: 0; font-weight: 600; }
    .info-overlay p { font-size: 0.85rem; margin: 4px 0 0; opacity: 0.8; }
  </style>
</head>
<body>
  <div class="info-overlay">
    <h1>${animeTitle}</h1>
    <p>${epTitle}</p>
  </div>
  <div class="player-container">
    <video id="player" playsinline controls>
      <source src="${streamUrl}" type="video/mp4">
    </video>
  </div>

  <script src="https://cdn.plyr.io/3.7.8/plyr.polyfilled.js"></script>
  <script>
    const player = new Plyr('#player', {
      controls: [
        'play-large', 'play', 'progress', 'current-time', 'duration',
        'mute', 'volume', 'captions', 'settings', 'pip', 'airplay', 'fullscreen'
      ],
      keyboard: { focused: true, global: true },
      seekTime: 10
    });
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

async function handleStreamProxy(gdriveId, request, env) {
  // Constrói requisição direta para o endpoint de export/download do Drive com API Key
  const apiKey = env.GOOGLE_DRIVE_API_KEY;
  const driveUrl = `https://www.googleapis.com/drive/v3/files/${gdriveId}?alt=media&key=${apiKey}`;

  // Encaminha os cabeçalhos de Range para permitir Seek no player
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

async function handleAnimeMetadata(tmdbId, env, corsHeaders) {
  const supabaseUrl = env.SUPABASE_URL;
  const supabaseKey = env.SUPABASE_ANON_KEY;

  const res = await fetch(`${supabaseUrl}/rest/v1/animes?tmdb_id=eq.${tmdbId}&select=*,seasons(*,episodes(*,media_sources(*)))`, {
    headers: {
      "apikey": supabaseKey,
      "Authorization": `Bearer ${supabaseKey}`
    }
  });

  const data = await res.json();
  return new Response(JSON.stringify(data), {
    headers: {
      ...corsHeaders,
      "Content-Type": "application/json"
    }
  });
}
