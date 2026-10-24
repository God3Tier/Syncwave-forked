-- Preserve existing audio records while replacing the legacy integer/timestamp
-- record shape with the shared UUID Song contract. Existing S3 keys were the
-- integer ID, so retain that object reference for migrated rows.
DO $$
BEGIN
    IF to_regclass('public.music_metadata') IS NOT NULL THEN
        INSERT INTO songs (
            song_id, title, artist, duration_ms, audio_reference,
            lyrics_status, waveform_status, processing_status, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), song_name, 'Unknown', timestamp * 1000, id::text,
            'PENDING', 'PENDING', 'PROCESSING', to_timestamp(timestamp), to_timestamp(timestamp)
        FROM music_metadata
        ON CONFLICT (audio_reference) DO NOTHING;

        DROP TABLE music_metadata;
    END IF;
END $$;
