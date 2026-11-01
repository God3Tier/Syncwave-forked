use super::PlaybackSessions;
use crate::{
    models::playback::PlaylistPlayback,
    ringbuffer::{CURRENT_SLOT, OFFSETS, RingBufferImpl},
    security::CognitoClaims,
    webhook::{Webhook, client::WebHookClient},
};
use actix_web::{HttpMessage, HttpRequest, HttpResponse, Responder, web};
use std::sync::Arc;
use tokio::sync::{Mutex, RwLock};
use uuid::Uuid;

pub async fn play(
    playlist_id: web::Path<Uuid>,
    client: web::Data<WebHookClient>,
    request: HttpRequest,
    sessions: web::Data<PlaybackSessions>,
) -> impl Responder {
    let client_id = match resolve_client_id(&request) {
        Ok(client_id) => client_id,
        Err(response) => return response,
    };
    let playlist_id = playlist_id.into_inner();
    let webhook_client = client.get_ref().clone();
    let song_ids = match webhook_client.retrieve_playlist_song_ids(playlist_id).await {
        Ok(song_ids) => song_ids,
        Err(error) => {
            return HttpResponse::BadGateway().json(serde_json::json!({
                "error": { "code": "UPSTREAM_SERVICE_ERROR", "message": error.to_string() }
            }));
        }
    };

    let shared_client = Arc::new(RwLock::new(webhook_client));
    let mut ring_buffer =
        RingBufferImpl::new(OFFSETS.len(), song_ids.into_boxed_slice(), shared_client);
    if let Err(error) = ring_buffer.initialize().await {
        return HttpResponse::BadGateway().json(serde_json::json!({
            "error": { "code": "UPSTREAM_SERVICE_ERROR", "message": error.to_string() }
        }));
    }

    let playback = Arc::new(Mutex::new(ring_buffer));
    sessions
        .lock()
        .await
        .insert((client_id, playlist_id), playback.clone());

    let ring_buffer = playback.lock().await;
    playback_response(playlist_id, &ring_buffer)
}

/// Returns the next audio chunk for the authenticated client's current song.
/// Call `/play` first to initialize and retain that client's ring buffer.
pub async fn next_chunk(
    playlist_id: web::Path<Uuid>,
    request: HttpRequest,
    sessions: web::Data<PlaybackSessions>,
) -> impl Responder {
    let client_id = match resolve_client_id(&request) {
        Ok(client_id) => client_id,
        Err(response) => return response,
    };
    let playlist_id = playlist_id.into_inner();
    let key = (client_id, playlist_id);
    let playback = sessions.lock().await.get(&key).cloned();
    let Some(playback) = playback else {
        return HttpResponse::NotFound().json(serde_json::json!({
            "error": { "code": "PLAYBACK_NOT_FOUND", "message": "start playlist playback first" }
        }));
    };

    let mut ring_buffer = playback.lock().await;
    if let Err(error) = ring_buffer.extend_current_song().await {
        return HttpResponse::BadGateway().json(serde_json::json!({
            "error": { "code": "UPSTREAM_SERVICE_ERROR", "message": error.to_string() }
        }));
    }

    playback_response(playlist_id, &ring_buffer)
}

fn resolve_client_id(request: &HttpRequest) -> Result<String, HttpResponse> {
    if let Some(claims) = request.extensions().get::<CognitoClaims>() {
        return Ok(claims.sub.clone());
    }
    request
        .headers()
        .get("x-client-id")
        .and_then(|value| value.to_str().ok())
        .filter(|value| !value.trim().is_empty())
        .map(str::to_owned)
        .ok_or_else(|| {
            HttpResponse::BadRequest().json(serde_json::json!({
                "error": { "code": "CLIENT_ID_REQUIRED", "message": "send X-Client-ID when Cognito authentication is disabled" }
            }))
        })
}

fn playback_response(
    playlist_id: Uuid,
    ring_buffer: &RingBufferImpl<WebHookClient>,
) -> HttpResponse {
    let mut buffers = ring_buffer.playback_buffers();
    for buffer in &mut buffers {
        let Some(duration_ms) = buffer.waveform.duration_ms else {
            buffer.waveform.timestamps_ms.clear();
            continue;
        };
        let peak_count = buffer.waveform.peaks.len() as u128;
        buffer.waveform.timestamps_ms = if peak_count == 0 {
            Vec::new()
        } else {
            (0..buffer.waveform.peaks.len())
                .map(|index| {
                    (((index as u128 * 2 + 1) * duration_ms as u128) / (peak_count * 2)) as u64
                })
                .collect()
        };
    }

    HttpResponse::Ok().json(PlaylistPlayback {
        playlist_id,
        current_position: CURRENT_SLOT,
        buffers,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::security::CognitoClaims;
    use actix_web::{
        App, Error, HttpMessage, HttpRequest, HttpResponse, HttpServer,
        body::to_bytes,
        dev::{ServiceRequest, ServiceResponse},
        http::StatusCode,
        middleware::Next,
        test, web,
    };

    const PLAYLIST_ID: &str = "00000000-0000-4000-8000-000000000010";
    const SONG_ID: &str = "00000000-0000-4000-8000-000000000011";

    fn test_claims(sub: &str) -> CognitoClaims {
        CognitoClaims {
            sub: sub.to_owned(),
            aud: "test-client".to_owned(),
            iss: "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test".to_owned(),
            exp: 4_000_000_000,
            iat: None,
            auth_time: None,
            token_use: "access".to_owned(),
            username: None,
            email: None,
            groups: Vec::new(),
            scope: None,
            client_id: None,
            jti: None,
        }
    }

    async fn inject_client<B>(
        req: ServiceRequest,
        next: Next<B>,
    ) -> Result<ServiceResponse<B>, Error> {
        req.extensions_mut().insert(test_claims("client-1"));
        next.call(req).await
    }

    fn sessions() -> web::Data<PlaybackSessions> {
        web::Data::new(Arc::new(tokio::sync::Mutex::new(
            std::collections::HashMap::new(),
        )))
    }

    async fn upstream(request: HttpRequest) -> HttpResponse {
        if request
            .path()
            .ends_with(&format!("/playlists/{PLAYLIST_ID}"))
        {
            return HttpResponse::Ok().json(serde_json::json!({
                "playlist_id": PLAYLIST_ID,
                "songs": [{ "song_id": SONG_ID, "position": 0 }]
            }));
        }
        if request.path().ends_with("/audio/range") {
            if request.query_string().contains("start=180") {
                return HttpResponse::Ok().body("next");
            }
            return HttpResponse::Ok().body("audio");
        }
        if request
            .path()
            .ends_with(&format!("/songs/{SONG_ID}/lyrics"))
        {
            return HttpResponse::Ok().json(serde_json::json!({
                "lines": [{ "time_ms": 1250, "text": "line" }]
            }));
        }
        if request
            .path()
            .ends_with(&format!("/songs/{SONG_ID}/waveform"))
        {
            return HttpResponse::Ok().json(serde_json::json!({
                "duration_ms": 420000,
                "peaks": [0.1, 0.5]
            }));
        }
        HttpResponse::NotFound().finish()
    }

    async fn mock_upstream_url() -> String {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = HttpServer::new(|| App::new().default_service(web::route().to(upstream)))
            .listen(listener)
            .unwrap()
            .run();
        actix_web::rt::spawn(server);
        format!("http://{address}")
    }

    #[actix_web::test]
    async fn rejects_a_non_uuid_playlist_id() {
        let client = web::Data::new(WebHookClient::new(
            "http://127.0.0.1:1".into(),
            "http://127.0.0.1:1".into(),
            "http://127.0.0.1:1".into(),
            "http://127.0.0.1:1".into(),
        ));
        let app = test::init_service(
            App::new()
                .wrap(actix_web::middleware::from_fn(inject_client))
                .app_data(client)
                .app_data(sessions())
                .route("/playlists/{playlist_id}/play", web::post().to(play)),
        )
        .await;
        let response = test::call_service(
            &app,
            test::TestRequest::post()
                .uri("/playlists/not-a-uuid/play")
                .to_request(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[actix_web::test]
    async fn returns_audio_lyrics_and_waveform_buffers_for_the_playlist() {
        let url = mock_upstream_url().await;
        let client = web::Data::new(WebHookClient::new(
            url.clone(),
            url.clone(),
            url.clone(),
            url,
        ));
        let app = test::init_service(
            App::new()
                .wrap(actix_web::middleware::from_fn(inject_client))
                .app_data(client)
                .app_data(sessions())
                .route("/playlists/{playlist_id}/play", web::post().to(play))
                .route(
                    "/playlists/{playlist_id}/play/next",
                    web::post().to(next_chunk),
                ),
        )
        .await;
        let response = test::call_service(
            &app,
            test::TestRequest::post()
                .uri(&format!("/playlists/{PLAYLIST_ID}/play"))
                .to_request(),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let body: serde_json::Value = test::read_body_json(response).await;
        let current = &body["buffers"][body["current_position"].as_u64().unwrap() as usize];
        assert_eq!(current["song_id"], SONG_ID);
        assert_eq!(current["audio_base64"], "YXVkaW8=");
        assert_eq!(current["lyrics"][0]["time_seconds"], 1.25);
        assert_eq!(current["waveform"]["duration_ms"], 420000);
        assert_eq!(current["waveform"]["peaks"], serde_json::json!([0.1, 0.5]));
        assert_eq!(
            current["waveform"]["timestamps_ms"],
            serde_json::json!([105000, 315000])
        );
    }

    #[actix_web::test]
    async fn next_chunk_appends_three_minutes_for_the_authenticated_client() {
        let url = mock_upstream_url().await;
        let sessions = sessions();
        let client = web::Data::new(WebHookClient::new(
            url.clone(),
            url.clone(),
            url.clone(),
            url,
        ));
        let app = test::init_service(
            App::new()
                .wrap(actix_web::middleware::from_fn(inject_client))
                .app_data(client)
                .app_data(sessions)
                .route("/playlists/{playlist_id}/play", web::post().to(play))
                .route(
                    "/playlists/{playlist_id}/play/next",
                    web::post().to(next_chunk),
                ),
        )
        .await;

        let start = test::call_service(
            &app,
            test::TestRequest::post()
                .uri(&format!("/playlists/{PLAYLIST_ID}/play"))
                .to_request(),
        )
        .await;
        assert_eq!(start.status(), StatusCode::OK);

        let response = test::call_service(
            &app,
            test::TestRequest::post()
                .uri(&format!("/playlists/{PLAYLIST_ID}/play/next"))
                .to_request(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::OK);
        let body: serde_json::Value =
            serde_json::from_slice(&to_bytes(response.into_body()).await.unwrap()).unwrap();
        let current = &body["buffers"][body["current_position"].as_u64().unwrap() as usize];
        assert_eq!(current["buffered_minutes"], 6.0);
        assert_eq!(current["audio_base64"], "YXVkaW9uZXh0");

        let response = test::call_service(
            &app,
            test::TestRequest::post()
                .uri(&format!("/playlists/{PLAYLIST_ID}/play/next"))
                .to_request(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::OK);
        let body: serde_json::Value = test::read_body_json(response).await;
        let current = &body["buffers"][body["current_position"].as_u64().unwrap() as usize];
        assert_eq!(current["buffered_minutes"], 7.0);
    }

    #[actix_web::test]
    async fn next_chunk_requires_an_initialized_client_playback() {
        let app = test::init_service(
            App::new()
                .wrap(actix_web::middleware::from_fn(inject_client))
                .app_data(sessions())
                .route(
                    "/playlists/{playlist_id}/play/next",
                    web::post().to(next_chunk),
                ),
        )
        .await;
        let response = test::call_service(
            &app,
            test::TestRequest::post()
                .uri(&format!("/playlists/{PLAYLIST_ID}/play/next"))
                .to_request(),
        )
        .await;
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }
}
