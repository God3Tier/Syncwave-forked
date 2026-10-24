use bytes::Bytes;
use errors::StoreError;
use uuid::Uuid;

pub mod audio;
mod errors;
#[cfg(test)]
mod test;

#[async_trait::async_trait]
pub trait Storage: Send + Sync {
    async fn get_track(&self, song_id: Uuid, audio_reference: &str) -> Result<Bytes, StoreError>;
    async fn get_track_by_timing(
        &self,
        song_id: Uuid,
        audio_reference: &str,
        start_time: u64,
        end_time: u64,
        total_time: i64,
    ) -> Result<Bytes, StoreError>;
}
