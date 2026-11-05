use crate::{
    catalogue::{Catalogue, CatalogueError, SongInfo},
    store::audio::AudioStore,
};
use actix_web::{HttpResponse, Responder, web};
use serde::{Deserialize, Serialize};
use std::{
    collections::hash_map::DefaultHasher,
    hash::{Hash, Hasher},
    sync::Arc,
};
use uuid::Uuid;

const CHUNK_DURATION_MS: u64 = 10_000;
const SAMPLE_RATE: u64 = 44_100;

#[derive(Debug, Serialize)]
struct ChunkDescription {
    index: u32,
    start_ms: u64,
    duration_ms: u64,
    start_sample: u64,
    end_sample: u64,
    url: String,
}

#[derive(Debug, Serialize)]
struct TrackManifest {
    song_id: Uuid,
    media_version: String,
    duration_ms: u64,
    chunk_duration_ms: u64,
    format: &'static str,
    sample_rate_hz: u64,
    channels: u8,
    bits_per_sample: u8,
    chunks: Vec<ChunkDescription>,
}

#[derive(Debug, Deserialize)]
pub struct ChunkQuery {
    version: String,
}

fn media_version(song: &SongInfo) -> String {
    let mut hash = DefaultHasher::new();
    song.audio_reference.hash(&mut hash);
    song.duration_ms.hash(&mut hash);
    format!("v1-{:016x}", hash.finish())
}

fn manifest(song: &SongInfo) -> Option<TrackManifest> {
    let duration_ms = u64::try_from(song.duration_ms?).ok()?;
    if duration_ms == 0 {
        return None;
    }
    let version = media_version(song);
    let count = duration_ms.div_ceil(CHUNK_DURATION_MS);
    let chunks = (0..count)
        .map(|index| {
            let start_ms = index * CHUNK_DURATION_MS;
            let chunk_duration = (duration_ms - start_ms).min(CHUNK_DURATION_MS);
            ChunkDescription {
                index: index as u32,
                start_ms,
                duration_ms: chunk_duration,
                start_sample: start_ms * SAMPLE_RATE / 1_000,
                end_sample: (start_ms + chunk_duration) * SAMPLE_RATE / 1_000,
                url: format!(
                    "/api/streaming/tracks/{}/chunks/{index}?version={version}",
                    song.song_id
                ),
            }
        })
        .collect();

    Some(TrackManifest {
        song_id: song.song_id,
        media_version: version,
        duration_ms,
        chunk_duration_ms: CHUNK_DURATION_MS,
        format: "audio/wav; codecs=1",
        sample_rate_hz: SAMPLE_RATE,
        channels: 2,
        bits_per_sample: 16,
        chunks,
    })
}

async fn ready_song(
    catalogue: &Arc<dyn Catalogue>,
    song_id: Uuid,
) -> Result<SongInfo, HttpResponse> {
    match catalogue.get_song(song_id).await {
        Ok(song) if song.processing_status == "READY" => Ok(song),
        Ok(_) => Err(HttpResponse::Conflict().body("the song is not ready for streaming")),
        Err(CatalogueError::NotFound) => Err(HttpResponse::NotFound().finish()),
        Err(error) => Err(HttpResponse::BadGateway().body(error.to_string())),
    }
}

pub async fn get_manifest(
    catalogue: web::Data<Arc<dyn Catalogue>>,
    song_id: web::Path<Uuid>,
) -> impl Responder {
    let song = match ready_song(catalogue.get_ref(), song_id.into_inner()).await {
        Ok(song) => song,
        Err(response) => return response,
    };
    match manifest(&song) {
        Some(manifest) => HttpResponse::Ok().json(manifest),
        None => HttpResponse::Conflict().body("the song has no usable duration yet"),
    }
}

pub async fn get_chunk(
    store: web::Data<AudioStore>,
    catalogue: web::Data<Arc<dyn Catalogue>>,
    path: web::Path<(Uuid, u32)>,
    query: web::Query<ChunkQuery>,
) -> impl Responder {
    let (song_id, index) = path.into_inner();
    let song = match ready_song(catalogue.get_ref(), song_id).await {
        Ok(song) => song,
        Err(response) => return response,
    };
    let Some(manifest) = manifest(&song) else {
        return HttpResponse::Conflict().body("the song has no usable duration yet");
    };
    if query.version != manifest.media_version {
        return HttpResponse::Conflict().body("the media version is stale");
    }
    let Some(chunk) = manifest.chunks.get(index as usize) else {
        return HttpResponse::NotFound().finish();
    };

    match store
        .get_pcm_chunk(
            song_id,
            &song.audio_reference,
            &manifest.media_version,
            index,
            chunk.start_ms,
            chunk.duration_ms,
        )
        .await
    {
        Ok(bytes) => HttpResponse::Ok()
            .insert_header(("Cache-Control", "private, max-age=31536000, immutable"))
            .content_type("audio/wav")
            .body(bytes),
        Err(error) => HttpResponse::InternalServerError().body(error.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn song(duration_ms: i64) -> SongInfo {
        SongInfo {
            song_id: Uuid::nil(),
            audio_reference: "audio/example.mp3".into(),
            duration_ms: Some(duration_ms),
            processing_status: "READY".into(),
        }
    }

    #[test]
    fn manifest_uses_exact_contiguous_sample_boundaries() {
        let manifest = manifest(&song(25_001)).unwrap();
        assert_eq!(manifest.chunks.len(), 3);
        assert_eq!(manifest.chunks[0].start_sample, 0);
        assert_eq!(
            manifest.chunks[0].end_sample,
            manifest.chunks[1].start_sample
        );
        assert_eq!(
            manifest.chunks[1].end_sample,
            manifest.chunks[2].start_sample
        );
        assert_eq!(manifest.chunks[2].duration_ms, 5_001);
        assert_eq!(manifest.chunks[2].end_sample, 1_102_544);
    }

    #[test]
    fn version_changes_when_the_source_identity_changes() {
        let first = song(10_000);
        let mut second = song(10_001);
        assert_ne!(media_version(&first), media_version(&second));
        second.duration_ms = first.duration_ms;
        second.audio_reference = "audio/replaced.mp3".into();
        assert_ne!(media_version(&first), media_version(&second));
    }
}
