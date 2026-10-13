pub mod audio_by_time;
pub mod cache_state;
pub mod track_audio;
mod errors; 

use actix_web::web;

/// Registers each audio transmitter endpoint.
pub fn configure(config: &mut web::ServiceConfig) {
    config
        .route(
            "/tracks/{track_id}/audio",
            web::get().to(track_audio::get_track_audio),
        )
        .route("/cache", web::get().to(cache_state::get))
        .route(
            "/tracks/{track_id}/audio/range",
            web::get().to(audio_by_time::get_audio_by_range),
        );
}
