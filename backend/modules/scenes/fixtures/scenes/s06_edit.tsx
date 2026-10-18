// MOCK fixture edit of scene 6 ("make the packet diagram clearer"):
// the takeaway as a labelled packet flow; same slot, timing and audio.
import React from 'react';
import {Arrow, COLORS, ClaimTag, Icon, Label, Packet, Svg, findWord, interior, progress} from './scene-kit';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  const {frame} = props;
  const inner = interior(props);
  const sig = findWord(props, 'Signaling');
  const media = findWord(props, 'media');
  const enc = findWord(props, 'encryption');
  const sigAt = Math.max(inner.start, sig ? sig.start : inner.start + 60);
  const mediaAt = Math.max(inner.start, media ? media.start : sigAt + 40);
  const encAt = Math.max(inner.start, enc ? enc.start : mediaAt + 40);
  const loop = (start: number, period: number) => (frame < start ? 0 : ((frame - start) % period) / period);
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <Icon kind="phone" x={0} y={330} size={200} opacity={progress(frame, inner.start, 10)} />
      <Icon kind="phone" x={736} y={330} size={200} opacity={progress(frame, inner.start, 10)} />
      <Icon kind="server" x={403} y={40} size={130} color={COLORS.blue} opacity={progress(frame, sigAt, 10)} />
      <Svg>
        <Arrow from={{x: 170, y: 340}} to={{x: 420, y: 170}} progress={progress(frame, sigAt, 12)} color={COLORS.blue} dashed />
        <Arrow from={{x: 516, y: 170}} to={{x: 766, y: 340}} progress={progress(frame, sigAt + 6, 12)} color={COLORS.blue} dashed />
        <Arrow from={{x: 190, y: 430}} to={{x: 746, y: 430}} progress={progress(frame, mediaAt, 14)} color={COLORS.green} width={10} />
        {frame >= mediaAt + 14 && <Packet from={{x: 200, y: 430}} to={{x: 736, y: 430}} progress={loop(mediaAt + 14, 36)} color={frame >= encAt ? COLORS.orange : COLORS.green} size={24} />}
      </Svg>
      <Label x={80} y={200} width={300} color={COLORS.blue} opacity={progress(frame, sigAt, 10)}>1 · Signaling</Label>
      <Label x={268} y={470} width={400} align="center" color={COLORS.green} opacity={progress(frame, mediaAt, 10)}>2 · Media packets</Label>
      <Label x={218} y={560} width={500} align="center" color={COLORS.orange} opacity={progress(frame, encAt, 10)}>3 · Encrypted end to end</Label>
      <ClaimTag context={props.context} ids={['c006']} x={0} y={700} opacity={progress(frame, encAt + 20, 10)} />
    </div>
  );
}
