pub mod audio_transmitter;

use actix_web::web;

/// Registers the audio transmitter service routes.
pub fn configure_routes(config: &mut web::ServiceConfig) {
    audio_transmitter::configure(config);
}
