use std::collections::HashMap;
use std::sync::RwLock;

use jsonwebtoken::DecodingKey;
use reqwest::Client;
use serde::Deserialize;

use crate::security::errors::AuthError;

/// A single JSON Web Key from Cognito's JWKS endpoint.
#[derive(Debug, Clone, Deserialize)]
pub struct Jwk {
    pub kty: String,
    pub kid: String,
    #[serde(rename = "use")]
    pub key_use: String,
    pub alg: String,
    pub n: String,
    pub e: String,
}

/// The Cognito `.well-known/jwks.json` response.
#[derive(Debug, Deserialize)]
pub struct JwksResponse {
    pub keys: Vec<Jwk>,
}

/// In-memory cache of Cognito RSA public keys indexed by `kid`.
///
/// [`refresh`](JwksCache::refresh) fetches the JWKS and rebuilds the cache;
/// token verification then reads keys from memory. Call it at startup and
/// periodically so that rotated signing keys are picked up.
pub struct JwksCache {
    jwks_url: String,
    http: Client,
    keys: RwLock<HashMap<String, DecodingKey>>,
}

impl JwksCache {
    pub fn new(jwks_url: impl Into<String>, http: Client) -> Self {
        Self {
            jwks_url: jwks_url.into(),
            http,
            keys: RwLock::new(HashMap::new()),
        }
    }

    /// Fetch the JWKS from Cognito and rebuild the key cache.
    pub async fn refresh(&self) -> Result<(), AuthError> {
        let resp = self
            .http
            .get(&self.jwks_url)
            .send()
            .await
            .map_err(|e| AuthError::JwksFetch(e.to_string()))?;

        if !resp.status().is_success() {
            return Err(AuthError::JwksFetch(format!(
                "unexpected status {}",
                resp.status()
            )));
        }

        let jwks: JwksResponse = resp
            .json()
            .await
            .map_err(|e| AuthError::JwksFetch(e.to_string()))?;

        let mut keys = HashMap::with_capacity(jwks.keys.len());
        for jwk in jwks.keys {
            // Cognito signs tokens with RSA-256 signature keys.
            if jwk.kty != "RSA" || jwk.alg != "RS256" || jwk.key_use != "sig" {
                continue;
            }
            if let Ok(key) = DecodingKey::from_rsa_components(&jwk.n, &jwk.e) {
                keys.insert(jwk.kid.clone(), key);
            }
        }

        *self.keys.write().expect("jwks cache poisoned") = keys;

        Ok(())
    }

    /// Returns the decoding key for the given `kid`, if cached.
    pub fn get(&self, kid: &str) -> Option<DecodingKey> {
        self.keys
            .read()
            .expect("jwks cache poisoned")
            .get(kid)
            .cloned()
    }

    /// Insert a decoding key directly into the cache (tests only).
    #[cfg(test)]
    pub(crate) fn insert_key(&self, kid: String, key: DecodingKey) {
        self.keys
            .write()
            .expect("jwks cache poisoned")
            .insert(kid, key);
    }
}
