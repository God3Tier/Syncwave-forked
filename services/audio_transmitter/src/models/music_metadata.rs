use crate::schema::music_metadata;
use diesel::{Insertable, Queryable, Selectable};

/// A song's database record. `timestamp` is Unix time in seconds.
#[derive(Debug, Queryable, Selectable)]
#[diesel(table_name = music_metadata)]
#[diesel(check_for_backend(diesel::pg::Pg))]
pub struct MusicMetadata {
    pub id: i32,
    pub song_name: String,
    pub timestamp: i64,
}

/// Values used when adding a song. Omitting `timestamp` lets PostgreSQL use
/// the current time by default.
#[derive(Insertable)]
#[diesel(table_name = music_metadata)]
pub struct NewMusicMetadata<'a> {
    pub song_name: &'a str,
    pub timestamp: Option<i64>,
}
