mod node;
mod ringbufferimpl; 

/*
 * Figure out the commands for this sliding window thing
 */
pub trait RingBuffer {
	fn next_song(&self); 
	fn prev_song(&self); 
	
}