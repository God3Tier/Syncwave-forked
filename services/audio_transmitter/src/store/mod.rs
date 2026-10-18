use bytes::Bytes;
use errors::StoreError;

pub mod audio;
mod errors; 
#[cfg(test)]
mod test;

#[async_trait::async_trait]
pub trait Storage: Send + Sync {
    async fn get_track(&self, id: i32) -> Result<Bytes, StoreError>;
    async fn get_track_by_timing(
        &self,
        id: i32,
        start_time: u64,
        end_time: u64,
        total_time: i64,
    ) -> Result<Bytes, StoreError>;
}
