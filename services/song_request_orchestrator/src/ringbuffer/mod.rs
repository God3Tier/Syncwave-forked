mod node;
mod ringbufferimpl;

/*
 * Figure out the commands for this sliding window thing
 */
pub trait RingBuffer {
    async fn next_song(&mut self); 
    async fn prev_song(&mut self);
}
