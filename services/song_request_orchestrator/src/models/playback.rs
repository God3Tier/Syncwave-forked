use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Deserialize, Serialize, Default)]
pub struct WaveformData {
    pub duration_ms: Option<u64>,
    pub peaks: Vec<f32>,
    #[serde(default)]
    pub timestamps_ms: Vec<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LyricLine {
    pub time_seconds: f64,
    pub text: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct BufferedSong {
    pub song_id: Uuid,
    pub audio_base64: String,
    pub buffered_minutes: f64,
    pub lyrics: Vec<LyricLine>,
    pub waveform: WaveformData,
}

#[derive(Debug, Clone, Serialize)]
pub struct PlaylistPlayback {
    pub playlist_id: Uuid,
    pub current_position: usize,
    pub buffers: Vec<BufferedSong>,
}
