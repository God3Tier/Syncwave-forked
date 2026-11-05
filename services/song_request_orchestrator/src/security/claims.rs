use serde::{Deserialize, Serialize};

/// Claims emitted by SyncWave Auth for an authenticated browser session.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AuthClaims {
    pub sub: String,
    pub aud: String,
    pub iss: String,
    pub exp: u64,
    pub iat: u64,
    #[serde(default)]
    pub jti: Option<String>,
}
