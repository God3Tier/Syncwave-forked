use super::{Storage, audio::AudioStore};
use actix_web::{App, HttpResponse, HttpServer, web};
use aws_sdk_s3::{
    Client,
    config::{Credentials, Region},
};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
use std::time::Duration;

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

fn audio_store(capacity: u64, endpoint: &str) -> AudioStore {
    AudioStore::new(capacity, test_s3_client(endpoint), "test-bucket".to_owned())
}

#[actix_web::test]
async fn get_track_returns_cached_bytes_without_a_second_s3_fetch() {
    let (endpoint, mock_s3) = start_mock_s3(Duration::ZERO).await;
    let store = audio_store(10, &endpoint);

    let first = store.get_track(42).await.unwrap();
    let second = store.get_track(42).await.unwrap();

    assert_eq!(first.as_ref(), b"audio-data");
    assert_eq!(second.as_ref(), b"audio-data");
    assert_eq!(mock_s3.calls.load(Ordering::SeqCst), 1);
}

#[actix_web::test]
async fn failed_get_track_is_not_cached_and_the_next_call_retries() {
    let (endpoint, mock_s3) = start_mock_s3(Duration::ZERO).await;
    let store = audio_store(10, &endpoint);

    assert!(store.get_track(7).await.is_err());
    assert!(store.get_track(7).await.is_err());

    assert_eq!(mock_s3.calls.load(Ordering::SeqCst), 2);
}

#[actix_web::test]
#[ignore = "pending single-flight storage fetches for concurrent cache misses"]
async fn concurrent_cache_misses_share_one_s3_fetch() {
    let (endpoint, mock_s3) = start_mock_s3(Duration::from_millis(25)).await;
    let store = Arc::new(audio_store(10, &endpoint));
    let results = futures_util::future::join_all((0..8).map(|_| {
        let store = store.clone();
        async move { store.get_track(42).await }
    }))
    .await;

    assert!(results.iter().all(Result::is_ok));
    assert_eq!(mock_s3.calls.load(Ordering::SeqCst), 1);
}

#[actix_web::test]
async fn cache_evicts_entries_when_entry_capacity_is_exceeded() {
    let (endpoint, mock_s3) = start_mock_s3(Duration::ZERO).await;
    let store = audio_store(1, &endpoint);

    for track_id in [1, 2, 1] {
        store.get_track(track_id).await.unwrap();
    }

    assert_eq!(mock_s3.calls.load(Ordering::SeqCst), 2);
}

#[actix_web::test]
async fn get_track_by_timing_returns_the_expected_half_open_interval() {
    let (endpoint, _) = start_mock_s3(Duration::ZERO).await;
    let store = audio_store(10, &endpoint);

    let bytes = store.get_track_by_timing(44, 2, 5, 10).await.unwrap();

    assert_eq!(bytes.as_ref(), b"234");
}

#[actix_web::test]
async fn get_track_by_timing_clamps_end_to_track_runtime() {
    let (endpoint, _) = start_mock_s3(Duration::ZERO).await;
    let store = audio_store(10, &endpoint);

    let bytes = store.get_track_by_timing(44, 0, 11, 10).await.unwrap();

    assert_eq!(bytes.as_ref(), b"0123456789");
}
