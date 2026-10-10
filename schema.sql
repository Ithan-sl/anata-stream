-- Schema Supabase: Catálogo de Animes e Mídias Remotas
-- Dialeto: PostgreSQL (Supabase)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Animes
CREATE TABLE IF NOT EXISTS animes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tmdb_id INTEGER UNIQUE NOT NULL,
    imdb_id TEXT,
    title TEXT NOT NULL,
    original_title TEXT,
    overview TEXT,
    poster_path TEXT,
    backdrop_path TEXT,
    first_air_date DATE,
    status TEXT,
    genres JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Temporadas
CREATE TABLE IF NOT EXISTS seasons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    anime_id UUID NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
    tmdb_id INTEGER,
    season_number INTEGER NOT NULL,
    name TEXT,
    overview TEXT,
    poster_path TEXT,
    episode_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (anime_id, season_number)
);

-- 3. Episódios
CREATE TABLE IF NOT EXISTS episodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    season_id UUID NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    episode_number INTEGER NOT NULL,
    name TEXT,
    overview TEXT,
    still_path TEXT,
    tmdb_id INTEGER,
    air_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (season_id, episode_number)
);

-- 4. Fontes de Mídia (Google Drive)
CREATE TABLE IF NOT EXISTS media_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    storage_provider TEXT NOT NULL DEFAULT 'gdrive',
    gdrive_file_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    mime_type TEXT DEFAULT 'video/mp4',
    file_size BIGINT,
    duration_seconds INTEGER,
    resolution TEXT DEFAULT '1080p',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para buscas em alta velocidade
CREATE INDEX IF NOT EXISTS idx_animes_tmdb_id ON animes(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_seasons_anime_id ON seasons(anime_id);
CREATE INDEX IF NOT EXISTS idx_episodes_season_id ON episodes(season_id);
CREATE INDEX IF NOT EXISTS idx_media_sources_episode_id ON media_sources(episode_id);
