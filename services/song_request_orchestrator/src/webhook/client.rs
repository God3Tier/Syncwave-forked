use crate::models::playback::WaveformData;
use crate::webhook::errors::WebHookError;
use bytes::Bytes;
use reqwest::Client;
use serde_json::Value;
use std::env;
use std::time::Duration;
use uuid::Uuid;

#[derive(Clone)]
pub struct WebHookClient {
    audio_server: String,
    playlist_server: String,
    lyrics_server: String,
    waveform_server: String,
    client: Client,
}

impl WebHookClient {
    pub fn from_env() -> Self {
        Self::new(
            env::var("AUDIO_SERVICE_URL")
                .unwrap_or_else(|_| "http://audio_transmitter:8081".into()),
            env::var("PLAYLIST_SERVICE_URL").unwrap_or_else(|_| "http://playlist:8080".into()),
            env::var("LYRICS_SERVICE_URL").unwrap_or_else(|_| "http://lyrics:8080".into()),
            env::var("WAVEFORM_SERVICE_URL").unwrap_or_else(|_| "http://waveform:8080".into()),
        )
    }

    pub fn new(
        audio_server: String,
        playlist_server: String,
        lyrics_server: String,
        waveform_server: String,
    ) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .expect("default webhook HTTP client configuration is valid");
        Self {
            audio_server,
            playlist_server,
            lyrics_server,
            waveform_server,
            client,
        }
    }
}

impl super::Webhook for WebHookClient {
    async fn retrieve_playlist_song_ids(
        &self,
        playlist_id: Uuid,
    ) -> Result<Vec<Uuid>, WebHookError> {
        let response: Value = self
            .client
            .get(format!("{}/playlists/{playlist_id}", self.playlist_server))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        let songs = response
            .get("songs")
            .and_then(Value::as_array)
            .ok_or_else(|| {
                WebHookError::InvalidResponse("playlist response has no songs array".into())
            })?;
        songs
            .iter()
            .map(|song| {
                song.get("song_id")
                    .and_then(Value::as_str)
                    .ok_or_else(|| {
                        WebHookError::InvalidResponse("playlist song has no song_id".into())
                    })?
                    .parse::<Uuid>()
                    .map_err(|error| {
                        WebHookError::InvalidResponse(format!(
                            "invalid playlist song UUID: {error}"
                        ))
                    })
            })
            .collect()
    }

    async fn retrieve_song_by_timestamp(
        &self,
        id: Uuid,
        start_time: f64,
        end_time: f64,
    ) -> Result<Bytes, WebHookError> {
        let start_seconds = (start_time * 60.0).round() as u64;
        let end_seconds = (end_time * 60.0).round() as u64;
        let response = self
            .client
            .get(format!(
                "{}/tracks/{}/audio/range?start={}&end={}",
                self.audio_server, id, start_seconds, end_seconds
            ))
            .send()
            .await?
            .error_for_status()?;

        let body: Bytes = response.bytes().await?;
        Ok(body)
    }
    async fn retrieve_lyrics(&self, id: Uuid) -> Result<Vec<(i64, String)>, WebHookError> {
        let response: Value = self
            .client
            .get(format!("{}/songs/{id}/lyrics", self.lyrics_server))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        let lines = response
            .get("lines")
            .and_then(Value::as_array)
            .ok_or_else(|| {
                WebHookError::InvalidResponse("lyrics response has no lines array".into())
            })?;
        lines
            .iter()
            .map(|line| {
                let time_ms = line.get("time_ms").and_then(Value::as_i64).ok_or_else(|| {
                    WebHookError::InvalidResponse("lyric line has no integer time_ms".into())
                })?;
                let text = line.get("text").and_then(Value::as_str).ok_or_else(|| {
                    WebHookError::InvalidResponse("lyric line has no text".into())
                })?;
                Ok((time_ms, text.to_owned()))
            })
            .collect()
    }

    async fn retrieve_waveform(&self, id: Uuid) -> Result<WaveformData, WebHookError> {
        let response = self
            .client
            .get(format!("{}/songs/{id}/waveform", self.waveform_server))
            .send()
            .await?
            .error_for_status()?;
        Ok(response.json().await?)
    }
}
