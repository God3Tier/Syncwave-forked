use crate::models::playback::WaveformData;
use bytes::Bytes;
use errors::WebHookError;
use uuid::Uuid;

pub mod client;
pub mod errors;

/*
 * TODO: Figure out the other webhooks needed
 * TODO: If the actual program calculates the song peaks and troughs, is it returned via the webhook?
 */
pub trait Webhook {
    async fn retrieve_playlist_song_ids(
        &self,
        playlist_id: Uuid,
    ) -> Result<Vec<Uuid>, WebHookError>;
    async fn retrieve_song_by_timestamp(
        &self,
        id: Uuid,
        start_time: f64,
        end_time: f64,
    ) -> Result<Bytes, WebHookError>;
    async fn retrieve_lyrics(&self, id: Uuid) -> Result<Vec<(i64, String)>, WebHookError>;
    async fn retrieve_waveform(&self, id: Uuid) -> Result<WaveformData, WebHookError>;
}
