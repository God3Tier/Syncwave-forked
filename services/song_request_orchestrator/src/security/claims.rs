use serde::{Deserialize, Serialize};

/// Claims verified from a Cognito JWT (access token or ID token).
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct CognitoClaims {
    /// Subject - the authenticated user's UUID.
    pub sub: String,
    /// Audience - the Cognito app client ID.
    pub aud: String,
    /// Issuer - the Cognito user pool URL.
    pub iss: String,
    /// Expiration time (Unix timestamp).
    pub exp: u64,
    /// Issued at (Unix timestamp).
    #[serde(default)]
    pub iat: Option<u64>,
    /// Authentication time (Unix timestamp, ID tokens only).
    #[serde(default)]
    pub auth_time: Option<u64>,
    /// Token use: `"access"` or `"id"`.
    pub token_use: String,
    /// The user's username (`cognito:username` claim).
    #[serde(rename = "cognito:username", default)]
    pub username: Option<String>,
    /// The user's email address.
    #[serde(default)]
    pub email: Option<String>,
    /// Cognito groups the user belongs to (`cognito:groups` claim).
    #[serde(rename = "cognito:groups", default)]
    pub groups: Vec<String>,
    /// OAuth scopes (access tokens only).
    #[serde(default)]
    pub scope: Option<String>,
    /// The app client ID that issued the token.
    #[serde(default)]
    pub client_id: Option<String>,
    /// JWT ID.
    #[serde(default)]
    pub jti: Option<String>,
}

impl CognitoClaims {
    /// Returns `true` if the token is an access token.
    pub fn is_access_token(&self) -> bool {
        self.token_use == "access"
    }

    /// Returns `true` if the token is an ID token.
    pub fn is_id_token(&self) -> bool {
        self.token_use == "id"
    }
}
