CREATE TABLE IF NOT EXISTS songs (
    song_id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    duration_ms BIGINT NOT NULL CHECK (duration_ms >= 0),
    audio_reference TEXT NOT NULL UNIQUE,
    lyrics_status TEXT NOT NULL CHECK (lyrics_status IN ('PENDING', 'PROCESSING', 'READY', 'FAILED')),
    waveform_status TEXT NOT NULL CHECK (waveform_status IN ('PENDING', 'PROCESSING', 'READY', 'FAILED')),
    processing_status TEXT NOT NULL CHECK (processing_status IN ('PROCESSING', 'PARTIAL', 'READY', 'FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
