use std::sync::Arc;
use std::time::Duration;

use jsonwebtoken::{Algorithm, Validation, decode, decode_header};
use reqwest::Client;

use crate::security::claims::CognitoClaims;
use crate::security::config::CognitoConfig;
use crate::security::errors::AuthError;
use crate::security::jwks::JwksCache;

/// Tokens returned by the Cognito token endpoint.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct TokenResponse {
    pub access_token: String,
    #[serde(default)]
    pub id_token: Option<String>,
    #[serde(default)]
    pub refresh_token: Option<String>,
    pub token_type: String,
    pub expires_in: u64,
}

/// Client for verifying and obtaining Cognito JWTs.
///
/// Verification uses the Cognito JWKS endpoint: token signatures are verified
/// with the RSA public keys published at
/// `https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json`.
#[derive(Clone)]
pub struct CognitoClient {
    config: CognitoConfig,
    http: Client,
    jwks: Arc<JwksCache>,
}

impl CognitoClient {
    pub fn new(config: CognitoConfig) -> Result<Self, AuthError> {
        let http = Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .map_err(|e| AuthError::CognitoRequest(e))?;
        let jwks = Arc::new(JwksCache::new(&config.jwks_url, http.clone()));
        Ok(Self { config, http, jwks })
    }

    /// Insert a public key directly into the JWKS cache (tests only).
    #[cfg(test)]
    pub(crate) fn insert_test_key(&self, kid: &str, pem: &[u8]) {
        let key =
            jsonwebtoken::DecodingKey::from_rsa_pem(pem).expect("invalid test RSA public key");
        self.jwks.insert_key(kid.to_owned(), key);
    }

    /// The Cognito configuration in use.
    pub fn config(&self) -> &CognitoConfig {
        &self.config
    }

    /// Fetch the JWKS from Cognito and populate the verification key cache.
    ///
    /// This should be called at startup (and periodically thereafter) so that
    /// rotated signing keys are picked up.
    pub async fn refresh_jwks(&self) -> Result<(), AuthError> {
        self.jwks.refresh().await
    }

    /// Verify a Cognito JWT and return its claims.
    ///
    /// The token's signature, issuer, audience, and expiration are validated.
    /// This is synchronous once the JWKS cache has been populated.
    pub fn verify_token(&self, token: &str) -> Result<CognitoClaims, AuthError> {
        let header = decode_header(token).map_err(|e| AuthError::InvalidToken(e.to_string()))?;
        let kid = header
            .kid
            .as_deref()
            .ok_or_else(|| AuthError::InvalidToken("token header missing kid".to_string()))?;

        let key = self
            .jwks
            .get(kid)
            .ok_or_else(|| AuthError::InvalidToken(format!("unknown key id: {kid}")))?;

        let mut validation = Validation::new(Algorithm::RS256);
        validation.set_audience(&[&self.config.client_id]);
        validation.set_issuer(&[&self.config.issuer]);
        // exp is required and validated by default; allow 60s clock skew.
        validation.leeway = 60;

        let token_data = decode::<CognitoClaims>(token, &key, &validation)
            .map_err(|e| AuthError::InvalidToken(e.to_string()))?;

        let claims = token_data.claims;
        if !claims.is_access_token() && !claims.is_id_token() {
            return Err(AuthError::InvalidToken(format!(
                "unexpected token_use: {}",
                claims.token_use
            )));
        }

        Ok(claims)
    }

    /// Obtain tokens from Cognito using the `password` grant.
    ///
    /// This calls the Cognito token endpoint directly (no AWS signature
    /// required). The app client must be configured to allow the
    /// `PASSWORD` grant type and must not have a client secret.
    ///
    /// Returns the access token (suitable for `verify_token`) plus an optional
    /// ID token and refresh token.
    pub async fn authenticate_password(
        &self,
        username: &str,
        password: &str,
    ) -> Result<TokenResponse, AuthError> {
        let endpoint = self
            .config
            .token_endpoint
            .as_ref()
            .ok_or_else(|| AuthError::Config("COGNITO_DOMAIN is not configured".to_string()))?;

        let resp = self
            .http
            .post(endpoint)
            .form(&[
                ("grant_type", "password"),
                ("client_id", &self.config.client_id),
                ("username", username),
                ("password", password),
            ])
            .send()
            .await
            .map_err(|e| AuthError::CognitoRequest(e))?;

        if !resp.status().is_success() {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            return Err(AuthError::TokenEndpoint { status, body });
        }

        let tokens: TokenResponse = resp
            .json()
            .await
            .map_err(|e| AuthError::CognitoRequest(e))?;
        Ok(tokens)
    }
}
