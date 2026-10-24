use crate::{ringbuffer::RingBufferImpl, webhook::client::WebHookClient};
use actix_web::{HttpResponse, Responder, web};
use std::{collections::HashMap, sync::Arc};
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::security::UserId;
mod play_playlist;

/// Per-client, per-playlist ring buffers retained between playback requests.
pub type PlaybackSessions =
    Arc<Mutex<HashMap<(String, Uuid), Arc<Mutex<RingBufferImpl<WebHookClient>>>>>>;

#[cfg(test)]
mod test;

pub fn configure(config: &mut web::ServiceConfig) {
    config.route("/health", web::get().to(health_check));
    config.route("/me", web::get().to(me));
    config.route(
        "/playlists/{playlist_id}/play",
        web::post().to(play_playlist::play),
    );
    config.route(
        "/playlists/{playlist_id}/play/next",
        web::post().to(play_playlist::next_chunk),
    );
}

pub async fn health_check() -> impl Responder {
    HttpResponse::Ok().body("OK")
}

/// Example protected route: the authenticated user's ID is supplied as a
/// handler parameter by the Cognito middleware via the [`UserId`] extractor.
pub async fn me(user_id: UserId) -> impl Responder {
    HttpResponse::Ok().json(serde_json::json!({ "user_id": user_id.as_str() }))
}
