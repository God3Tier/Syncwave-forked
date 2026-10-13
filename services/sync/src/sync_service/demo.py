import io
import math
import struct
import wave
from functools import lru_cache


@lru_cache(maxsize=1)
def test_tone_wav() -> bytes:
    """Generate a short melody for local multi-browser synchronization tests."""
    sample_rate = 22_050
    notes = (261.63, 329.63, 392.00, 523.25, 392.00, 329.63, 293.66, 349.23)
    seconds_per_note = 0.5
    repeats = 4
    frames: list[bytes] = []
    for frequency in notes * repeats:
        sample_count = round(sample_rate * seconds_per_note)
        for index in range(sample_count):
            envelope = min(1.0, index / 300, (sample_count - index) / 600)
            sample = int(9_000 * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.append(struct.pack("<h", sample))

    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(frames))
    return output.getvalue()


DEMO_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SyncWave five-browser test</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { max-width: 760px; margin: 40px auto; padding: 0 20px; background: #10131a; color: #eef2ff; }
    button { padding: 12px 18px; border: 0; border-radius: 8px; font-weight: 700; cursor: pointer; }
    .card { background: #191f2b; border: 1px solid #30394a; border-radius: 12px; padding: 20px; }
    dl { display: grid; grid-template-columns: 180px 1fr; gap: 8px; }
    dt { color: #9eabc1; } dd { margin: 0; font-variant-numeric: tabular-nums; }
    #state { color: #75e6a4; font-weight: 800; }
    pre { min-height: 180px; white-space: pre-wrap; color: #b9c6dc; }
  </style>
</head>
<body>
  <h1>SyncWave device test</h1>
  <p>Arm this browser, then wait for all five participants to become ready.</p>
  <div class="card">
    <button id="arm">Connect &amp; arm audio</button>
    <dl>
      <dt>Participant</dt><dd id="participant">—</dd>
      <dt>State</dt><dd id="state">DISCONNECTED</dd>
      <dt>Clock offset</dt><dd id="offset">—</dd>
      <dt>Target server time</dt><dd id="target">—</dd>
      <dt>Measured start error</dt><dd id="start-error">—</dd>
      <dt>Last correction</dt><dd id="correction">—</dd>
    </dl>
    <pre id="log" aria-label="event log"></pre>
  </div>
<script>
const params = new URLSearchParams(location.search);
const slot = params.get('slot');
const jamId = params.get('jam_id') || (slot ? 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' : null);
const participantId = params.get('participant_id') || (slot ? `10000000-0000-4000-8000-00000000000${slot}` : null);
const token = params.get('token') || (slot ? 'local-sync-participant-token' : null);
const $ = id => document.getElementById(id);
$('participant').textContent = participantId || 'missing';
let socket, context, audioBuffer, source, seq = 0, generation = 0;
let clockOffsetMs = 0, roundTripDelayMs = 0, startErrorMs = null;
let pendingStartErrorMs = null, offsetSamples = [];
let heartbeatTimer, statusTimer, playbackAnchorContextTime = 0, playbackAnchorPositionMs = 0;
let playbackRate = 1;
const log = message => { $('log').textContent += `${new Date().toISOString()} ${message}\n`; };
const frame = (type, payload) => ({type, jam_id: jamId, seq: seq++, sent_at_ms: Date.now(), payload});
const setState = value => { $('state').textContent = value; document.body.dataset.state = value; };

async function loadTone() {
  const base = location.pathname.startsWith('/api/sync/') ? '/api/sync' : '';
  const response = await fetch(`${base}/demo/test-tone.wav`);
  audioBuffer = await context.decodeAudioData(await response.arrayBuffer());
  log(`test melody buffered (${audioBuffer.duration.toFixed(1)}s)`);
}

function sampleClock() {
  if (!socket || socket.readyState !== WebSocket.OPEN || offsetSamples.length >= 5) return;
  const sampleId = crypto.randomUUID();
  socket.send(JSON.stringify(frame('TIME_PING', {sample_id: sampleId, client_sent_ms: Date.now()})));
}

function currentPositionMs() {
  if (!context || playbackAnchorContextTime === 0) return playbackAnchorPositionMs;
  return Math.max(0, playbackAnchorPositionMs +
    (context.currentTime - playbackAnchorContextTime) * 1000 * playbackRate);
}

function reanchorPlayback(rate) {
  playbackAnchorPositionMs = currentPositionMs();
  playbackAnchorContextTime = context.currentTime;
  playbackRate = rate;
  if (source) source.playbackRate.setValueAtTime(rate, context.currentTime);
}

function startStatusReports() {
  clearInterval(statusTimer);
  statusTimer = setInterval(() => {
    if (!socket || socket.readyState !== WebSocket.OPEN || $('state').textContent !== 'PLAYING') return;
    const report = frame('PLAYBACK_STATUS', {
      generation,
      measured_server_time_ms: Math.round(Date.now() + clockOffsetMs),
      position_ms: Math.round(currentPositionMs()),
      buffering: false,
      clock_offset_ms: clockOffsetMs,
      round_trip_delay_ms: roundTripDelayMs,
      start_error_ms: pendingStartErrorMs
    });
    pendingStartErrorMs = null;
    socket.send(JSON.stringify(report));
  }, 1000);
}

function schedulePlayback(payload) {
  if (source) source.stop();
  source = context.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(context.destination);
  const serverNow = Date.now() + clockOffsetMs;
  const delayMs = Math.max(0, payload.target_server_time_ms - serverNow);
  const when = context.currentTime + delayMs / 1000;
  playbackAnchorContextTime = when;
  playbackAnchorPositionMs = payload.start_position_ms;
  playbackRate = payload.playback_rate || 1;
  source.playbackRate.value = playbackRate;
  const activeSource = source;
  source.onended = () => {
    if (source === activeSource && $('state').textContent === 'PLAYING') {
      clearInterval(statusTimer);
      setState('ENDED');
      log('test melody ended');
    }
  };
  source.start(when, payload.start_position_ms / 1000);
  $('target').textContent = String(payload.target_server_time_ms);
  setState('SCHEDULED');
  log(`PLAY_AT received; scheduling in ${Math.round(delayMs)}ms`);
  setTimeout(() => {
    const measuredServerTime = Date.now() + clockOffsetMs;
    const errorMs = Math.round(measuredServerTime - payload.target_server_time_ms);
    startErrorMs = errorMs;
    pendingStartErrorMs = errorMs;
    $('start-error').textContent = `${errorMs} ms`;
    document.body.dataset.startErrorMs = String(errorMs);
    setState('PLAYING');
    log(`playback started; measured timer error ${errorMs}ms`);
    startStatusReports();
  }, delayMs);
}

function schedulePause(payload) {
  const serverNow = Date.now() + clockOffsetMs;
  const delayMs = Math.max(0, payload.target_server_time_ms - serverNow);
  if (source) {
    try { source.stop(context.currentTime + delayMs / 1000); } catch (_) { /* already stopped */ }
  }
  $('target').textContent = String(payload.target_server_time_ms);
  setState('PAUSE_SCHEDULED');
  setTimeout(() => {
    playbackAnchorPositionMs = payload.position_ms;
    playbackAnchorContextTime = 0;
    setState('PAUSED');
    log(`paused at ${payload.position_ms}ms`);
  }, delayMs);
}

function scheduleSeek(payload) {
  if (payload.resume_playback) {
    schedulePlayback({
      target_server_time_ms: payload.target_server_time_ms,
      start_position_ms: payload.position_ms
    });
    return;
  }
  schedulePause(payload);
  log(`paused seek scheduled to ${payload.position_ms}ms`);
}

async function handle(message) {
  const data = JSON.parse(message.data);
  log(data.type);
  if (data.type === 'JOINED') {
    generation = data.payload.generation;
    setState(data.payload.state);
    sampleClock();
  } else if (data.type === 'TIME_PONG') {
    const t3 = Date.now();
    const p = data.payload;
    const offset = ((p.server_received_ms - p.client_sent_ms) + (p.server_sent_ms - t3)) / 2;
    const delay = (t3 - p.client_sent_ms) - (p.server_sent_ms - p.server_received_ms);
    offsetSamples.push({offset, delay});
    if (offsetSamples.length < 5) sampleClock();
    else {
      offsetSamples.sort((a, b) => a.delay - b.delay);
      const best = offsetSamples.slice(0, 3).map(sample => sample.offset).sort((a, b) => a - b);
      clockOffsetMs = best[1];
      roundTripDelayMs = offsetSamples[0].delay;
      $('offset').textContent = `${clockOffsetMs.toFixed(1)} ms`;
      log('clock sampling complete');
    }
  } else if (data.type === 'PREPARE') {
    generation = data.payload.generation;
    if (!audioBuffer) await loadTone();
    socket.send(JSON.stringify(frame('READY', {
      generation,
      buffered_duration_ms: Math.round(audioBuffer.duration * 1000),
      media_duration_ms: Math.round(audioBuffer.duration * 1000)
    })));
    setState('READY');
  } else if (data.type === 'PLAY_AT') {
    schedulePlayback(data.payload);
  } else if (data.type === 'PAUSE_AT') {
    schedulePause(data.payload);
  } else if (data.type === 'RESUME_AT') {
    schedulePlayback(data.payload);
  } else if (data.type === 'SEEK_TO') {
    scheduleSeek(data.payload);
  } else if (data.type === 'SYNC_CORRECTION') {
    $('correction').textContent = `${data.payload.method} (${data.payload.drift_ms}ms)`;
    const delayMs = Math.max(0, data.payload.apply_at_server_time_ms - (Date.now() + clockOffsetMs));
    if (data.payload.method === 'SEEK') {
      schedulePlayback({
        target_server_time_ms: data.payload.apply_at_server_time_ms,
        start_position_ms: data.payload.target_position_ms,
        playback_rate: 1
      });
    } else {
      setTimeout(() => {
        reanchorPlayback(data.payload.playback_rate);
        setTimeout(() => reanchorPlayback(1), data.payload.duration_ms);
      }, delayMs);
    }
  } else if (data.type === 'ERROR') {
    setState(`ERROR: ${data.payload.code}`);
  }
}

$('arm').addEventListener('click', async () => {
  if (!jamId || !participantId || !token) { setState('MISSING_QUERY_PARAMETERS'); return; }
  $('arm').disabled = true;
  context = new AudioContext();
  await context.resume();
  await loadTone();
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  const base = location.pathname.startsWith('/api/sync/') ? '/api/sync' : '';
  socket = new WebSocket(`${scheme}://${location.host}${base}/ws?jam_id=${jamId}&participant_id=${participantId}&token=${encodeURIComponent(token)}`);
  socket.onmessage = handle;
  socket.onopen = () => {
    heartbeatTimer = setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(frame('TIME_PING', {sample_id: crypto.randomUUID(), client_sent_ms: Date.now()})));
      }
    }, 15000);
  };
  socket.onclose = event => {
    clearInterval(heartbeatTimer);
    clearInterval(statusTimer);
    setState(`CLOSED:${event.code}`);
  };
  socket.onerror = () => setState('SOCKET_ERROR');
  setState('CONNECTING');
});
</script>
</body>
</html>
"""
