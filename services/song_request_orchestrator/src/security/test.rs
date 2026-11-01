use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use actix_web::{App, Error, HttpResponse, Responder, body::to_bytes, http::StatusCode, test, web};
use jsonwebtoken::{Algorithm, EncodingKey, Header, encode};

use super::{CognitoAuth, CognitoClaims, CognitoClient, CognitoConfig, UserId};

/// Throwaway 2048-bit RSA key pair used to sign and verify test tokens.
/// Test-only; never used by the service itself.
const TEST_PRIVATE_KEY: &str = "\
-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQC9qrg5xk1e9VKm
+MXAEuEe545eeUT0M12JfMHSUZfhGEpTkNNT8MWwLtQ7JZEdvaXoVYH21p4SJ4D6
GAib3xLHIOtNtKdk5AjDXUZQH+/Q5arZ9i2AL0fnqQ3mfaai54WQjIzE5BHyGyz2
W5jbOj8ILOcB+k4FHBLhx9Fn9wUXbaL1lpqsKBVD5K4UR7/scDdnMJO8RoXAg2zp
kzkZRJoMrIwRCK2iP2BLm9YVnoEwH5ieMDzT5zOJy2YL/y2bmU1lxf8iWl0jTN5j
nwYb+8//kpLRJm1cHBAE6Z7ZfvbP7fsGqXP98Mq9EBhO8GqkEdP4HWEKuZsUPizl
Ay5QtH8BAgMBAAECggEACzvMccqRnFNUKATRxJaxq/iLxYNx/rM4oesoWS5BPEEp
rNGl/KGk+dKKOi8XTV9FT3GaEx5CykE5+cYY42+Gz5G+8hEmPXrmnHiesKH1nKYv
tH1o1D/oprtL8hgE2b7z+ZvjfglimTf8FaLW9rwYTeIH9CVov9N5+FKzD9DxBaI7
/R+rcI5lNyI3klWYnpll7hMQn3tuw1HbuSDcxVGlLH/Zc9TpVdh7pXW0/PU37/8L
K7H41Po8FAWXhIYPU86F/sY8y/33yTmnvzLJa+ZUpm2hCyRl71xhvH0AQVDdGm+b
f1c0V3DZ24ku51jncVLxTPvLwYY4d1Sp5IDxZZK+YQKBgQDmQKzWVjurzhRpQIuP
6q+CoWW7UjGZfuBZgcnVEYV/U0Y+pTscqcRk4tnhfBnlv587TWIqCGP1Q2UAk62O
q2d/OgkapfxQaxGXGSCSWXMWUXaAp7o083yFP55qUdSjVvfB3IpGg3QHbpQtp6QJ
4BH/wYXKvmX3fLlJXcVAfV7h8QKBgQDS4Ddt39092x6yWmOomFHIFw2y/ezoLwfW
ydOaelwWJ+Aijpfg+DqDxsgTcA/a0CyHYIqizdEL0kwUOe59GwYI4ZnZ2B0RoOnJ
5tBbOuM9piTgmxxlquAm4xab7f1qBDi3Hozoy+7uMvzbNeYTcEoVGSFLiYXz3kba
y43WDIFeEQKBgB6h9hyh5lhqF18VXjvsXiND87PjMIQaVCC0WrTFGvygiJTnCKE8
mMtPPut3xj5Bqx6JogizixDjQXm9K/byKNfNUc7AzHuqcvGmPyYZTm1msxxUtDo9
NpDHsPy2HFMKy/V3sNHGxVYDyST1y6YgsGRVS8Z4ZDpz1nbDSe3VgB0RAoGAZ/0F
mHsyoNQzWQRV7MfgXGlx6fhqIT1AAl1Yqe75Bjv3vVLP9rKyOFWISH2Uc/UAYGnt
M8eG9OtpdPf0cWEoIq0Nr21xOEY/w768tKBfewE5YkFbSY9wJf0KIy7DLsqSJUs9
dXdLhc9C/d6gbKmM/sZ7ssJIei/8hNyoPwu/p+ECgYBt8ryJMrR+VheSbv2/im24
CUXvMFEsXdJjrHt0nTYWMX4sY5vuVgvH6V28w5WAWiNQvML23pL85SuaW19SpL69
/bvaj4v1ix07c2Dn7Q8xYB2IG3YTwT6RM4l1zSBo75r96/3wbc8/LEE5OLs22lKB
aUuXY4PQLrz+viI7zUwJlw==
-----END PRIVATE KEY-----
";

const TEST_PUBLIC_KEY: &str = "\
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvaq4OcZNXvVSpvjFwBLh
HueOXnlE9DNdiXzB0lGX4RhKU5DTU/DFsC7UOyWRHb2l6FWB9taeEieA+hgIm98S
xyDrTbSnZOQIw11GUB/v0OWq2fYtgC9H56kN5n2moueFkIyMxOQR8hss9luY2zo/
CCznAfpOBRwS4cfRZ/cFF22i9ZaarCgVQ+SuFEe/7HA3ZzCTvEaFwINs6ZM5GUSa
DKyMEQitoj9gS5vWFZ6BMB+YnjA80+czictmC/8tm5lNZcX/IlpdI0zeY58GG/vP
/5KS0SZtXBwQBOme2X72z+37Bqlz/fDKvRAYTvBqpBHT+B1hCrmbFD4s5QMuULR/
AQIDAQAB
-----END PUBLIC KEY-----
";

const TEST_KID: &str = "syncwave-test-key";
const TEST_CLIENT_ID: &str = "test-client-id";
const TEST_ISSUER: &str = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST";

/// A Cognito client whose JWKS cache holds the test public key.
fn test_client() -> Arc<CognitoClient> {
    let config = CognitoConfig {
        region: "us-east-1".to_owned(),
        user_pool_id: "us-east-1_TEST".to_owned(),
        client_id: TEST_CLIENT_ID.to_owned(),
        issuer: TEST_ISSUER.to_owned(),
        jwks_url: "https://example.invalid/.well-known/jwks.json".to_owned(),
        token_endpoint: None,
        jwks_ttl: Duration::from_secs(3600),
    };
    let client = CognitoClient::new(config).expect("test cognito client");
    client.insert_test_key(TEST_KID, TEST_PUBLIC_KEY.as_bytes());
    Arc::new(client)
}

fn test_auth() -> CognitoAuth {
    CognitoAuth::new(Some(test_client())).exclude("/health")
}

/// Signs a token with the test private key.
fn sign_token(sub: &str, exp_offset_secs: i64, kid: &str) -> String {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock before unix epoch")
        .as_secs() as i64;

    let claims = CognitoClaims {
        sub: sub.to_owned(),
        aud: TEST_CLIENT_ID.to_owned(),
        iss: TEST_ISSUER.to_owned(),
        exp: (now + exp_offset_secs) as u64,
        iat: Some(now as u64),
        auth_time: None,
        token_use: "access".to_owned(),
        username: Some(sub.to_owned()),
        email: Some(format!("{sub}@example.com")),
        groups: Vec::new(),
        scope: Some("openid".to_owned()),
        client_id: Some(TEST_CLIENT_ID.to_owned()),
        jti: None,
    };

    let mut header = Header::new(Algorithm::RS256);
    header.kid = Some(kid.to_owned());

    encode(
        &header,
        &claims,
        &EncodingKey::from_rsa_pem(TEST_PRIVATE_KEY.as_bytes()).expect("test private key"),
    )
    .expect("failed to sign test token")
}

fn test_token(sub: &str, exp_offset_secs: i64) -> String {
    sign_token(sub, exp_offset_secs, TEST_KID)
}

/// Routes used by the tests: `/health` has no extractors, `/whoami` takes the
/// [`UserId`] parameter and `/claims` takes the [`CognitoClaims`] parameter.
fn configure_test_routes(cfg: &mut web::ServiceConfig) {
    cfg.route("/whoami", web::get().to(whoami))
        .route("/claims", web::get().to(claims_sub))
        .route("/health", web::get().to(ok));
}

async fn whoami(user_id: UserId) -> impl Responder {
    HttpResponse::Ok().body(user_id.as_str().to_owned())
}

async fn claims_sub(claims: CognitoClaims) -> impl Responder {
    HttpResponse::Ok().body(claims.sub)
}

async fn ok() -> impl Responder {
    HttpResponse::Ok().body("OK")
}

/// The status of the error a middleware rejection produces.
fn rejection_status(err: &Error) -> StatusCode {
    err.error_response().status()
}

#[actix_web::test]
async fn valid_token_passes_user_id_to_the_handler() {
    let app = test::init_service(
        App::new()
            .wrap(test_auth())
            .configure(configure_test_routes),
    )
    .await;

    let token = test_token("user-123", 3600);
    let req = test::TestRequest::get()
        .uri("/whoami")
        .insert_header(("Authorization", format!("Bearer {token}")))
        .to_request();

    let resp = test::call_service(&app, req).await;
    assert_eq!(resp.status(), StatusCode::OK);
    let body = to_bytes(resp.into_body()).await.expect("response body");
    assert_eq!(&body[..], b"user-123");
}

#[actix_web::test]
async fn valid_token_exposes_claims_to_the_handler() {
    let app = test::init_service(
        App::new()
            .wrap(test_auth())
            .configure(configure_test_routes),
    )
    .await;

    let token = test_token("user-456", 3600);
    let req = test::TestRequest::get()
        .uri("/claims")
        .insert_header(("Authorization", format!("Bearer {token}")))
        .to_request();

    let resp = test::call_service(&app, req).await;
    assert_eq!(resp.status(), StatusCode::OK);
    let body = to_bytes(resp.into_body()).await.expect("response body");
    assert_eq!(&body[..], b"user-456");
}

#[actix_web::test]
async fn missing_token_is_rejected() {
    let app = test::init_service(
        App::new()
            .wrap(test_auth())
            .configure(configure_test_routes),
    )
    .await;

    let req = test::TestRequest::get().uri("/whoami").to_request();
    match test::try_call_service(&app, req).await {
        Ok(_) => panic!("request without a token should be rejected"),
        Err(err) => assert_eq!(rejection_status(&err), StatusCode::UNAUTHORIZED),
    }
}

#[actix_web::test]
async fn malformed_authorization_header_is_rejected() {
    let app = test::init_service(
        App::new()
            .wrap(test_auth())
            .configure(configure_test_routes),
    )
    .await;

    let req = test::TestRequest::get()
        .uri("/whoami")
        .insert_header(("Authorization", "Token not-a-bearer-token"))
        .to_request();

    match test::try_call_service(&app, req).await {
        Ok(_) => panic!("non-bearer authorization header should be rejected"),
        Err(err) => assert_eq!(rejection_status(&err), StatusCode::UNAUTHORIZED),
    }
}

#[actix_web::test]
async fn unverifiable_token_is_rejected() {
    let app = test::init_service(
        App::new()
            .wrap(test_auth())
            .configure(configure_test_routes),
    )
    .await;

    let req = test::TestRequest::get()
        .uri("/whoami")
        .insert_header(("Authorization", "Bearer not-a-jwt"))
        .to_request();

    match test::try_call_service(&app, req).await {
        Ok(_) => panic!("invalid token should be rejected"),
        Err(err) => assert_eq!(rejection_status(&err), StatusCode::UNAUTHORIZED),
    }
}

#[actix_web::test]
async fn expired_token_is_rejected() {
    let app = test::init_service(
        App::new()
            .wrap(test_auth())
            .configure(configure_test_routes),
    )
    .await;

    // Well past the 60 second clock-skew leeway.
    let token = test_token("user-123", -3600);
    let req = test::TestRequest::get()
        .uri("/whoami")
        .insert_header(("Authorization", format!("Bearer {token}")))
        .to_request();

    match test::try_call_service(&app, req).await {
        Ok(_) => panic!("expired token should be rejected"),
        Err(err) => assert_eq!(rejection_status(&err), StatusCode::UNAUTHORIZED),
    }
}

#[actix_web::test]
async fn token_with_unknown_key_id_is_rejected() {
    let app = test::init_service(
        App::new()
            .wrap(test_auth())
            .configure(configure_test_routes),
    )
    .await;

    let token = sign_token("user-123", 3600, "unknown-key");
    let req = test::TestRequest::get()
        .uri("/whoami")
        .insert_header(("Authorization", format!("Bearer {token}")))
        .to_request();

    match test::try_call_service(&app, req).await {
        Ok(_) => panic!("token signed with an unknown key should be rejected"),
        Err(err) => assert_eq!(rejection_status(&err), StatusCode::UNAUTHORIZED),
    }
}

#[actix_web::test]
async fn excluded_path_does_not_require_a_token() {
    let app = test::init_service(
        App::new()
            .wrap(test_auth())
            .configure(configure_test_routes),
    )
    .await;

    let req = test::TestRequest::get().uri("/health").to_request();
    let resp = test::call_service(&app, req).await;

    assert_eq!(resp.status(), StatusCode::OK);
    let body = to_bytes(resp.into_body()).await.expect("response body");
    assert_eq!(&body[..], b"OK");
}

#[actix_web::test]
async fn passes_through_when_cognito_is_not_configured() {
    let app = test::init_service(
        App::new()
            .wrap(CognitoAuth::new(None))
            .configure(configure_test_routes),
    )
    .await;

    let req = test::TestRequest::get().uri("/health").to_request();
    let resp = test::call_service(&app, req).await;

    assert_eq!(resp.status(), StatusCode::OK);
}

#[actix_web::test]
async fn user_id_extractor_rejects_when_unauthenticated() {
    let app = test::init_service(
        App::new()
            .wrap(CognitoAuth::new(None))
            .configure(configure_test_routes),
    )
    .await;

    // The middleware passes the request through, but the handler requires a
    // user id, so the extractor rejects it with 401.
    let req = test::TestRequest::get().uri("/whoami").to_request();
    let resp = test::call_service(&app, req).await;

    assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
}
