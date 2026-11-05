use crate::store::Storage;
use crate::store::errors::StoreError;
use aws_sdk_s3::Client;
use bytes::Bytes;
use moka::future::Cache;
use serde::Serialize;
use std::{fs, process::Command, sync::Arc};
use tokio::sync::Semaphore;
use uuid::Uuid;

fn encode_pcm_chunk(source: Bytes, start_ms: u64, duration_ms: u64) -> Result<Vec<u8>, String> {
    let directory = tempfile::tempdir().map_err(|error| error.to_string())?;
    let input = directory.path().join("source");
    let output = directory.path().join("chunk.wav");
    fs::write(&input, source).map_err(|error| error.to_string())?;

    let result = Command::new("ffmpeg")
        .args([
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            &format!("{:.3}", start_ms as f64 / 1000.0),
            "-i",
        ])
        .arg(&input)
        .args([
            "-t",
            &format!("{:.3}", duration_ms as f64 / 1000.0),
            "-vn",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            "-y",
        ])
        .arg(&output)
        .output()
        .map_err(|error| format!("failed to start FFmpeg: {error}"))?;
    if !result.status.success() {
        return Err(String::from_utf8_lossy(&result.stderr).trim().to_owned());
    }
    fs::read(output).map_err(|error| error.to_string())
}

/// One cached song, without its audio bytes.
#[derive(Debug, PartialEq, Serialize)]
pub struct CachedTrack {
    pub song_id: Uuid,
    pub bytes: usize,
}

pub struct AudioStore {
    audio_stash: Cache<Uuid, Bytes>,
    chunk_stash: Cache<String, Bytes>,
    conversions: Arc<Semaphore>,
    client: Client,
    bucket_name: String,
}

impl AudioStore {
    pub fn new(capacity: u64, client: Client, bucket_name: String) -> Self {
        AudioStore {
            audio_stash: Cache::new(capacity),
            chunk_stash: Cache::builder()
                .max_capacity(256 * 1024 * 1024)
                .weigher(|_key: &String, value: &Bytes| value.len().min(u32::MAX as usize) as u32)
                .build(),
            conversions: Arc::new(Semaphore::new(2)),
            client,
            bucket_name,
        }
    }

    /// The cached song IDs and their sizes. Never the audio itself: this is
    /// reachable through the gateway.
    pub fn cache_state(&self) -> Vec<CachedTrack> {
        self.audio_stash
            .iter()
            .map(|(song_id, audio)| CachedTrack {
                song_id: *song_id,
                bytes: audio.len(),
            })
            .collect()
    }

    /// Produces one independently decodable PCM WAV derivative. Derivatives
    /// are cached by media version and chunk index; at most two FFmpeg jobs may
    /// run at once so a prefetch burst cannot exhaust the service.
    pub async fn get_pcm_chunk(
        &self,
        song_id: Uuid,
        audio_reference: &str,
        media_version: &str,
        chunk_index: u32,
        start_ms: u64,
        duration_ms: u64,
    ) -> Result<Bytes, StoreError> {
        let key = format!("{song_id}:{media_version}:{chunk_index}");
        if let Some(bytes) = self.chunk_stash.get(&key).await {
            return Ok(bytes);
        }

        let source = self.get_track(song_id, audio_reference).await?;
        let permit = self
            .conversions
            .clone()
            .acquire_owned()
            .await
            .map_err(|error| StoreError::AudioDerivative(error.to_string()))?;
        let encoded = actix_web::web::block(move || {
            let _permit = permit;
            encode_pcm_chunk(source, start_ms, duration_ms)
        })
        .await
        .map_err(|error| StoreError::AudioDerivative(error.to_string()))?
        .map_err(StoreError::AudioDerivative)?;

        let encoded = Bytes::from(encoded);
        self.chunk_stash.insert(key, encoded.clone()).await;
        Ok(encoded)
    }
}

#[async_trait::async_trait]
impl Storage for AudioStore {
    async fn get_track(&self, song_id: Uuid, audio_reference: &str) -> Result<Bytes, StoreError> {
        match self.audio_stash.get(&song_id).await {
            Some(bytes) => Ok(bytes),
            None => {
                let response = self
                    .client
                    .get_object()
                    .bucket(self.bucket_name.to_owned())
                    .key(audio_reference)
                    .send()
                    .await?;

                let data = response.body.collect().await?.into_bytes();
                self.audio_stash.insert(song_id, data).await;
                // Acceptable to unwrap here as we can gurantee an insert prior to this instruction
                Ok(self.audio_stash.get(&song_id).await.unwrap())
            }
        }
    }

    async fn get_track_by_timing(
        &self,
        song_id: Uuid,
        audio_reference: &str,
        start_time: u64,
        end_time: u64,
        total_time: i64,
    ) -> Result<Bytes, StoreError> {
        let audio = self.get_track(song_id, audio_reference).await?;
        let audio_len = audio.len();

        // Do integer division here because it should not matter if it overflows abit
        let ratio = audio_len / total_time as usize;
        let start_bit = start_time * ratio as u64;
        let end_bit = std::cmp::min(end_time, total_time as u64) * ratio as u64;

        Ok(audio.slice(start_bit as usize..end_bit as usize))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use aws_sdk_s3::config::{Credentials, Region};

    #[actix_web::test]
    async fn cache_state_lists_ids_and_sizes_without_audio() {
        let config = aws_sdk_s3::Config::builder()
            .behavior_version_latest()
            .region(Region::new("us-east-1"))
            .credentials_provider(Credentials::new("test", "test", None, None, "test"))
            .build();
        let store = AudioStore::new(10, Client::from_conf(config), "bucket".into());
        let song_id = Uuid::new_v4();
        store
            .audio_stash
            .insert(song_id, Bytes::from_static(b"ID3 audio"))
            .await;

        assert_eq!(store.cache_state(), vec![CachedTrack { song_id, bytes: 9 }]);
    }

    #[test]
    fn variable_bitrate_input_produces_independent_exact_wav_chunks() {
        let directory = tempfile::tempdir().unwrap();
        let source_path = directory.path().join("source.mp3");
        let generated = Command::new("ffmpeg")
            .args([
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=25.001",
                "-q:a",
                "4",
                "-y",
            ])
            .arg(&source_path)
            .status()
            .unwrap();
        assert!(generated.success());
        let source = Bytes::from(fs::read(source_path).unwrap());

        for (index, duration_ms) in [10_000, 10_000, 5_001].into_iter().enumerate() {
            let wav = encode_pcm_chunk(source.clone(), index as u64 * 10_000, duration_ms).unwrap();
            assert!(wav.starts_with(b"RIFF"));
            assert_eq!(&wav[8..12], b"WAVE");

            let path = directory.path().join(format!("chunk-{index}.wav"));
            fs::write(&path, wav).unwrap();
            let probe = Command::new("ffprobe")
                .args([
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=sample_rate,channels,duration_ts",
                    "-of",
                    "csv=p=0",
                ])
                .arg(path)
                .output()
                .unwrap();
            assert!(probe.status.success());
            let values = String::from_utf8(probe.stdout).unwrap();
            let fields: Vec<_> = values.trim().split(',').collect();
            assert_eq!(&fields[..2], ["44100", "2"]);
            assert_eq!(
                fields[2].parse::<u64>().unwrap(),
                duration_ms * 44_100 / 1_000
            );
        }
    }
}
