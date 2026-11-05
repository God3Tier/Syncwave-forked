use crate::{
    catalogue::{Catalogue, CatalogueError},
    store::{Storage, audio::AudioStore},
};
use actix_web::{HttpResponse, Responder, web};
use std::sync::Arc;
use uuid::Uuid;

fn normalize_time_range(start: u64, end: u64, runtime: i64) -> Option<(u64, u64)> {
    if start > end {
        return None;
    }

    let end = end.min(runtime as u64);
    (start < end).then_some((start, end))
}

#[derive(serde::Deserialize)]
pub struct AudioTimeRange {
    pub start: u64,
    pub end: u64,
}

pub async fn get_audio_by_range(
    store: web::Data<AudioStore>,
    catalogue: web::Data<Arc<dyn Catalogue>>,
    track_id: web::Path<String>,
    range: web::Query<AudioTimeRange>,
) -> impl Responder {
    let song_id = match Uuid::parse_str(track_id.as_str()) {
        Ok(song_id) => song_id,
        Err(_) => return HttpResponse::BadRequest().body("song_id must be a UUID"),
    };

    // The Catalogue owns song metadata; this service keeps no copy of it.
    let song = match catalogue.get_song(song_id).await {
        Ok(song) => song,
        Err(CatalogueError::NotFound) => {
            return HttpResponse::NotFound().body(format!("no song with id {song_id}"));
        }
        // The song may exist; we just could not find out, so this is not a 404.
        Err(error) => return HttpResponse::BadGateway().body(error.to_string()),
    };
    let Some(duration_ms) = song.duration_ms else {
        return HttpResponse::Conflict().body("the song has no duration yet");
    };

    let range = range.into_inner();

    // The legacy range endpoint accepts seconds; Song.duration_ms is
    // authoritative and is converted only at this API boundary.
    let duration_seconds = duration_ms / 1_000;
    let pattern = normalize_time_range(range.start, range.end, duration_seconds);

    if pattern.is_none() {
        return HttpResponse::BadRequest()
            .body("range start must not be greater than end: {range.start} <= {range.end}");
    }

    let (start, end) = pattern.unwrap();

    match store
        .into_inner()
        .get_track_by_timing(song_id, &song.audio_reference, start, end, duration_seconds)
        .await
    {
        Ok(bytes) => HttpResponse::Ok()
            .content_type("application/octet-stream")
            .body(bytes),
        Err(e) => HttpResponse::InternalServerError().body(e.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::catalogue::SongInfo;
    use actix_web::{App, HttpResponse, HttpServer, body::to_bytes, http::StatusCode, test, web};
    use aws_sdk_s3::{
        Client,
        config::{Credentials, Region},
    };
    use std::{collections::HashMap, sync::Mutex};

    /// A Catalogue with a fixed set of songs: song id -> duration in ms
    /// (`None` is a song Waveform has not measured yet).
    struct FakeCatalogue {
        songs: HashMap<Uuid, Option<i64>>,
        down: bool,
        asked: Mutex<Vec<Uuid>>,
    }

    impl FakeCatalogue {
        fn with(songs: &[(Uuid, Option<i64>)]) -> Self {
            Self {
                songs: songs.iter().copied().collect(),
                down: false,
                asked: Mutex::new(Vec::new()),
            }
        }

        fn down() -> Self {
            Self {
                down: true,
                ..Self::with(&[])
            }
        }
    }

    #[async_trait::async_trait]
    impl Catalogue for FakeCatalogue {
        async fn get_song(&self, song_id: Uuid) -> Result<SongInfo, CatalogueError> {
            self.asked.lock().unwrap().push(song_id);
            if self.down {
                return Err(CatalogueError::Unavailable("the Catalogue is down".into()));
            }
            match self.songs.get(&song_id) {
                Some(duration_ms) => Ok(SongInfo {
                    song_id,
                    audio_reference: format!("audio/{song_id}.mp3"),
                    duration_ms: *duration_ms,
                    processing_status: "READY".into(),
                }),
                None => Err(CatalogueError::NotFound),
            }
        }
    }

    /// Answers every object request with ten bytes and records the paths asked for.
    async fn mock_audio_object(
        requested: web::Data<Arc<Mutex<Vec<String>>>>,
        request: actix_web::HttpRequest,
    ) -> HttpResponse {
        requested.lock().unwrap().push(request.path().to_owned());
        HttpResponse::Ok()
            .content_type("application/octet-stream")
            .body("0123456789")
    }

    async fn start_mock_s3() -> (String, Arc<Mutex<Vec<String>>>) {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let requested = Arc::new(Mutex::new(Vec::new()));
        let data = web::Data::new(requested.clone());
        let server = HttpServer::new(move || {
            App::new()
                .app_data(data.clone())
                .default_service(web::route().to(mock_audio_object))
        })
        .listen(listener)
        .unwrap()
        .run();
        actix_web::rt::spawn(server);
        (format!("http://{address}"), requested)
    }

    fn test_s3_client(endpoint: &str) -> Client {
        let config = aws_sdk_s3::Config::builder()
            .behavior_version_latest()
            .region(Region::new("us-east-1"))
            .credentials_provider(Credentials::new("test", "test", None, None, "test"))
            .endpoint_url(endpoint)
            .force_path_style(true)
            .build();
        Client::from_conf(config)
    }

    macro_rules! init_range_app {
        ($catalogue:expr, $endpoint:expr) => {{
            let store = web::Data::new(AudioStore::new(
                10,
                test_s3_client(&$endpoint),
                "test-bucket".to_owned(),
            ));
            let catalogue: Arc<dyn Catalogue> = $catalogue;
            test::init_service(
                App::new()
                    .app_data(store)
                    .app_data(web::Data::new(catalogue))
                    .route(
                        "/tracks/{track_id}/audio/range",
                        web::get().to(get_audio_by_range),
                    ),
            )
            .await
        }};
    }

    macro_rules! fetch {
        ($app:expr, $uri:expr) => {
            test::call_service(&$app, test::TestRequest::get().uri($uri).to_request()).await
        };
    }

    #[actix_web::test]
    async fn valid_time_range_returns_the_requested_audio_bytes() {
        let track_id = Uuid::new_v4();
        let (endpoint, _) = start_mock_s3().await;
        let app = init_range_app!(
            Arc::new(FakeCatalogue::with(&[(track_id, Some(10_000))])),
            endpoint
        );

        let response = fetch!(
            app,
            &format!("/tracks/{track_id}/audio/range?start=2&end=5")
        );

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(to_bytes(response.into_body()).await.unwrap(), b"234"[..]);
    }

    #[actix_web::test]
    async fn the_audio_is_fetched_with_the_key_the_catalogue_gave() {
        let track_id = Uuid::new_v4();
        let (endpoint, requested) = start_mock_s3().await;
        let app = init_range_app!(
            Arc::new(FakeCatalogue::with(&[(track_id, Some(10_000))])),
            endpoint
        );

        fetch!(
            app,
            &format!("/tracks/{track_id}/audio/range?start=0&end=1")
        );

        let paths = requested.lock().unwrap().clone();
        assert!(
            paths
                .iter()
                .any(|path| path.ends_with(&format!("audio/{track_id}.mp3"))),
            "{paths:?}"
        );
    }

    #[actix_web::test]
    async fn malformed_time_query_is_rejected() {
        let (endpoint, _) = start_mock_s3().await;
        let app = init_range_app!(Arc::new(FakeCatalogue::with(&[])), endpoint);

        for query in ["start=abc&end=5", "start=2", "start=-1&end=5"] {
            let response = fetch!(app, &format!("/tracks/not-a-uuid/audio/range?{query}"));
            assert_eq!(response.status(), StatusCode::BAD_REQUEST, "{query}");
        }
    }

    #[actix_web::test]
    async fn a_track_id_that_is_not_a_uuid_never_reaches_the_catalogue() {
        let (endpoint, _) = start_mock_s3().await;
        let catalogue = Arc::new(FakeCatalogue::with(&[]));
        let app = init_range_app!(catalogue.clone(), endpoint);

        let response = fetch!(app, "/tracks/not-a-uuid/audio/range?start=1&end=2");

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        assert!(catalogue.asked.lock().unwrap().is_empty());
    }

    #[actix_web::test]
    async fn missing_track_metadata_returns_not_found() {
        let (endpoint, _) = start_mock_s3().await;
        let app = init_range_app!(Arc::new(FakeCatalogue::with(&[])), endpoint);

        let response = fetch!(
            app,
            &format!("/tracks/{}/audio/range?start=2&end=5", Uuid::new_v4())
        );

        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[actix_web::test]
    async fn an_unavailable_catalogue_is_a_bad_gateway_not_a_not_found() {
        let (endpoint, requested) = start_mock_s3().await;
        let app = init_range_app!(Arc::new(FakeCatalogue::down()), endpoint);

        let response = fetch!(
            app,
            &format!("/tracks/{}/audio/range?start=2&end=5", Uuid::new_v4())
        );

        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
        assert!(
            requested.lock().unwrap().is_empty(),
            "no audio is fetched without metadata"
        );
    }

    #[actix_web::test]
    async fn a_song_without_a_duration_yet_returns_conflict() {
        let track_id = Uuid::new_v4();
        let (endpoint, requested) = start_mock_s3().await;
        let app = init_range_app!(Arc::new(FakeCatalogue::with(&[(track_id, None)])), endpoint);

        let response = fetch!(
            app,
            &format!("/tracks/{track_id}/audio/range?start=0&end=1")
        );

        assert_eq!(response.status(), StatusCode::CONFLICT);
        assert!(requested.lock().unwrap().is_empty());
    }

    #[actix_web::test]
    async fn empty_time_range_returns_bad_request() {
        let track_id = Uuid::new_v4();
        let (endpoint, _) = start_mock_s3().await;
        let app = init_range_app!(
            Arc::new(FakeCatalogue::with(&[(track_id, Some(10_000))])),
            endpoint
        );

        let response = fetch!(
            app,
            &format!("/tracks/{track_id}/audio/range?start=5&end=5")
        );

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn end_after_track_runtime_returns_the_whole_song() {
        let track_id = Uuid::new_v4();
        let (endpoint, _) = start_mock_s3().await;
        let app = init_range_app!(
            Arc::new(FakeCatalogue::with(&[(track_id, Some(10_000))])),
            endpoint
        );

        let response = fetch!(
            app,
            &format!("/tracks/{track_id}/audio/range?start=0&end=11")
        );

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            to_bytes(response.into_body()).await.unwrap(),
            b"0123456789"[..]
        );
    }

    #[actix_web::test]
    async fn zero_runtime_is_rejected_by_the_controller() {
        let track_id = Uuid::new_v4();
        let (endpoint, _) = start_mock_s3().await;
        let app = init_range_app!(
            Arc::new(FakeCatalogue::with(&[(track_id, Some(0))])),
            endpoint
        );

        let response = fetch!(
            app,
            &format!("/tracks/{track_id}/audio/range?start=0&end=1")
        );

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn start_after_end_is_rejected_by_the_controller() {
        let track_id = Uuid::new_v4();
        let (endpoint, _) = start_mock_s3().await;
        let app = init_range_app!(
            Arc::new(FakeCatalogue::with(&[(track_id, Some(10_000))])),
            endpoint
        );

        let response = fetch!(
            app,
            &format!("/tracks/{track_id}/audio/range?start=5&end=2")
        );

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }
}
