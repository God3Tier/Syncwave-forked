use super::{
    RingBuffer,
    ringbufferimpl::{OFFSETS, RingBufferImpl},
};
use crate::models::playback::WaveformData;
use crate::webhook::{Webhook, errors::WebHookError};
use bytes::Bytes;
use std::sync::{Arc, Mutex};
use tokio::sync::RwLock;
use uuid::Uuid;

/*
 * Tests for the ring buffer that maintains the shared jam song arrangement.
 *
 * The arrangement mirrors plan.md §5 "Adaptive Circular Buffer":
 *
 *   Position:  -4   -3   -2   -1   CURRENT   +1   +2   +3   +4
 *   Buffer:   30s  30s   2m   2m     3m      2m   2m  30s  30s
 *
 * Slot 0 holds the song furthest ahead (+4), slot CURRENT_SLOT (4) holds the
 * song being played, and the last slot (8) holds the song furthest behind
 * (-4). `curr_position` indexes into `song_ids`, and slot `s` maps to the
 * playlist index `(curr_position + CURRENT_SLOT - s) % len`.
 *
 * When the current song advances the whole window slides forward by one song:
 * the old current song falls back toward the -4 side and a new song enters at
 * +4. `fill_window` only fetches audio a slot is still missing, so nearby
 * chunks are preserved and anything no longer useful is not re-requested.
 */

const TEST_PLAYLIST: [Uuid; 10] = [
    Uuid::from_u128(1),
    Uuid::from_u128(2),
    Uuid::from_u128(3),
    Uuid::from_u128(4),
    Uuid::from_u128(5),
    Uuid::from_u128(6),
    Uuid::from_u128(7),
    Uuid::from_u128(8),
    Uuid::from_u128(9),
    Uuid::from_u128(10),
];

// Runs an async test body inside an actix runtime so that the `rt::spawn`
// calls inside `fill_window` / `get_song_node` have a runtime to run on.
fn run_async<F>(future: F) -> F::Output
where
    F: std::future::Future,
{
    let sys = actix_web::rt::System::new();
    sys.block_on(future)
}

/// In-memory webhook used in tests. Records every audio request and returns
/// canned (empty) bytes, so no real network is needed to test arrangement.
struct MockWebhook {
    audio_calls: Arc<Mutex<Vec<(Uuid, f64, f64)>>>,
}

impl MockWebhook {
    fn new() -> Self {
        Self {
            audio_calls: Arc::new(Mutex::new(Vec::new())),
        }
    }
}

impl Webhook for MockWebhook {
    async fn retrieve_playlist_song_ids(
        &self,
        _playlist_id: Uuid,
    ) -> Result<Vec<Uuid>, WebHookError> {
        Ok(TEST_PLAYLIST.to_vec())
    }

    async fn retrieve_song_by_timestamp(
        &self,
        id: Uuid,
        start_time: f64,
        end_time: f64,
    ) -> Result<Bytes, WebHookError> {
        self.audio_calls
            .lock()
            .unwrap()
            .push((id, start_time, end_time));
        Ok(Bytes::new())
    }

    async fn retrieve_lyrics(&self, _id: Uuid) -> Result<Vec<(i64, String)>, WebHookError> {
        Ok(Vec::new())
    }

    async fn retrieve_waveform(&self, _id: Uuid) -> Result<WaveformData, WebHookError> {
        Ok(WaveformData::default())
    }
}

/// Builds a buffer over `TEST_PLAYLIST` backed by the mock webhook and returns
/// both the buffer and a handle to the recorded audio calls.
fn mock_buffer() -> (
    RingBufferImpl<MockWebhook>,
    Arc<Mutex<Vec<(Uuid, f64, f64)>>>,
) {
    let mock = MockWebhook::new();
    let calls = Arc::clone(&mock.audio_calls);
    let client: Arc<RwLock<MockWebhook>> = Arc::new(RwLock::new(mock));
    let buffer = RingBufferImpl::new(OFFSETS.len(), Box::new(TEST_PLAYLIST), client);
    (buffer, calls)
}

#[test]
fn offsets_match_plan_md() {
    // plan.md §5: -4/-3 = 30s, -2/-1 = 2m, CURRENT = 3m, +1/+2 = 2m, +3/+4 = 30s
    assert_eq!(
        super::ringbufferimpl::OFFSETS,
        [0.5, 0.5, 2.0, 2.0, 3.0, 2.0, 2.0, 0.5, 0.5]
    );
    assert_eq!(super::ringbufferimpl::CURRENT_SLOT, 4);
}

#[test]
fn song_id_at_anchors_on_current_song() {
    let (mut buffer, _calls) = mock_buffer();
    buffer.curr_position = 4; // song 5 is the current song

    // The CURRENT_SLOT holds the current song.
    assert_eq!(buffer.song_id_at(4), Some(Uuid::from_u128(5)));
    // Slot 0 is +4 (furthest ahead), the last slot is -4 (furthest behind).
    assert_eq!(buffer.song_id_at(0), Some(Uuid::from_u128(9)));
    assert_eq!(buffer.song_id_at(8), Some(Uuid::from_u128(1)));
    // Immediate neighbours ahead (+1) and behind (-1).
    assert_eq!(buffer.song_id_at(3), Some(Uuid::from_u128(6)));
    assert_eq!(buffer.song_id_at(5), Some(Uuid::from_u128(4)));
}

#[test]
fn song_id_at_wraps_around_playlist_edges() {
    let (mut buffer, _calls) = mock_buffer();
    buffer.curr_position = 0; // song 1 is the current song

    assert_eq!(buffer.song_id_at(4), Some(Uuid::from_u128(1)));
    assert_eq!(buffer.song_id_at(0), Some(Uuid::from_u128(5))); // +4 wraps forward
    assert_eq!(buffer.song_id_at(8), Some(Uuid::from_u128(7))); // -4 wraps backward
}

#[test]
fn next_song_advances_arrangement_by_one_song() {
    let (mut buffer, calls) = mock_buffer();
    buffer.curr_position = 0; // song 1 is current

    let entering = run_async(buffer.next_song()).unwrap();
    assert!(entering.duration() > 0.0);

    // The window slides forward by one song: song 2 is now current and the old
    // current song (1) falls back to the -1 position.
    assert_eq!(buffer.curr_position, 1);
    assert_eq!(buffer.song_id_at(4), Some(Uuid::from_u128(2))); // current
    assert_eq!(buffer.song_id_at(5), Some(Uuid::from_u128(1))); // old current now at -1
    assert_eq!(buffer.song_id_at(3), Some(Uuid::from_u128(3))); // +1
    assert_eq!(buffer.song_id_at(0), Some(Uuid::from_u128(6))); // +4: the newly entering song
    assert_eq!(buffer.song_id_at(8), Some(Uuid::from_u128(8))); // -4

    // The entering song at +4 is fetched from the very beginning of the track.
    let recorded = calls.lock().unwrap().clone();
    assert!(
        recorded
            .iter()
            .any(|(id, start, end)| *id == Uuid::from_u128(6) && *start == 0.0 && *end == 0.5),
        "entering +4 song should be fetched from [0, 0.5], got {recorded:?}"
    );
}

#[test]
fn prev_song_steps_back_by_one_song() {
    let (mut buffer, _calls) = mock_buffer();
    buffer.curr_position = 0; // song 1 is current

    run_async(buffer.prev_song()).unwrap();

    // The window slides backward by one song (wrapping to the playlist end):
    // song 10 is now current and the old current song (1) moves to +1.
    assert_eq!(buffer.curr_position, 9);
    assert_eq!(buffer.song_id_at(4), Some(Uuid::from_u128(10))); // current
    assert_eq!(buffer.song_id_at(3), Some(Uuid::from_u128(1))); // old current now at +1
    assert_eq!(buffer.song_id_at(0), Some(Uuid::from_u128(4))); // +4
    assert_eq!(buffer.song_id_at(8), Some(Uuid::from_u128(6))); // -4
}

#[test]
fn fill_window_grows_only_what_is_needed() {
    let (mut buffer, calls) = mock_buffer();
    buffer.curr_position = 0;

    // First advance: every slot is empty, so all 9 positions are fetched.
    run_async(buffer.next_song()).unwrap();
    let first_count = calls.lock().unwrap().len();
    assert_eq!(first_count, 9);

    // Second advance: nodes already holding enough audio for their position are
    // reused. Only the entering song (+4) and any song promoted to a position
    // that requires more audio are fetched again.
    run_async(buffer.next_song()).unwrap();
    let second_count = calls.lock().unwrap().len() - first_count;

    // The entering song (+4 = song 7) must be fetched from the beginning.
    let recorded = calls.lock().unwrap().clone();
    assert!(
        recorded
            .iter()
            .any(|(id, start, end)| *id == Uuid::from_u128(7) && *start == 0.0 && *end == 0.5),
        "entering +4 song should be fetched from [0, 0.5], got {recorded:?}"
    );

    // No position is completely re-fetched: only targeted fetches occur.
    assert_eq!(
        second_count, 3,
        "expected targeted refetches, got {second_count}"
    );
}

#[test]
fn empty_playlist_returns_default_node() {
    let mock = MockWebhook::new();
    let client: Arc<RwLock<MockWebhook>> = Arc::new(RwLock::new(mock));
    let mut buffer = RingBufferImpl::new(OFFSETS.len(), Box::new([]), client);

    let node = run_async(buffer.next_song()).unwrap();
    assert_eq!(node.duration(), 0.0);
    // With no songs there is nothing to advance past.
    assert_eq!(buffer.curr_position, 0);
}
