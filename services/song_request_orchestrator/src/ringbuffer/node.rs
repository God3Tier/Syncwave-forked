use bytes::{Bytes, BytesMut};

/*
 * TODO: Settle the part for the
 */
#[derive(Default, Clone)]
pub struct Node {
    audio_stream: BytesMut,
    lyrics_timestamp: Vec<(f64, String)>,
    current_time_stamp: f64,
}

impl Node {
    pub fn new(
        audio_stream: Bytes,
        lyrics_timestamp: Vec<(f64, String)>,
        current_time_stamp: f64,
    ) -> Self {
        Node {
            audio_stream: BytesMut::from(audio_stream),
            lyrics_timestamp,
            current_time_stamp,
        }
    }

    pub fn extend_song(&mut self, stream: Bytes, extended_duration: f64) {
        self.current_time_stamp += extended_duration;
        self.audio_stream.extend_from_slice(&stream)
    }

    /// How much audio this node currently holds, in the same units as the
    /// webhook offsets (minutes).
    pub fn duration(&self) -> f64 {
        self.current_time_stamp
    }
}
