# Anata Stream — Anime Harvester & Cloud Pipeline

Pipeline automatizado para catalogação de animes e animações (incluindo filmes e séries animadas como *Rick and Morty*), armazenamento no Google Drive (5TB) via Rclone, banco de dados Supabase e portal de streaming em tela cheia via Cloudflare Worker com ArtPlayer.

---

## ⚡ Recursos do Sistema

1. **Filtro Estrito de Animação (TMDB):**
   - **Permitido:** Todos os animes japoneses (séries e filmes), animações ocidentais adultas (Rick and Morty, Arcane, Castlevania, etc.) com gênero `16` (Animação) no TMDB.
   - **Bloqueado:** Filmes e séries normais com atores reais (Live-Action nunca sobem).

2. **Detecção Inteligente de Lacunas (Gap-Detection):**
   - Consulta o Supabase em tempo real.
   - Pula temporadas completas instantaneamente.
   - Se um anime estiver incompleto (ex: 8 de 12 episódios), detecta e baixa **somente os episódios faltantes**.
   - Zero arquivos ou registros duplicados.

3. **Trava de Segurança de 4 TB:**
   - Checagem automática do espaço ocupado no Google Drive antes de cada upload para manter folga no plano de 5 TB.

4. **Portal Web Dedicado (Cinema Mode):**
   - Hospedado no Cloudflare Worker (`worker.js`).
   - Engine **ArtPlayer** livre de licenças comerciais e bloqueios de domínio.
   - Controles mobile: toque duplo para pausar, segurar para 2x (como YouTube).
   - Roteamento SPA individual com URLs próprias por episódio (`/#/watch/:tmdb_id/:season/:ep`).

---

## 🚀 Como Executar

### 1. Ingestão 100% na Nuvem (Sem deixar o PC ligado)
Acesse a aba **Actions** deste repositório:
👉 **[Cloud Anime Harvester](https://github.com/Ithan-sl/anata-stream/actions/workflows/cloud_harvester.yml)**
1. Clique em **Run workflow**.
2. Escolha a página inicial e quantidade de páginas.
3. O GitHub Actions executará a colheita e o upload direto para o Google Drive.

### 2. Portal no Cloudflare Worker
1. Copie o arquivo [`worker.js`](worker.js).
2. Cole no painel da Cloudflare em **Edit code** do seu Worker e clique em **Deploy**.
3. Certifique-se de configurar as variáveis de ambiente:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
