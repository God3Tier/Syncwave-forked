use crate::schema::songs;
use chrono::{DateTime, Utc};
use diesel::{Queryable, Selectable};
use uuid::Uuid;

/// The Catalogue song row fields used by Streaming, mapped to the shared Song contract.
#[derive(Debug, Queryable, Selectable)]
#[diesel(table_name = songs)]
#[diesel(check_for_backend(diesel::pg::Pg))]
pub struct Song {
    pub song_id: Uuid,
    pub title: String,
    pub artist: String,
    pub duration_ms: i64,
    pub audio_reference: String,
    pub lyrics_status: String,
    pub waveform_status: String,
    pub processing_status: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}
