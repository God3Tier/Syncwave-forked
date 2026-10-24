diesel::table! {
    songs (song_id) {
        song_id -> Uuid,
        title -> Text,
        artist -> Text,
        duration_ms -> Int8,
        audio_reference -> Text,
        lyrics_status -> Text,
        waveform_status -> Text,
        processing_status -> Text,
        created_at -> Timestamptz,
        updated_at -> Timestamptz,
    }
}
