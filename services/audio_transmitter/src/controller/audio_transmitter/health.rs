use actix_web::{HttpResponse, Responder};
use serde::Serialize;

#[derive(Serialize)]
struct Health {
    status: &'static str,
}

/// Liveness check, like every other service's `GET /health`.
pub async fn get() -> impl Responder {
    HttpResponse::Ok().json(Health { status: "ok" })
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::{App, http::StatusCode, test, web};
    use serde_json::json;

    #[actix_web::test]
    async fn health_returns_ok() {
        let app = test::init_service(App::new().route("/health", web::get().to(get))).await;
        let response =
            test::call_service(&app, test::TestRequest::get().uri("/health").to_request()).await;
        assert_eq!(response.status(), StatusCode::OK);
        let body: serde_json::Value = test::read_body_json(response).await;
        assert_eq!(body, json!({ "status": "ok" }));
    }
}
