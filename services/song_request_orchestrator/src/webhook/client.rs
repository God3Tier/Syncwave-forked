use crate::Error;
use bytes::Bytes;
use reqwest::Client;
use std::time::Duration;

pub struct WebHookClient {
    audio_server: String,
}

impl super::Webhook for WebHookClient {
    async fn retrieve_song_by_timestamp(
        &self,
        id: i32,
        start_time: i32,
        end_time: i32,
    ) -> Result<Bytes, Error> {
        let client = Client::builder().timeout(Duration::from_secs(5)).build()?;

        let response = client
            .get(format!(
                "{}/tracks/{}/audio/range?start={}&end={}",
                self.audio_server, id, start_time, end_time
            ))
            .send()
            .await?
            .error_for_status()?;

        let body: Bytes = response.bytes().await?;
        Ok(body)
    }
    async fn retrieve_lyrics(&self, id: i32) -> Result<Vec<(i32, String)>, Error> {
        todo!("Lyrics retrieval not done yet")
    }
}
