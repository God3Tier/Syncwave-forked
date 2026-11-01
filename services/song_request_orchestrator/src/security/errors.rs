use actix_web::Error;
use actix_web::http::StatusCode;
use reqwest::Error as ReqwestError;

/// Errors produced while authenticating with Amazon Cognito.
#[derive(Debug, thiserror::Error)]
pub enum AuthError {
    #[error("missing authorization header")]
    MissingToken,

    #[error("invalid authorization header: expected 'Bearer <token>'")]
    InvalidHeader,

    #[error("token verification failed: {0}")]
    InvalidToken(String),

    #[error("cognito request failed: {0}")]
    CognitoRequest(#[from] ReqwestError),

    #[error("cognito token endpoint returned HTTP {status}: {body}")]
    TokenEndpoint { status: u16, body: String },

    #[error("jwks fetch failed: {0}")]
    JwksFetch(String),

    #[error("missing cognito configuration: {0}")]
    Config(String),
}

impl AuthError {
    /// HTTP status code to use when reporting this error to a client.
    pub fn status_code(&self) -> StatusCode {
        match self {
            AuthError::MissingToken | AuthError::InvalidHeader | AuthError::InvalidToken(_) => {
                StatusCode::UNAUTHORIZED
            }
            AuthError::TokenEndpoint { .. } => StatusCode::BAD_GATEWAY,
            AuthError::CognitoRequest(_) | AuthError::JwksFetch(_) | AuthError::Config(_) => {
                StatusCode::INTERNAL_SERVER_ERROR
            }
        }
    }

    /// Convert into an [`actix_web::Error`] with the appropriate status code.
    pub fn into_actix_error(self) -> Error {
        let body = self.to_string();
        match self.status_code() {
            StatusCode::UNAUTHORIZED => actix_web::error::ErrorUnauthorized(body),
            StatusCode::BAD_GATEWAY => actix_web::error::ErrorBadGateway(body),
            _ => actix_web::error::ErrorInternalServerError(body),
        }
    }
}
