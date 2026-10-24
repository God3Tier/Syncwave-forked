use thiserror::Error;

#[derive(Debug, Error)]
pub enum RingBufferError {
    #[error("Webhook error")]
    WebhookError(#[from] crate::webhook::errors::WebHookError),

    #[error("A spawned webhook task failed to complete")]
    TaskJoinError(#[from] actix_web::rt::task::JoinError),
}
