// MOCK fixture scene 4: end-to-end encryption; relays forward unreadable packets.
import React from 'react';
import {COLORS, Icon, Label, Packet, Svg, findWord, interior, progress} from './scene-kit';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  const {frame} = props;
  const inner = interior(props);
  const enc = findWord(props, 'encrypted,');
  const cannot = findWord(props, 'cannot');
  const encAt = enc ? enc.start : inner.start + 100;
  const cannotAt = cannot ? cannot.start : encAt + 40;
  const t = (start: number, period: number) => (frame < start ? 0 : ((frame - start) % period) / period);
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <Icon kind="phone" x={10} y={360} size={190} opacity={progress(frame, inner.start, 10)} />
      <Icon kind="server" x={403} y={380} size={130} color={COLORS.secondary} opacity={progress(frame, inner.start + 6, 10)} />
      <Icon kind="phone" x={736} y={360} size={190} opacity={progress(frame, inner.start, 10)} />
      <Svg>
        <line x1={190} y1={450} x2={746} y2={450} stroke={COLORS.line} strokeWidth={6} />
        {frame >= encAt && <Packet from={{x: 190, y: 450}} to={{x: 746, y: 450}} progress={t(encAt, 40)} color={COLORS.blue} label="E2E" />}
      </Svg>
      <Icon kind="lock" x={130} y={180} size={120} color={COLORS.blue} opacity={progress(frame, encAt, 10)} />
      <Icon kind="lock" x={686} y={180} size={120} color={COLORS.blue} opacity={progress(frame, encAt + 6, 10)} />
      <Label x={218} y={60} width={500} align="center" color={COLORS.blue} opacity={progress(frame, encAt, 10)}>End-to-end encrypted</Label>
      <Label x={268} y={560} width={400} align="center" color={COLORS.secondary} opacity={progress(frame, cannotAt, 10)}>Relay can’t read it</Label>
    </div>
  );
}
