use crate::store::{Storage, audio::AudioStore};
use actix_web::{HttpResponse, Responder, web};

/*
 * I'm not actually sure I want to ever use this endpoint. It only makes sense if we have a download feature
 */
pub async fn get_track_audio(
    store: web::Data<AudioStore>,
    track_id: web::Path<i32>,
) -> impl Responder {
    if track_id.clone() <= 0 {
        return HttpResponse::BadRequest().body("ID has to be positive");
    }

    match store.get_track(track_id.into_inner()).await {
        Ok(audio) => HttpResponse::Ok()
            .content_type("application/octet-stream")
            .body(audio),
        Err(error) => HttpResponse::InternalServerError().body(error.to_string()),
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
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    use std::time::Duration;

    macro_rules! assert_expected_eq {
        ($actual:expr, $expected:expr $(,)?) => {{
            let actual = &$actual;
            let expected = &$expected;
            assert_eq!(expected, actual, "expected: {expected:?}\nactual: {actual:?}");
        }};
        ($actual:expr, $expected:expr, $($arg:tt)+) => {{
            let actual = &$actual;
            let expected = &$expected;
            assert_eq!(expected, actual, "{}\nexpected: {expected:?}\nactual: {actual:?}", format_args!($($arg)+));
        }};
    }

    struct MockS3 {
        calls: AtomicUsize,
        delay: Duration,
    }

    async fn mock_s3_object(
        state: web::Data<Arc<MockS3>>,
        request: actix_web::HttpRequest,
    ) -> HttpResponse {
        state.calls.fetch_add(1, Ordering::SeqCst);
        if !state.delay.is_zero() {
            actix_web::rt::time::sleep(state.delay).await;
        }

        match request.path() {
            "/test-bucket/7" => HttpResponse::NotFound()
                .content_type("application/xml")
                .body("<Error><Code>NoSuchKey</Code><Message>missing</Message></Error>"),
            "/test-bucket/42" => HttpResponse::Ok()
                .content_type("application/octet-stream")
                .body("audio-data"),
            _ => HttpResponse::Ok()
                .content_type("application/octet-stream")
                .body("0123456789"),
        }
    }

    async fn start_mock_s3(delay: Duration) -> (String, Arc<MockS3>) {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let state = Arc::new(MockS3 {
            calls: AtomicUsize::new(0),
            delay,
        });
        let state_data = web::Data::new(state.clone());
        let server = HttpServer::new(move || {
            App::new()
                .app_data(state_data.clone())
                .default_service(web::route().to(mock_s3_object))
        })
        .listen(listener)
        .unwrap()
        .run();
        actix_web::rt::spawn(server);
        (format!("http://{address}"), state)
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

    macro_rules! init_audio_app {
        ($store:expr) => {
            test::init_service(
                App::new()
                    .app_data($store)
                    .route("/tracks/{track_id}/audio", web::get().to(get_track_audio)),
            )
            .await
        };
    }

    #[actix_web::test]
    async fn track_audio_returns_storage_bytes() {
        let (endpoint, _) = start_mock_s3(Duration::ZERO).await;
        let store = web::Data::new(AudioStore::new(
            10,
            test_s3_client(&endpoint),
            "test-bucket".to_owned(),
        ));
        let app = init_audio_app!(store);

        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/tracks/42/audio")
                .to_request(),
        )
        .await;
        assert_expected_eq!(response.status(), StatusCode::OK);
        assert_expected_eq!(
            to_bytes(response.into_body()).await.unwrap(),
            b"audio-data"[..]
        );
    }

    #[actix_web::test]
    async fn storage_failure_returns_500() {
        let (endpoint, _) = start_mock_s3(Duration::ZERO).await;
        let store = web::Data::new(AudioStore::new(
            10,
            test_s3_client(&endpoint),
            "test-bucket".to_owned(),
        ));
        let app = init_audio_app!(store);

        let response = test::call_service(
            &app,
            test::TestRequest::get().uri("/tracks/7/audio").to_request(),
        )
        .await;
        assert_expected_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
    }

    #[actix_web::test]
    async fn malformed_track_id_is_rejected_without_fetching_storage() {
        let (endpoint, mock_s3) = start_mock_s3(Duration::ZERO).await;
        let store = web::Data::new(AudioStore::new(
            10,
            test_s3_client(&endpoint),
            "test-bucket".to_owned(),
        ));
        let app = init_audio_app!(store);
        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/tracks/nope/audio")
                .to_request(),
        )
        .await;

        assert!(response.status().is_client_error());
        assert_expected_eq!(mock_s3.calls.load(Ordering::SeqCst), 0);
    }

    #[actix_web::test]
    async fn negative_track_id_is_rejected_without_fetching_storage() {
        let (endpoint, mock_s3) = start_mock_s3(Duration::ZERO).await;
        let store = web::Data::new(AudioStore::new(
            10,
            test_s3_client(&endpoint),
            "test-bucket".to_owned(),
        ));
        let app = init_audio_app!(store);

        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/tracks/-1/audio")
                .to_request(),
        )
        .await;

        assert!(response.status().is_client_error());
        assert_expected_eq!(mock_s3.calls.load(Ordering::SeqCst), 0);
    }

    #[actix_web::test]
    async fn get_returns_the_entire_audio_file() {
        let (endpoint, _) = start_mock_s3(Duration::ZERO).await;
        let store = web::Data::new(AudioStore::new(
            10,
            test_s3_client(&endpoint),
            "test-bucket".to_owned(),
        ));
        let app = init_audio_app!(store);
        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/tracks/44/audio")
                .to_request(),
        )
        .await;

        assert_expected_eq!(response.status(), StatusCode::OK);
        assert_expected_eq!(
            to_bytes(response.into_body()).await.unwrap(),
            b"0123456789"[..]
        );
    }

    #[actix_web::test]
    async fn audio_response_has_a_content_type() {
        let (endpoint, _) = start_mock_s3(Duration::ZERO).await;
        let store = web::Data::new(AudioStore::new(
            10,
            test_s3_client(&endpoint),
            "test-bucket".to_owned(),
        ));
        let app = init_audio_app!(store);

        let response = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/tracks/42/audio")
                .to_request(),
        )
        .await;

        assert!(response.headers().contains_key("Content-Type"));
    }
}
