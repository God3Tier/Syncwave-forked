use actix_web::dev::{ServiceRequest, ServiceResponse};
use actix_web::middleware::Next;
use actix_web::{App, Error, HttpMessage, body::to_bytes, http::StatusCode, test};

use super::{health_check, me};

use crate::security::CognitoClaims;

fn test_claims(sub: &str) -> CognitoClaims {
    CognitoClaims {
        sub: sub.to_string(),
        aud: "test-client".to_string(),
        iss: "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test".to_string(),
        exp: 4_000_000_000,
        iat: None,
        auth_time: None,
        token_use: "access".to_string(),
        username: None,
        email: None,
        groups: Vec::new(),
        scope: None,
        client_id: None,
        jti: None,
    }
}

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

#[actix_web::test]
async fn me_returns_user_id_when_authenticated() {
    // Emulates the Cognito middleware by attaching verified claims.
    async fn inject_claims<B>(
        req: ServiceRequest,
        next: Next<B>,
    ) -> Result<ServiceResponse<B>, Error> {
        req.extensions_mut().insert(test_claims("user-123"));
        next.call(req).await
    }

    let app = test::init_service(
        App::new()
            .wrap(actix_web::middleware::from_fn(inject_claims))
            .route("/me", actix_web::web::get().to(me)),
    )
    .await;
    let response = test::call_service(&app, test::TestRequest::get().uri("/me").to_request()).await;

    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body()).await.unwrap();
    let body: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(body["user_id"], "user-123");
}

#[actix_web::test]
async fn me_without_claims_is_unauthorized() {
    let app = test::init_service(App::new().route("/me", actix_web::web::get().to(me))).await;
    let response = test::call_service(&app, test::TestRequest::get().uri("/me").to_request()).await;

    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
}
