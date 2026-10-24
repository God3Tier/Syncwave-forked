use thiserror::Error;

#[derive(Debug, Error)]
pub enum WebHookError {
    #[error("Unable to retrieve response from server")]
    RequestError(#[from] reqwest::Error),
    #[error("upstream service returned an invalid response: {0}")]
    InvalidResponse(String),
}
