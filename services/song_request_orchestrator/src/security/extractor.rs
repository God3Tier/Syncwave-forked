use std::future::{Ready, ready};

use actix_web::dev::Payload;
use actix_web::{Error, FromRequest, HttpMessage, HttpRequest, error};

use crate::security::CognitoClaims;

/// The authenticated user's ID, taken from the JWT `sub` claim.
///
/// Handlers receive this as a parameter:
///
/// ```ignore
/// async fn me(user_id: UserId) -> impl Responder {
///     format!("authenticated as {}", user_id.0)
/// }
/// ```
///
/// The value is supplied by the [`CognitoAuth`](crate::security::CognitoAuth)
/// middleware, which verifies the request's bearer token and stores its claims
/// in the request extensions. If the middleware did not run (or the token was
/// rejected before reaching the handler), extraction fails with `401
/// Unauthorized`.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct UserId(pub String);

impl UserId {
    /// The raw Cognito user ID (JWT `sub`).
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for UserId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl FromRequest for UserId {
    type Error = Error;
    type Future = Ready<Result<Self, Self::Error>>;

    fn from_request(req: &HttpRequest, _payload: &mut Payload) -> Self::Future {
        let user_id = req
            .extensions()
            .get::<CognitoClaims>()
            .map(|claims| UserId(claims.sub.clone()));
        ready(user_id.ok_or_else(|| error::ErrorUnauthorized("missing authenticated user")))
    }
}

impl FromRequest for CognitoClaims {
    type Error = Error;
    type Future = Ready<Result<Self, Self::Error>>;

    fn from_request(req: &HttpRequest, _payload: &mut Payload) -> Self::Future {
        let claims = req.extensions().get::<CognitoClaims>().cloned();
        ready(claims.ok_or_else(|| error::ErrorUnauthorized("missing cognito claims")))
    }
}
