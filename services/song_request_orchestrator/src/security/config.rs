use std::time::Duration;

/// Configuration for connecting to an Amazon Cognito user pool.
///
/// Values are read from environment variables. All are required unless noted.
#[derive(Debug, Clone)]
pub struct CognitoConfig {
    /// AWS region the user pool lives in (e.g. `us-east-1`).
    pub region: String,
    /// Cognito user pool ID (e.g. `us-east-1_XXXXXXXXX`).
    pub user_pool_id: String,
    /// Cognito app client ID.
    pub client_id: String,
    /// Issuer URL expected in the `iss` claim. Defaults to
    /// `https://cognito-idp.{region}.amazonaws.com/{user_pool_id}`.
    pub issuer: String,
    /// JWKS URL used to verify token signatures. Defaults to
    /// `{issuer}/.well-known/jwks.json`.
    pub jwks_url: String,
    /// Optional Cognito token endpoint used to obtain tokens
    /// (`https://{domain}.auth.{region}.amazoncognito.com/oauth2/token`).
    /// Only set when `COGNITO_DOMAIN` is configured.
    pub token_endpoint: Option<String>,
    /// How long to cache the JWKS before refreshing. Defaults to 1 hour.
    pub jwks_ttl: Duration,
}

impl CognitoConfig {
    /// Reads configuration from environment variables.
    ///
    /// # Environment variables
    ///
    /// - `COGNITO_REGION` (or `AWS_REGION`) - AWS region, **required**.
    /// - `COGNITO_USER_POOL_ID` - **required**.
    /// - `COGNITO_CLIENT_ID` - **required**.
    /// - `COGNITO_DOMAIN` - optional Cognito domain prefix for the token endpoint.
    /// - `COGNITO_ISSUER` - optional issuer URL override.
    /// - `COGNITO_JWKS_TTL_SECS` - optional JWKS cache TTL in seconds (default 3600).
    pub fn from_env() -> Result<Self, String> {
        let region = std::env::var("COGNITO_REGION")
            .or_else(|_| std::env::var("AWS_REGION"))
            .map_err(|_| "COGNITO_REGION or AWS_REGION must be set".to_string())?;
        let user_pool_id = std::env::var("COGNITO_USER_POOL_ID")
            .map_err(|_| "COGNITO_USER_POOL_ID must be set".to_string())?;
        let client_id = std::env::var("COGNITO_CLIENT_ID")
            .map_err(|_| "COGNITO_CLIENT_ID must be set".to_string())?;

        let issuer = std::env::var("COGNITO_ISSUER").unwrap_or_else(|_| {
            format!("https://cognito-idp.{region}.amazonaws.com/{user_pool_id}")
        });
        let jwks_url = format!("{issuer}/.well-known/jwks.json");

        let token_endpoint = std::env::var("COGNITO_DOMAIN")
            .ok()
            .map(|domain| format!("https://{domain}.auth.{region}.amazoncognito.com/oauth2/token"));

        let jwks_ttl = std::env::var("COGNITO_JWKS_TTL_SECS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok().map(Duration::from_secs))
            .unwrap_or(Duration::from_secs(3600));

        Ok(Self {
            region,
            user_pool_id,
            client_id,
            issuer,
            jwks_url,
            token_endpoint,
            jwks_ttl,
        })
    }
}
