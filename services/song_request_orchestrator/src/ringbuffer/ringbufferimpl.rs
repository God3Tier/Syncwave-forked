use super::node;
use crate::webhook::{Webhook, client::WebHookClient};
use std::sync::Arc;
use tokio::sync::RwLock;

// These are constants that determine the song timing offsets in minutes
const OFFSETS: [f64; 5] = [1.5, 2.0, 3.0, 2.0, 1.5];

/*
 * The RingBuffer is a struct that holds the capacity buffer and the list of IDed songs, This allows
 * me to perform the song and whatever necessary request to retrieve the online playlist. This should have
 * an offset size of only 4 but I am ok to have it configurable via and env file
 */
pub struct RingBufferImpl {
    capacity: usize,
    buf: Box<[node::Node]>,
    song_ids: Box<[i32]>,
    // This is the index at which the song queue starts from
    position: usize,
    client: Arc<RwLock<WebHookClient>>,
}

impl RingBufferImpl {
    pub fn new(capacity: usize, song_ids: Box<[i32]>, client: Arc<RwLock<WebHookClient>>) -> Self {
        // TODO: Initialise the songs with the predetermined songs from the ids
        RingBufferImpl {
            capacity,
            buf: vec![node::Node::default(); capacity].into_boxed_slice(),
            song_ids,
            position: 0,
            client,
        }
    }
}

impl super::RingBuffer for RingBufferImpl {
    async fn next_song(&mut self) {
        
    }

    async fn prev_song(&mut self) {
      
    }

}
