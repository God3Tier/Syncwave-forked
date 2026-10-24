use errors::RingBufferError;

pub mod errors;
mod node;
mod ringbufferimpl;
pub use ringbufferimpl::{CURRENT_SLOT, OFFSETS, RingBufferImpl};

#[cfg(test)]
mod test;

/*
 * Figure out the commands for this sliding window thing
 */
pub trait RingBuffer {
    async fn next_song(&mut self) -> Result<node::Node, RingBufferError>;
    async fn prev_song(&mut self) -> Result<node::Node, RingBufferError>;
}
