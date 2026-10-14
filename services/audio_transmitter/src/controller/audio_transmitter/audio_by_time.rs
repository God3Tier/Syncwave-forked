use crate::{
    controller::audio_transmitter::errors::MetadataError,
    db::DbPool,
    models::music_metadata::MusicMetadata,
    schema::music_metadata::dsl::music_metadata,
    store::{Storage, audio::AudioStore},
};
use actix_web::{HttpResponse, Responder, web};
use diesel::{associations::HasTable, prelude::*};

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
    db_pool: web::Data<DbPool>,
    track_id: web::Path<i32>,
    range: web::Query<AudioTimeRange>,
) -> impl Responder {
    let db = db_pool.clone();
    let track_id_clone = track_id.clone();

    let total_time = web::block(move || -> Result<MusicMetadata, MetadataError> {
        let mut conn = db.get()?;

        let metadata = music_metadata::table()
            .find(track_id_clone)
            .first::<MusicMetadata>(&mut conn)?;
        Ok(metadata)
    })
    .await;

    match total_time {
        Ok(Ok(metadata)) => {
            let range = range.into_inner();

            let pattern = normalize_time_range(range.start, range.end, metadata.timestamp);

            if pattern.is_none() {
                return HttpResponse::BadRequest().body(
                    "range start must not be greater than end: {range.start} <= {range.end}",
                );
            }

            let (start, end) = pattern.unwrap();

            match store
                .into_inner()
                .get_track_by_timing(track_id.into_inner(), start, end, metadata.timestamp)
                .await
            {
                Ok(bytes) => HttpResponse::Ok()
                    .content_type("application/octet-stream")
                    .body(bytes),
                Err(e) => HttpResponse::InternalServerError().body(e.to_string()),
            }
        }
        Ok(Err(MetadataError::Connection(e))) => {
            HttpResponse::InternalServerError().body(e.to_string())
        }
        Ok(Err(MetadataError::Query(e))) => HttpResponse::NotFound().body(e.to_string()),

        Err(e) => HttpResponse::InternalServerError().body(e.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::{App, HttpResponse, HttpServer, body::to_bytes, http::StatusCode, test, web};
    use aws_sdk_s3::{
        Client,
        config::{Credentials, Region},
    };
    use std::sync::OnceLock;

    static TEST_SCHEMA: OnceLock<()> = OnceLock::new();

    async fn mock_audio_object() -> HttpResponse {
        HttpResponse::Ok()
            .content_type("application/octet-stream")
            .body("0123456789")
    }

    async fn start_mock_s3() -> String {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server =
            HttpServer::new(|| App::new().default_service(web::route().to(mock_audio_object)))
                .listen(listener)
                .unwrap()
                .run();
        actix_web::rt::spawn(server);
        format!("http://{address}")
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

    fn disposable_db_pool() -> crate::db::DbPool {
        dotenvy::dotenv().ok();
        let database_url = std::env::var("TEST_DATABASE_URL")
            .expect("set TEST_DATABASE_URL to a disposable PostgreSQL database");
        let pool = crate::db::create_pool(&database_url).expect("database pool should initialize");
        TEST_SCHEMA.get_or_init(|| {
            crate::db::initialize_schema(&pool).expect("music metadata table should exist");
        });
        pool
    }

    fn insert_track(pool: &crate::db::DbPool, duration_seconds: i64) -> i32 {
        use crate::{
            models::music_metadata::{MusicMetadata, NewMusicMetadata},
            schema::music_metadata,
        };

        let mut connection = pool.get().expect("database connection should be available");
        diesel::insert_into(music_metadata::table)
            .values(NewMusicMetadata {
                song_name: "range-test-track",
                timestamp: Some(duration_seconds),
            })
            .returning(MusicMetadata::as_returning())
            .get_result::<MusicMetadata>(&mut connection)
            .expect("metadata row should be inserted")
            .id
    }

    macro_rules! init_range_app {
        ($pool:expr, $endpoint:expr) => {{
            let store = web::Data::new(AudioStore::new(
                10,
                test_s3_client(&$endpoint),
                "test-bucket".to_owned(),
            ));
            test::init_service(
                App::new()
                    .app_data(store)
                    .app_data(web::Data::new($pool))
                    .route(
                        "/tracks/{track_id}/audio/range",
                        web::get().to(get_audio_by_range),
                    ),
            )
            .await
        }};
    }

    #[actix_web::test]
    async fn valid_time_range_returns_the_requested_audio_bytes() {
        let pool = disposable_db_pool();
        let endpoint = start_mock_s3().await;
        let app = init_range_app!(pool.clone(), endpoint);
        let track_id = insert_track(&pool, 10);
        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri(&format!("/tracks/{track_id}/audio/range?start=2&end=5"))
                .to_request(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(to_bytes(response.into_body()).await.unwrap(), b"234"[..]);
    }

    #[actix_web::test]
    async fn malformed_time_query_is_rejected() {
        let pool = disposable_db_pool();
        let endpoint = start_mock_s3().await;
        let app = init_range_app!(pool, endpoint);

        for query in ["start=abc&end=5", "start=2", "start=-1&end=5"] {
            let response = test::call_service(
                &app,
                test::TestRequest::get()
                    .uri(&format!("/tracks/1/audio/range?{query}"))
                    .to_request(),
            )
            .await;
            assert_eq!(response.status(), StatusCode::BAD_REQUEST, "{query}");
        }
    }

    #[actix_web::test]
    async fn missing_track_metadata_returns_not_found() {
        let pool = disposable_db_pool();
        let endpoint = start_mock_s3().await;
        let app = init_range_app!(pool, endpoint);
        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/tracks/-1/audio/range?start=2&end=5")
                .to_request(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[actix_web::test]
    async fn empty_time_range_returns_bad_request() {
        let pool = disposable_db_pool();
        let endpoint = start_mock_s3().await;
        let app = init_range_app!(pool.clone(), endpoint);
        let track_id = insert_track(&pool, 10);
        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri(&format!("/tracks/{track_id}/audio/range?start=5&end=5"))
                .to_request(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn end_after_track_runtime_returns_the_whole_song() {
        let pool = disposable_db_pool();
        let endpoint = start_mock_s3().await;
        let app = init_range_app!(pool.clone(), endpoint);
        let track_id = insert_track(&pool, 10);
        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri(&format!("/tracks/{track_id}/audio/range?start=0&end=11"))
                .to_request(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            to_bytes(response.into_body()).await.unwrap(),
            b"0123456789"[..]
        );
    }

    #[actix_web::test]
    async fn zero_runtime_is_rejected_by_the_controller() {
        let pool = disposable_db_pool();
        let track_id = insert_track(&pool, 0);
        let endpoint = start_mock_s3().await;
        let app = init_range_app!(pool, endpoint);

        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri(&format!("/tracks/{track_id}/audio/range?start=0&end=1"))
                .to_request(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn start_after_end_is_rejected_by_the_controller() {
        let pool = disposable_db_pool();
        let track_id = insert_track(&pool, 10);
        let endpoint = start_mock_s3().await;
        let app = init_range_app!(pool, endpoint);

        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri(&format!("/tracks/{track_id}/audio/range?start=5&end=2"))
                .to_request(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }
}
