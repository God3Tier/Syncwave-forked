use crate::Error;
use bytes::Bytes;

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
        todo!("song retrieval is not implemented yet")
    }
   	async fn retrieve_lyrics(&self, id:i32) -> Result<Vec<(i32, String)>, Error> {
    	todo!("Lyrics retrieval not done yet")
    }

}
