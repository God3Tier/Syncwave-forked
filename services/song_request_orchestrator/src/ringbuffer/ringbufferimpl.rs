use super::{errors::RingBufferError, node};
use crate::webhook::Webhook;
use actix_web::rt;
use std::sync::Arc;
use tokio::sync::RwLock;

// How long (in minutes) each buffer slot must hold. Slots run from the song
// furthest ahead (+4) at slot 0 down to the song furthest behind (-4) at the
// last slot; `CURRENT_SLOT` holds the song being played. Mirrors plan.md §5
// "Adaptive Circular Buffer":
//
//   Position:  -4   -3   -2   -1   CURRENT   +1   +2   +3   +4
//   Buffer:   30s  30s   2m   2m     3m      2m   2m  30s  30s
//
// `OFFSETS[slot]` is indexed by slot, so `OFFSETS[0]` is the +4 position and
// the last entry is the -4 position.
pub(super) const OFFSETS: [f64; 9] = [0.5, 0.5, 2.0, 2.0, 3.0, 2.0, 2.0, 0.5, 0.5];

// The slot that holds the currently playing song. Positions run from
// `+CURRENT_SLOT` at slot 0 down to `-CURRENT_SLOT` at the last slot.
pub(super) const CURRENT_SLOT: usize = 4;

/*
 * The RingBuffer is a struct that holds the capacity buffer and the list of IDed songs, This allows
 * me to perform the song and whatever necessary request to retrieve the online playlist. This should have
 * an offset size of only 4 but I am ok to have it configurable via and env file
 *
 * `C` is the webhook client used to fetch audio ranges and lyrics. It is kept
 * generic so tests can inject an in-memory client instead of hitting the
 * network.
 */
pub struct RingBufferImpl<C: Webhook + 'static> {
    capacity: usize,
    buf: Box<[node::Node]>,
    song_ids: Box<[i32]>,
    // This is the index at which the song queue starts from
    pub(super) curr_position: usize,
    client: Arc<RwLock<C>>,
}

impl<C: Webhook + 'static> RingBufferImpl<C> {
    pub fn new(capacity: usize, song_ids: Box<[i32]>, client: Arc<RwLock<C>>) -> Self {
        // The buffer is exactly the offset window from plan.md §5 (-4..+4).
        debug_assert_eq!(
            capacity,
            OFFSETS.len(),
            "buffer capacity must match the offset window (9 positions)"
        );

        // TODO: Initialise the songs with the predetermined songs from the ids
        RingBufferImpl {
            capacity,
            buf: vec![node::Node::default(); capacity].into_boxed_slice(),
            song_ids,
            curr_position: 0,
            client,
        }
    }

    /// Song id sitting in buffer slot `slot`, anchored on `curr_position`:
    /// slot `CURRENT_SLOT` is the current song, slot 0 is furthest ahead (+4)
    /// and the last slot is furthest behind (-4). Returns `None` if there are
    /// no songs to place yet.
    pub(super) fn song_id_at(&self, slot: usize) -> Option<i32> {
        if self.song_ids.is_empty() {
            return None;
        }

        // Slot 0 is +4, so a slot's position is CURRENT_SLOT - slot.
        let position = CURRENT_SLOT as isize - slot as isize;
        let index = (self.curr_position as isize + position)
            .rem_euclid(self.song_ids.len() as isize) as usize;
        Some(self.song_ids[index])
    }

    /// Refills the window after a rotation. `enter_slot` is the position whose
    /// song is new to the window: it is built from scratch with `get_song_node`
    /// (first audio chunk + complete lyrics — the only lyrics request per song).
    /// Every other node only ever grows audio to its position's required chunk.
    ///
    /// All requests are spawned first, then all awaited before anything is
    /// applied, so one failure does not abandon the other in-flight calls.
    async fn fill_window(&mut self, enter_slot: usize) -> Result<(), RingBufferError> {
        // The rotated-in slot still holds the evicted song's node. Clear it so a
        // failed fetch leaves an empty node rather than stale audio.
        self.buf[enter_slot] = node::Node::default();

        let Some(entering_id) = self.song_id_at(enter_slot) else {
            return Ok(());
        };

        // New song: first audio chunk plus its complete lyrics.
        let client = self.client.clone();
        let new_node_task = rt::spawn(get_song_node(client, entering_id, 0.0, OFFSETS[enter_slot]));

        // Every other node only ever needs more audio.
        let mut pending = Vec::new();
        for (slot, &required) in OFFSETS.iter().enumerate().take(self.buf.len()) {
            if slot == enter_slot {
                continue;
            }
            let buffered = self.buf[slot].duration();
            if buffered >= required {
                // Already holds at least this position's required chunk.
                continue;
            }
            let Some(song_id) = self.song_id_at(slot) else {
                continue;
            };
            let missing = required - buffered;
            let client = self.client.clone();

            // Fetch only what is missing: [buffered, required).
            let task = rt::spawn(async move {
                client
                    .read()
                    .await
                    .retrieve_song_by_timestamp(song_id, buffered, required)
                    .await
            });

            pending.push((slot, missing, task));
        }

        // Wait for the new node and every extension to finish before applying.
        let new_node = new_node_task.await;
        let mut completed = Vec::with_capacity(pending.len());
        for (slot, duration, task) in pending {
            completed.push((slot, duration, task.await));
        }

        // Apply: place the freshly built node, then append audio to the rest.
        self.buf[enter_slot] = new_node??;
        for (slot, duration, joined) in completed {
            self.buf[slot].extend_song(joined??, duration);
        }

        Ok(())
    }
}

/*
 * Builds a single ring buffer node by fetching every piece of remote data it
 * needs. Each webhook call is spawned as its own non-blocking task on the
 * actix runtime, so the calls run concurrently instead of one after the other.
 *
 * To add another API call later:
 *   1. Clone `client` into a new handle and `rt::spawn` the call in the
 *      "kick off" section below.
 *   2. Await its handle in the "collect" section and fold the value into the
 *      node.
 * The two sections are separate on purpose: awaiting has to happen after every
 * task has been spawned, otherwise the calls stop being concurrent.
 */
async fn get_song_node<C: Webhook + 'static>(
    client: Arc<RwLock<C>>,
    next_id: i32,
    start_time: f64,
    end_time: f64,
) -> Result<node::Node, RingBufferError> {
    // Kick off every request for this node.
    let audio_client = client.clone();
    let audio_task = rt::spawn(async move {
        audio_client
            .read()
            .await
            .retrieve_song_by_timestamp(next_id, start_time, end_time)
            .await
    });

    let lyrics_client = client.clone();
    let lyrics_task =
        rt::spawn(async move { lyrics_client.read().await.retrieve_lyrics(next_id).await });

    // Collect the results. Every task is already running by this point, so the
    // awaits below only wait for work that is already in flight.
    let bytes_stream = audio_task.await??;
    let lyrics = lyrics_task.await??;

    // The webhook reports lyric timestamps as whole seconds, the node stores
    // them as fractional seconds.
    let lyrics_timestamp: Vec<(f64, String)> = lyrics
        .into_iter()
        .map(|(timestamp, line)| (timestamp as f64, line))
        .collect();

    // Record how much audio we now hold (end - start) so the node reports the
    // right duration and future extensions fetch the correct next range.
    Ok(node::Node::new(
        bytes_stream,
        lyrics_timestamp,
        end_time - start_time,
    ))
}

impl<C: Webhook + 'static> super::RingBuffer for RingBufferImpl<C> {
    async fn next_song(&mut self) -> Result<node::Node, RingBufferError> {
        if self.buf.is_empty() || self.song_ids.is_empty() {
            return Ok(node::Node::default());
        }

        // Advance one song, wrapping back to the first once the playlist ends.
        self.curr_position += 1;
        if self.curr_position >= self.song_ids.len() {
            self.curr_position = 0;
        }

        // Shift every song one slot to the right; slot 0 is emptied for the
        // newly relevant song (the one now furthest ahead, +4).
        self.buf.rotate_right(1);
        let enter_slot = 0;

        self.fill_window(enter_slot).await?;
        Ok(self.buf[enter_slot].clone())
    }

    async fn prev_song(&mut self) -> Result<node::Node, RingBufferError> {
        if self.buf.is_empty() || self.song_ids.is_empty() {
            return Ok(node::Node::default());
        }

        // Step back one song, wrapping to the last when at the start.
        if self.curr_position == 0 {
            self.curr_position = self.song_ids.len() - 1;
        } else {
            self.curr_position -= 1;
        }

        // Shift every song one slot to the left; the last slot is emptied for
        // the newly relevant song (the one now furthest behind, -4).
        self.buf.rotate_left(1);
        let enter_slot = self.buf.len() - 1;

        self.fill_window(enter_slot).await?;
        Ok(self.buf[enter_slot].clone())
    }
}
