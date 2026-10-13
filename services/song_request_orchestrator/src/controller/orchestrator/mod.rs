use actix_web::{HttpResponse, Responder};

pub fn configure(config: &mut actix_web::web::ServiceConfig) {
    config.route("/health", actix_web::web::get().to(health_check));
}

pub async fn health_check() -> impl Responder {
    HttpResponse::Ok().body("OK")
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::{App, body::to_bytes, http::StatusCode, test};

    #[actix_web::test]
    async fn health_check_returns_ok() {
        let app =
            test::init_service(App::new().route("/health", actix_web::web::get().to(health_check)))
                .await;
        let response =
            test::call_service(&app, test::TestRequest::get().uri("/health").to_request()).await;

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(to_bytes(response.into_body()).await.unwrap(), b"OK"[..]);
    }

    #[actix_web::test]
    async fn unknown_route_returns_not_found() {
        let app =
            test::init_service(App::new().route("/health", actix_web::web::get().to(health_check)))
                .await;
        let response =
            test::call_service(&app, test::TestRequest::get().uri("/missing").to_request()).await;

        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }
}
