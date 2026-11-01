import { useEffect, useRef } from 'react';

interface WaveformProps {
  peaks: number[];
  durationMs: number;
  positionMs: number;
  onSeek?: (ms: number) => void;
  height?: number;
  className?: string;
}

const PLAYED = '#ba9eff';
const UNPLAYED = 'rgba(58, 223, 250, 0.35)';
const PLAYHEAD = '#eae7f1';

/** Canvas waveform from the Waveform Service's peaks, with played portion and a playhead. */
export function Waveform({ peaks, durationMs, positionMs, onSeek, height = 120, className = '' }: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, width, height);

    const values = peaks.length ? peaks : new Array(120).fill(0.08);
    const step = width / values.length;
    const barWidth = Math.max(1, step * 0.6);
    const progress = durationMs > 0 ? Math.min(1, positionMs / durationMs) : 0;
    const playedX = progress * width;
    const mid = height / 2;

    values.forEach((peak, i) => {
      const x = i * step;
      const barHeight = Math.max(2, Math.min(1, peak) * (height - 8));
      ctx.fillStyle = x + barWidth <= playedX ? PLAYED : UNPLAYED;
      ctx.beginPath();
      ctx.roundRect(x, mid - barHeight / 2, barWidth, barHeight, barWidth / 2);
      ctx.fill();
    });

    if (durationMs > 0) {
      ctx.fillStyle = PLAYHEAD;
      ctx.shadowColor = PLAYED;
      ctx.shadowBlur = 8;
      ctx.fillRect(Math.max(0, playedX - 1), 0, 2, height);
      ctx.shadowBlur = 0;
    }
  }, [peaks, durationMs, positionMs, height]);

  const seekable = Boolean(onSeek) && durationMs > 0;
  const seekTo = (clientX: number) => {
    const canvas = canvasRef.current;
    if (!canvas || !onSeek) return;
    const rect = canvas.getBoundingClientRect();
    onSeek(Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)) * durationMs);
  };

  return (
    <canvas
      ref={canvasRef}
      style={{ height }}
      className={`block w-full ${seekable ? 'cursor-pointer' : ''} ${className}`}
      role={seekable ? 'slider' : 'img'}
      aria-label="Waveform"
      aria-valuemin={seekable ? 0 : undefined}
      aria-valuemax={seekable ? Math.round(durationMs / 1000) : undefined}
      aria-valuenow={seekable ? Math.round(positionMs / 1000) : undefined}
      tabIndex={seekable ? 0 : undefined}
      onClick={(event) => seekable && seekTo(event.clientX)}
      onKeyDown={(event) => {
        if (!seekable || !onSeek) return;
        if (event.key === 'ArrowRight') onSeek(Math.min(durationMs, positionMs + 5000));
        if (event.key === 'ArrowLeft') onSeek(Math.max(0, positionMs - 5000));
      }}
    />
  );
}
