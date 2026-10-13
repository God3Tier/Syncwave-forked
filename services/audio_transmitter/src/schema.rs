diesel::table! {
    music_metadata (id) {
        id -> Int4,
        song_name -> Text,
        timestamp -> Int8,
    }
}
