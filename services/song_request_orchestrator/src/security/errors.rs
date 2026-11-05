use actix_web::Error;
use actix_web::http::StatusCode;
use reqwest::Error as ReqwestError;

/// Errors produced while verifying a SyncWave account session.
#[derive(Debug, thiserror::Error)]
pub enum AuthError {
    #[error("missing SyncWave session")]
    MissingToken,
    #[error("invalid authorization header: expected 'Bearer <token>'")]
    InvalidHeader,
    #[error("token verification failed: {0}")]
    InvalidToken(String),
    #[error("authentication request failed: {0}")]
    AuthRequest(#[from] ReqwestError),
    #[error("JWKS fetch failed: {0}")]
    JwksFetch(String),
}

impl AuthError {
    pub fn status_code(&self) -> StatusCode {
        match self {
            Self::MissingToken | Self::InvalidHeader | Self::InvalidToken(_) => {
                StatusCode::UNAUTHORIZED
            }
            Self::AuthRequest(_) | Self::JwksFetch(_) => StatusCode::SERVICE_UNAVAILABLE,
        }
    }

    pub fn into_actix_error(self) -> Error {
        let body = self.to_string();
        match self.status_code() {
            StatusCode::UNAUTHORIZED => actix_web::error::ErrorUnauthorized(body),
            _ => actix_web::error::ErrorServiceUnavailable(body),
        }
    }
}
