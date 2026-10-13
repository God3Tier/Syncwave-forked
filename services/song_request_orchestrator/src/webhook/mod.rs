use crate::Error; 
use bytes::Bytes;

pub mod client; 

/*
 * TODO: Figure out the other webhooks needed
 * TODO: If the actual program calculates the song peaks and troughs, is it returned via the webhook? 
 */
pub trait Webhook {
	async fn retrieve_song_by_timestamp(&self, id: i32, start_time: i32, end_time: i32) -> Result<Bytes, Error>; 
	async fn retrieve_lyrics(&self, id:i32) -> Result<Vec<(i32, String)>, Error>; 
}