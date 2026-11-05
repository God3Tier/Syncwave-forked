use std::sync::Arc;
use std::time::Duration;

use jsonwebtoken::{Algorithm, Validation, decode, decode_header};
use reqwest::Client;

use crate::security::claims::AuthClaims;
use crate::security::config::AuthConfig;
use crate::security::errors::AuthError;
use crate::security::jwks::JwksCache;

/// Verifies JWT sessions issued by SyncWave Auth.
#[derive(Clone)]
pub struct AuthClient {
    config: AuthConfig,
    jwks: Arc<JwksCache>,
}

impl AuthClient {
    pub fn new(config: AuthConfig) -> Result<Self, AuthError> {
        let http = Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .map_err(AuthError::AuthRequest)?;
        let jwks = Arc::new(JwksCache::new(&config.jwks_url, http));
        Ok(Self { config, jwks })
    }

    #[cfg(test)]
    pub(crate) fn insert_test_key(&self, kid: &str, pem: &[u8]) {
        let key =
            jsonwebtoken::DecodingKey::from_rsa_pem(pem).expect("invalid test RSA public key");
        self.jwks.insert_key(kid.to_owned(), key);
    }

    pub fn config(&self) -> &AuthConfig {
        &self.config
    }

    pub async fn refresh_jwks(&self) -> Result<(), AuthError> {
        self.jwks.refresh().await
    }

    pub fn verify_token(&self, token: &str) -> Result<AuthClaims, AuthError> {
        let header =
            decode_header(token).map_err(|error| AuthError::InvalidToken(error.to_string()))?;
        let kid = header
            .kid
            .as_deref()
            .ok_or_else(|| AuthError::InvalidToken("token header missing kid".to_owned()))?;
        let key = self
            .jwks
            .get(kid)
            .ok_or_else(|| AuthError::InvalidToken(format!("unknown key id: {kid}")))?;

        let mut validation = Validation::new(Algorithm::RS256);
        validation.set_audience(&[&self.config.audience]);
        validation.set_issuer(&[&self.config.issuer]);
        validation.set_required_spec_claims(&["sub", "aud", "iss", "exp", "iat"]);
        validation.leeway = 60;

        decode::<AuthClaims>(token, &key, &validation)
            .map(|data| data.claims)
            .map_err(|error| AuthError::InvalidToken(error.to_string()))
    }
}
