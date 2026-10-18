// MOCK fixture scene 5: weak signal -> adapt bitrate, smooth jitter.
import React from 'react';
import {interpolate} from 'remotion';
import {Box, COLORS, Label, findWord, interior, progress} from './scene-kit';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  const {frame} = props;
  const inner = interior(props);
  const weak = findWord(props, 'weak?');
  const adapts = findWord(props, 'adapts');
  const jitter = findWord(props, 'jitter,');
  const weakAt = weak ? weak.start : inner.start + 60;
  const adaptAt = adapts ? adapts.start : weakAt + 60;
  const jitterAt = jitter ? jitter.start : adaptAt + 30;
  const bars = interpolate(frame, [weakAt, weakAt + 12], [4, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const rate = interpolate(frame, [adaptAt, adaptAt + 20], [1, 0.45], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 0}}>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} style={{position: 'absolute', left: 80 + i * 70, top: 300 - i * 60, width: 50, height: 120 + i * 60, borderRadius: 10, background: i < Math.round(bars) ? COLORS.ink : COLORS.line, opacity: progress(frame, inner.start, 10)}} />
      ))}
      <Label x={40} y={440} width={360} align="center" color={COLORS.orange} opacity={progress(frame, weakAt, 10)}>Weak signal</Label>
      <Label x={480} y={120} width={440} color={COLORS.secondary} opacity={progress(frame, adaptAt, 10)}>Bitrate</Label>
      <div style={{position: 'absolute', left: 480, top: 190, width: 420, height: 60, borderRadius: 30, border: `4px solid ${COLORS.ink}`, opacity: progress(frame, adaptAt, 10)}}>
        <div style={{width: `${rate * 100}%`, height: '100%', borderRadius: 30, background: COLORS.blue}} />
      </div>
      <Box x={480} y={300} width={420} height={140} color={COLORS.green} label="Jitter buffer" sublabel="smooths gaps" opacity={progress(frame, jitterAt, 10)} />
      <Label x={0} y={600} width={936} align="center" color={COLORS.secondary} size={38} opacity={progress(frame, jitterAt + 30, 10)}>Less quality, call stays live</Label>
    </div>
  );
}
