use super::node;
use crate::webhook::{Webhook, client::WebHookClient}; 

// These are constants that determine the song timing offsets in minutes
const OFFSET_0: f64 = 3.0; 
const OFFSET_1: f64 = 2.0; 
const OFFSET_2: f64 = 1.5; 
const OFFSET_3: f64 = 1.0; 

/*
 * The RingBuffer is a struct that holds the capacity buffer and the list of IDed songs, This allows 
 * me to perform the song and whatever necessary request to retrieve the online playlist. This should have 
 * an offset size of only 4 but I am ok to have it configurable via and env file
 */
pub struct RingBuffer {
    capacity: usize,
    buf: Box<[node::Node]>,
    song_ids: Box<[i32]>,
    // This is the index at which the song queue starts from
    position: usize, 
    client: WebHookClient, 
}

impl RingBuffer {
    pub fn new(capacity: usize, song_ids: Box<[i32]>, client: WebHookClient) -> Self {
    	// TODO: Initialise the songs with the predetermined songs from the ids
        RingBuffer {
            capacity,
            buf: vec![node::Node::default(); capacity].into_boxed_slice(), 
            song_ids,
            position: 0, 
            client
        }
    }
}


