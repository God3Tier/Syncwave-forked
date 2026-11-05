pub mod audio_by_time;
pub mod cache_state;
pub mod chunks;
pub mod health;
pub mod stream_info;
pub mod track_audio;

use actix_web::web;

/// Registers each audio transmitter endpoint.
pub fn configure(config: &mut web::ServiceConfig) {
    config
        .route(
            "/tracks/{track_id}/audio",
            web::get().to(track_audio::get_track_audio),
        )
        .route(
            "/tracks/{track_id}/stream-info",
            web::get().to(stream_info::get_stream_info),
        )
        .route(
            "/tracks/{track_id}/manifest",
            web::get().to(chunks::get_manifest),
        )
        .route(
            "/tracks/{track_id}/chunks/{chunk_index}",
            web::get().to(chunks::get_chunk),
        )
        .route("/health", web::get().to(health::get))
        .route("/cache", web::get().to(cache_state::get))
        .route(
            "/tracks/{track_id}/audio/range",
            web::get().to(audio_by_time::get_audio_by_range),
        );
}
