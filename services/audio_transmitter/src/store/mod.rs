use crate::Error;
use bytes::Bytes;
pub mod audio;

#[cfg(test)]
mod test;

#[async_trait::async_trait]
pub trait Storage: Send + Sync {
    async fn get_track(&self, id: i32) -> Result<Bytes, Error>;
    async fn get_track_by_timing(
        &self,
        id: i32,
        start_time: u64,
        end_time: u64,
        total_time: i64,
    ) -> Result<Bytes, Error>;
}
