use actix_web::{HttpResponse, Responder, web};

use crate::security::UserId;

#[cfg(test)]
mod test;

pub fn configure(config: &mut web::ServiceConfig) {
    config.route("/health", web::get().to(health_check));
    config.route("/me", web::get().to(me));
}

pub async fn health_check() -> impl Responder {
    HttpResponse::Ok().body("OK")
}

/// Example protected route: the authenticated user's ID is supplied as a
/// handler parameter by the Cognito middleware via the [`UserId`] extractor.
pub async fn me(user_id: UserId) -> impl Responder {
    HttpResponse::Ok().json(serde_json::json!({ "user_id": user_id.as_str() }))
}
