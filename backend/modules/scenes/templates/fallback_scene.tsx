// Deterministic fallback scene (generation_mode "fallback"). Topic-agnostic:
// everything it shows is read from the scene's own dialogue, claims, image
// and measured word timings. Same source for every scene slot.
import React from 'react';
import {interpolate} from 'remotion';
import {Box, COLORS, ClaimTag, FONT, Label, SceneImage, W, interior, pop, progress, sceneImage, sceneTurns, shorten} from './scene-kit';
import type {SceneProps} from './scene-kit';

const splitPoints = (text: string): string[] => {
  const parts = text
    .split(/(?<=[,.;:?!])\s+|\s+(?:and|so|but|or)\s+/i)
    .map((p) => p.replace(/[,.;:]+$/, '').trim())
    .filter((p) => p.split(' ').length >= 2);
  return parts.slice(0, 3);
};

export default function Scene(props: SceneProps) {
  const {frame} = props;
  const turns = sceneTurns(props);
  const [first, second] = turns;
  const inner = interior(props);
  const hasImage = sceneImage(props) !== null;
  const qStart = Math.max(inner.start, first ? first.start : inner.start);
  const aStart = Math.max(inner.start, second ? second.start : inner.start);
  const points = second ? splitPoints(second.turn.text) : [];
  const words = second ? second.words : [];
  const pointStarts = points.map((p, i) => {
    const head = p.split(' ')[0].toLowerCase().replace(/[^a-z0-9]/g, '');
    const w = words.find((x) => x.text.toLowerCase().replace(/[^a-z0-9]/g, '') === head && x.start >= aStart);
    return w ? w.start : aStart + i * 20;
  });
  const cardW = hasImage ? 600 : W;
  return (
    <div style={{position: 'absolute', inset: 0, fontFamily: FONT}}>
      {first && (
        <Box
          x={0}
          y={0}
          width={W}
          height={200}
          color={COLORS.blue}
          fill="#EFF6FF"
          opacity={progress(frame, qStart, 10)}
          scale={0.92 + 0.08 * pop(frame, qStart)}
          label={shorten(first.turn.text, 70)}
        />
      )}
      {points.map((p, i) => {
        const s = pointStarts[i];
        const active = frame >= s && (i + 1 >= points.length || frame < pointStarts[i + 1]);
        return (
          <Box
            key={i}
            x={0}
            y={240 + i * 150}
            width={cardW}
            height={130}
            color={active ? COLORS.green : COLORS.line}
            fill={COLORS.background}
            highlight={active ? 1 : 0}
            opacity={progress(frame, s, 10)}
            label={shorten(p, 48)}
          />
        );
      })}
      {hasImage && <SceneImage scene={props} x={630} y={240} width={306} height={420} opacity={progress(frame, aStart, 12)} />}
      {second && (
        <ClaimTag context={props.context} ids={second.turn.claim_ids} x={0} y={720} opacity={interpolate(frame, [aStart + 20, aStart + 32], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})} />
      )}
      {!first && <Label x={0} y={300} width={W} align="center" color={COLORS.secondary}>Scene {props.slot.index}</Label>}
    </div>
  );
}
