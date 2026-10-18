use thiserror::Error;

#[derive(Debug, Error)]
pub enum WebHookError {
    #[error("Unable to retrieve response from server")]
    RequestError(#[from] reqwest::Error),
}
