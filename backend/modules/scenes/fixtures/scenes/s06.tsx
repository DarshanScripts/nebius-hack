// MOCK fixture scene 6: takeaway - signaling, media path, encryption.
import React from 'react';
import {Box, COLORS, ClaimTag, findWord, interior, pop, progress} from './scene-kit';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  const {frame} = props;
  const inner = interior(props);
  const steps = [
    {word: 'Signaling', label: 'Signaling', sub: 'sets up the call', color: COLORS.blue},
    {word: 'media', label: 'Media path', sub: 'direct or relay', color: COLORS.green},
    {word: 'encryption', label: 'Encryption', sub: 'end to end', color: COLORS.orange},
  ];
  return (
    <div style={{position: 'absolute', inset: 0}}>
      {steps.map((s, i) => {
        const w = findWord(props, s.word);
        const at = Math.max(inner.start, w ? w.start : inner.start + 100 + i * 30);
        return <Box key={s.label} x={68} y={60 + i * 210} width={800} height={170} color={s.color} label={s.label} sublabel={s.sub} opacity={progress(frame, at, 10)} scale={0.9 + 0.1 * pop(frame, at)} />;
      })}
      <ClaimTag context={props.context} ids={['c006']} x={68} y={700} opacity={progress(frame, inner.start + 150, 10)} />
    </div>
  );
}
