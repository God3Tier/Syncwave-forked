use bytes::Bytes;

/*
 * TODO: Settle the part for the 
 */
#[derive(Default, Clone)]
pub struct Node {
    audio_stream: Bytes,
    lyrics_timestamp: Vec<(i32, String)>,
}

impl Node {
    pub fn new(audio_stream: Bytes, lyrics_timestamp: Vec<(i32, String)>) -> Self {
        Node {
            audio_stream,
            lyrics_timestamp,
        }
    }
}
