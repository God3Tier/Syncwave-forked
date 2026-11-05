// Response shapes of the browser-facing services. Field names follow the
// OpenAPI specs in contracts/api/ and the service source for those without one.

export type StageStatus = 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED';
export type ProcessingStatus = 'PROCESSING' | 'PARTIAL' | 'READY' | 'FAILED';

export interface Song {
  song_id: string;
  title: string;
  artist: string;
  duration_ms: number | null;
  audio_reference: string;
  lyrics_status: StageStatus;
  waveform_status: StageStatus;
  processing_status: ProcessingStatus;
  created_at: string;
  updated_at: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface ServiceError {
  code: string;
  message: string;
}

export interface LyricLine {
  time_ms: number;
  text: string;
}

export interface Lyrics {
  song_id: string;
  status: 'PROCESSING' | 'READY' | 'FAILED';
  line_count: number;
  lines: LyricLine[];
  error?: ServiceError;
  updated_at: string;
}

export interface Waveform {
  song_id: string;
  status: 'PROCESSING' | 'READY' | 'FAILED';
  points: number;
  duration_ms: number | null;
  peaks: number[];
  error?: ServiceError;
  updated_at: string;
}

export interface WaveformBands {
  song_id: string;
  status: 'PROCESSING' | 'READY' | 'FAILED';
  frame_rate: number | null;
  frame_count: number;
  band_count: number;
  band_edges_hz: number[];
  levels: string;
  error?: ServiceError;
  updated_at: string;
}

export interface PlaylistSong {
  song_id: string;
  position: number;
}

export interface PlaylistSummary {
  playlist_id: string;
  owner_id: string;
  name: string;
  song_count: number;
  created_at: string;
  updated_at: string;
}

export interface Playlist extends PlaylistSummary {
  songs: PlaylistSong[];
}

export type WeatherCondition = 'CLEAR' | 'CLOUDY' | 'RAIN' | 'STORM' | 'SNOW' | 'FOG' | 'OTHER';

export interface Recommendation {
  song_id: string;
  title: string;
  artist: string;
  duration_ms: number;
  reason: 'WEATHER_MATCH' | 'GENERAL';
}

export interface Recommendations {
  items: Recommendation[];
  weather_used: boolean;
  weather: { condition: WeatherCondition; temperature_c: number } | null;
}

export interface SearchResult {
  song_id: string;
  title: string;
  artist: string;
}

export interface StreamInfo {
  song_id: string;
  stream_url: string;
  supports_ranges: boolean;
  manifest_url: string;
}

export interface StreamChunk {
  index: number;
  start_ms: number;
  duration_ms: number;
  start_sample: number;
  end_sample: number;
  url: string;
}

export interface StreamManifest {
  song_id: string;
  media_version: string;
  duration_ms: number;
  chunk_duration_ms: number;
  format: string;
  sample_rate_hz: number;
  channels: number;
  bits_per_sample: number;
  chunks: StreamChunk[];
}

export interface UploadReceipt {
  song_id: string;
  event_id: string;
  status: string;
  title: string;
  artist: string;
  mood: string | null;
  duration_ms: number | null;
  audio_reference: string;
  lyrics_reference: string | null;
  publish_attempts: number;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
  published_at: string | null;
}

export type JamState = 'IDLE' | 'PREPARING' | 'SCHEDULED' | 'PLAYING' | 'PAUSED' | 'ENDED';

export interface QueueItem {
  queue_item_id: string;
  song_id: string;
  added_by: string;
  position: number;
}

export interface Jam {
  jam_id: string;
  owner_id: string;
  participant_ids: string[];
  participants: Array<{ participant_id: string; username: string; role: 'OWNER' | 'MEMBER' }>;
  queue: QueueItem[];
  current_queue_item_id: string | null;
  sync_generation: number | null;
  state: JamState;
  lifecycle_state: 'ACTIVE' | 'ENDED';
  member_token: string | null;
  member_id: string | null;
}

export interface Readiness {
  generation: number;
  prepare_deadline_ms: number | null;
  timed_out: boolean;
  decision_required: boolean;
  ready_participant_ids: string[];
  unready_participant_ids: string[];
}
