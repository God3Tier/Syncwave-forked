import { useEffect, useRef } from 'react';
import { usePlayer } from '../player/context';
import { productColors } from '../theme';

// Bars per side. The picture is mirrored like a music video's: the bass is in
// the middle and higher notes spread out to both edges, spaced evenly in pitch
// (log frequency) over the range music lives in.
const BARS = 40;
const MIN_HZ = 60;
const MAX_HZ = 10_000;

/**
 * Live frequency bars for the song that is playing, the kind music videos
 * show, mirrored left to right and top to bottom. Unlike <Waveform>, which draws the whole song from the Waveform
 * Service's peaks, this reads the player's Web Audio analyser every frame.
 * When playback stops the bars fall back to rest.
 */
export function Visualizer({
  active,
  height = 160,
  source,
}: {
  active: boolean;
  height?: number;
  source?: () => AnalyserNode | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const levels = useRef(new Float32Array(BARS));
  const { analyser } = usePlayer();

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    const node = active ? (source ?? analyser)() : null;
    const bins = new Uint8Array(node?.frequencyBinCount ?? 0);
    const hzPerBin = node ? node.context.sampleRate / 2 / bins.length : 1;
    // edges[i]..edges[i + 1] are the FFT bins behind bar i.
    const edges = Array.from({ length: BARS + 1 }, (_, i) =>
      Math.min(bins.length - 1, Math.round((MIN_HZ * (MAX_HZ / MIN_HZ) ** (i / BARS)) / hzPerBin)),
    );
    const current = levels.current;
    let frame = 0;

    const draw = () => {
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      if (canvas.width !== Math.round(width * ratio)) canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, height);

      if (node) node.getByteFrequencyData(bins);
      let moving = false;
      for (let i = 0; i < BARS; i++) {
        let peak = 0;
        if (node) for (let bin = edges[i]; bin <= Math.max(edges[i], edges[i + 1] - 1); bin++) peak = Math.max(peak, bins[bin]);
        // Higher notes carry less energy; tilt them up so the whole width moves.
        const target = Math.min(1, (peak / 255) * (0.8 + (0.5 * i) / BARS));
        current[i] = Math.max(target, current[i] * 0.9);
        if (current[i] > 0.01) moving = true;
      }

      const step = width / (BARS * 2);
      const barWidth = step * 0.6;
      const centreX = width / 2;
      const centreY = height / 2;
      const gradient = ctx.createLinearGradient(0, 0, width, 0);
      gradient.addColorStop(0, productColors.secondary);
      gradient.addColorStop(0.5, productColors.primary);
      gradient.addColorStop(1, productColors.secondary);
      ctx.fillStyle = gradient;
      ctx.shadowColor = productColors.secondary;
      ctx.shadowBlur = 10;
      current.forEach((level, i) => {
        const barHeight = Math.max(3, level * (height - 12));
        const offset = i * step + (step - barWidth) / 2;
        ctx.beginPath();
        ctx.roundRect(centreX + offset, centreY - barHeight / 2, barWidth, barHeight, barWidth / 2);
        ctx.roundRect(centreX - offset - barWidth, centreY - barHeight / 2, barWidth, barHeight, barWidth / 2);
        ctx.fill();
      });
      ctx.shadowBlur = 0;

      if (node || moving) frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [active, analyser, height, source]);

  return <canvas ref={canvasRef} style={{ height }} className="block w-full" role="img" aria-label="Audio visualiser" />;
}
