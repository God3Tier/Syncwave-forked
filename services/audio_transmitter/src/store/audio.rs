use crate::store::Storage;
use crate::store::errors::StoreError;
use aws_sdk_s3::Client;
use bytes::Bytes;
use moka::future::Cache;
use serde::Serialize;
use uuid::Uuid;

/// One cached song, without its audio bytes.
#[derive(Debug, PartialEq, Serialize)]
pub struct CachedTrack {
    pub song_id: Uuid,
    pub bytes: usize,
}

pub struct AudioStore {
    audio_stash: Cache<Uuid, Bytes>,
    client: Client,
    bucket_name: String,
}

impl AudioStore {
    pub fn new(capacity: u64, client: Client, bucket_name: String) -> Self {
        AudioStore {
            audio_stash: Cache::new(capacity),
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
}
