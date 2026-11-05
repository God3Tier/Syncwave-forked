use std::time::Duration;

/// Configuration for verifying sessions issued by SyncWave Auth.
#[derive(Debug, Clone)]
pub struct AuthConfig {
    pub issuer: String,
    pub audience: String,
    pub jwks_url: String,
    pub jwks_ttl: Duration,
}

impl AuthConfig {
    pub fn from_env() -> Result<Self, String> {
        let jwks_url = std::env::var("AUTH_JWKS_URL")
            .map_err(|_| "AUTH_JWKS_URL must be set to enable authentication".to_owned())?;
        let issuer = std::env::var("AUTH_ISSUER").unwrap_or_else(|_| "syncwave-auth".to_owned());
        let audience = std::env::var("AUTH_AUDIENCE").unwrap_or_else(|_| "syncwave".to_owned());
        let jwks_ttl = std::env::var("AUTH_JWKS_TTL_SECS")
            .ok()
            .and_then(|value| value.parse::<u64>().ok())
            .map(Duration::from_secs)
            .unwrap_or(Duration::from_secs(3600));

        Ok(Self {
            issuer,
            audience,
            jwks_url,
            jwks_ttl,
        })
    }
}
