use crate::store::audio::AudioStore;
use actix_web::{HttpResponse, Responder, web};

pub async fn get(store: web::Data<AudioStore>) -> impl Responder {
    HttpResponse::Ok().json(store.cache_state())
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::{App, http::StatusCode, test};
    use aws_sdk_s3::{
        Client,
        config::{Credentials, Region},
    };

    #[actix_web::test]
    async fn cache_state_returns_json_list() {
        let config = aws_sdk_s3::Config::builder()
            .behavior_version_latest()
            .region(Region::new("us-east-1"))
            .credentials_provider(Credentials::new("test", "test", None, None, "test"))
            .build();
        let store = web::Data::new(AudioStore::new(
            10,
            Client::from_conf(config),
            "bucket".into(),
        ));
        let app = test::init_service(
            App::new()
                .app_data(store)
                .route("/cache", web::get().to(get)),
        )
        .await;
        let response =
            test::call_service(&app, test::TestRequest::get().uri("/cache").to_request()).await;
        assert_eq!(response.status(), StatusCode::OK);
        let body: serde_json::Value = test::read_body_json(response).await;
        assert_eq!(body, serde_json::json!([]));
    }
}
