pub mod orchestrator;

use actix_web::web;

/// Registers the orchestrator service routes.
pub fn configure_routes(config: &mut web::ServiceConfig) {
    orchestrator::configure(config);
}
