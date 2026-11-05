//! Song metadata comes from the Catalogue Service (plan.md section 3.1), the
//! canonical owner of song data. This service keeps no database of its own.
//!
//! It asks `GET {CATALOGUE_URL}/songs/{song_id}` and uses only the fields it
//! needs; every other field of the Catalogue's Song is ignored.

use reqwest::StatusCode;
use serde::Deserialize;
use std::time::Duration;
use thiserror::Error;
use uuid::Uuid;

/// The part of the Catalogue's Song that audio delivery needs.
#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct SongInfo {
    pub song_id: Uuid,
    /// The S3 key of the audio object.
    pub audio_reference: String,
    /// `null` in the Catalogue until Waveform has measured the song.
    pub duration_ms: Option<i64>,
    pub processing_status: String,
}

#[derive(Debug, Error)]
pub enum CatalogueError {
    /// The Catalogue answered that no such song exists.
    #[error("no such song in the Catalogue")]
    NotFound,
    /// The Catalogue could not give an answer: unreachable, too slow, an error
    /// status or an unreadable body. The song may well exist.
    #[error("the Catalogue Service could not answer: {0}")]
    Unavailable(String),
}

#[async_trait::async_trait]
pub trait Catalogue: Send + Sync {
    async fn get_song(&self, song_id: Uuid) -> Result<SongInfo, CatalogueError>;
}

/// Calls the Catalogue Service over HTTP.
pub struct HttpCatalogue {
    base_url: String,
    client: reqwest::Client,
}

impl HttpCatalogue {
    /// `timeout` bounds the whole request, so a slow Catalogue cannot hold a
    /// listener's request open forever.
    pub fn new(base_url: &str, timeout: Duration) -> Result<Self, reqwest::Error> {
        let client = reqwest::Client::builder().timeout(timeout).build()?;
        Ok(Self {
            base_url: base_url.trim_end_matches('/').to_owned(),
            client,
        })
    }
}

#[async_trait::async_trait]
impl Catalogue for HttpCatalogue {
    async fn get_song(&self, song_id: Uuid) -> Result<SongInfo, CatalogueError> {
        let response = self
            .client
            .get(format!("{}/songs/{song_id}", self.base_url))
            .send()
            .await
            .map_err(|error| CatalogueError::Unavailable(error.to_string()))?;

        match response.status() {
            StatusCode::OK => response.json::<SongInfo>().await.map_err(|error| {
                CatalogueError::Unavailable(format!("unreadable Catalogue response: {error}"))
            }),
            StatusCode::NOT_FOUND => Err(CatalogueError::NotFound),
            status => Err(CatalogueError::Unavailable(format!(
                "the Catalogue answered with status {status}"
            ))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::{App, HttpResponse, HttpServer, web};

    const FOUND: &str = "00000000-0000-4000-8000-000000000001";
    const NO_DURATION: &str = "00000000-0000-4000-8000-000000000002";
    const MISSING: &str = "00000000-0000-4000-8000-000000000003";
    const BROKEN: &str = "00000000-0000-4000-8000-000000000004";
    const GARBAGE: &str = "00000000-0000-4000-8000-000000000005";
    const SLOW: &str = "00000000-0000-4000-8000-000000000006";

    async fn mock_song(id: web::Path<String>) -> HttpResponse {
        match id.as_str() {
            FOUND => HttpResponse::Ok().json(serde_json::json!({
                "song_id": FOUND,
                "title": "T",
                "artist": "A",
                "duration_ms": 214000,
                "audio_reference": "audio/found.mp3",
                "lyrics_status": "READY",
                "waveform_status": "READY",
                "processing_status": "READY",
                "created_at": "2026-10-24T00:00:00Z",
                "updated_at": "2026-10-24T00:00:00Z"
            })),
            NO_DURATION => HttpResponse::Ok().json(serde_json::json!({
                "song_id": NO_DURATION,
                "audio_reference": "audio/pending.mp3",
                "duration_ms": null,
                "processing_status": "PROCESSING"
            })),
            MISSING => HttpResponse::NotFound().json(serde_json::json!({
                "error": {"code": "SONG_NOT_FOUND", "message": "No song"}
            })),
            BROKEN => HttpResponse::InternalServerError().body("boom"),
            GARBAGE => HttpResponse::Ok().body("not json"),
            SLOW => {
                actix_web::rt::time::sleep(Duration::from_secs(2)).await;
                HttpResponse::Ok().body("too late")
            }
            _ => HttpResponse::NotFound().finish(),
        }
    }

    async fn start_mock_catalogue() -> String {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = HttpServer::new(|| App::new().route("/songs/{id}", web::get().to(mock_song)))
            .listen(listener)
            .unwrap()
            .run();
        actix_web::rt::spawn(server);
        format!("http://{address}")
    }

    async fn catalogue() -> HttpCatalogue {
        // The trailing slash must be ignored.
        HttpCatalogue::new(
            &format!("{}/", start_mock_catalogue().await),
            Duration::from_millis(500),
        )
        .unwrap()
    }

    fn id(value: &str) -> Uuid {
        Uuid::parse_str(value).unwrap()
    }

    #[actix_web::test]
    async fn a_known_song_is_returned_and_extra_fields_are_ignored() {
        let song = catalogue().await.get_song(id(FOUND)).await.unwrap();
        assert_eq!(song.song_id, id(FOUND));
        assert_eq!(song.audio_reference, "audio/found.mp3");
        assert_eq!(song.duration_ms, Some(214_000));
        assert_eq!(song.processing_status, "READY");
    }

    #[actix_web::test]
    async fn a_song_without_a_duration_yet_has_none() {
        let song = catalogue().await.get_song(id(NO_DURATION)).await.unwrap();
        assert_eq!(song.duration_ms, None);
    }

    #[actix_web::test]
    async fn a_404_means_not_found() {
        let result = catalogue().await.get_song(id(MISSING)).await;
        assert!(matches!(result, Err(CatalogueError::NotFound)), "{result:?}");
    }

    #[actix_web::test]
    async fn a_server_error_is_unavailable_not_not_found() {
        let result = catalogue().await.get_song(id(BROKEN)).await;
        assert!(matches!(result, Err(CatalogueError::Unavailable(_))), "{result:?}");
    }

    #[actix_web::test]
    async fn an_unreadable_body_is_unavailable() {
        let result = catalogue().await.get_song(id(GARBAGE)).await;
        assert!(matches!(result, Err(CatalogueError::Unavailable(_))), "{result:?}");
    }

    #[actix_web::test]
    async fn a_slow_catalogue_times_out_as_unavailable() {
        let result = catalogue().await.get_song(id(SLOW)).await;
        assert!(matches!(result, Err(CatalogueError::Unavailable(_))), "{result:?}");
    }

    #[actix_web::test]
    async fn an_unreachable_catalogue_is_unavailable() {
        // Port 9 (discard) on localhost: nothing listens there.
        let catalogue = HttpCatalogue::new("http://127.0.0.1:9", Duration::from_millis(500)).unwrap();
        let result = catalogue.get_song(id(FOUND)).await;
        assert!(matches!(result, Err(CatalogueError::Unavailable(_))), "{result:?}");
    }
}
