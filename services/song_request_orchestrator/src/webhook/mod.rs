use bytes::Bytes;
use errors::WebHookError;

pub mod client;
pub mod errors;

/*
 * TODO: Figure out the other webhooks needed
 * TODO: If the actual program calculates the song peaks and troughs, is it returned via the webhook?
 */
pub trait Webhook {
    async fn retrieve_song_by_timestamp(
        &self,
        id: i32,
        start_time: f64,
        end_time: f64,
    ) -> Result<Bytes, WebHookError>;
    async fn retrieve_lyrics(&self, id: i32) -> Result<Vec<(i32, String)>, WebHookError>;
}
