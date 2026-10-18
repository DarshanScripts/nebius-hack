// MOCK fixture scene 1: tapping call triggers signaling via servers.
import React from 'react';
import {Arrow, Box, COLORS, Icon, Label, Svg, findWord, interior, isActive, pop, progress, wordWindow} from './scene-kit';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  const {frame} = props;
  const inner = interior(props);
  const call = findWord(props, 'call');
  const signals = findWord(props, 'signals');
  const ring = findWord(props, 'ring');
  const tapAt = call ? call.start : inner.start;
  const sigAt = signals ? signals.start : inner.start + 120;
  const ringAt = ring ? ring.start : sigAt + 40;
  const ripple = progress(frame, tapAt, 18);
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <Icon kind="phone" x={40} y={300} size={220} color={COLORS.ink} opacity={progress(frame, inner.start, 10)} />
      <Icon kind="phone" x={676} y={300} size={220} color={COLORS.ink} opacity={progress(frame, inner.start + 6, 10)} />
      <Svg>
        <circle cx={150} cy={410} r={40 + 120 * ripple} fill="none" stroke={COLORS.blue} strokeWidth={6} opacity={ripple > 0 && ripple < 1 ? 1 - ripple : 0} />
        <Arrow from={{x: 230, y: 360}} to={{x: 400, y: 200}} progress={progress(frame, sigAt, 14)} color={COLORS.blue} />
        <Arrow from={{x: 536, y: 200}} to={{x: 706, y: 360}} progress={progress(frame, ringAt, 14)} color={COLORS.blue} />
      </Svg>
      <Icon kind="server" x={398} y={90} size={140} color={COLORS.blue} opacity={progress(frame, sigAt - 6, 10)} />
      <Label x={318} y={240} width={300} align="center" color={COLORS.blue} opacity={progress(frame, sigAt, 10)}>Signaling</Label>
      <Box x={636} y={560} width={300} height={110} color={COLORS.green} label="Ringing" opacity={progress(frame, ringAt + 8, 8)} scale={0.9 + 0.1 * pop(frame, ringAt + 8)} highlight={isActive(frame, wordWindow(props, 'd002_w013')) ? 1 : 0} />
      <Label x={0} y={560} width={300} align="center" color={COLORS.secondary} opacity={progress(frame, tapAt, 8)}>Tap “call”</Label>
    </div>
  );
}
