// MOCK fixture scene 3: NAT/firewalls block direct paths; relays keep calls up.
import React from 'react';
import {Arrow, COLORS, Icon, Label, SceneImage, Svg, findWord, interior, pop, progress} from './scene-kit';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  const {frame} = props;
  const inner = interior(props);
  const fw = findWord(props, 'Firewalls');
  const relays = findWord(props, 'relays');
  const fwAt = fw ? fw.start : inner.start + 100;
  const relayAt = relays ? relays.start : fwAt + 50;
  const wall = pop(frame, fwAt);
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <SceneImage scene={props} x={228} y={0} width={480} height={300} opacity={progress(frame, inner.start, 12) * (1 - progress(frame, fwAt - 10, 10)) } />
      <Icon kind="phone" x={20} y={440} size={190} opacity={progress(frame, inner.start, 10)} />
      <Icon kind="phone" x={726} y={440} size={190} opacity={progress(frame, inner.start, 10)} />
      <Svg>
        <Arrow from={{x: 200, y: 540}} to={{x: 440, y: 540}} progress={progress(frame, inner.start + 20, 16)} color={COLORS.secondary} dashed />
        <rect x={448} y={420} width={40} height={240 * wall} fill={COLORS.orange} rx={8} />
        <Arrow from={{x: 190, y: 460}} to={{x: 420, y: 230}} progress={progress(frame, relayAt, 12)} color={COLORS.green} />
        <Arrow from={{x: 516, y: 230}} to={{x: 746, y: 460}} progress={progress(frame, relayAt + 8, 12)} color={COLORS.green} />
      </Svg>
      <Icon kind="server" x={403} y={100} size={130} color={COLORS.green} opacity={progress(frame, relayAt - 6, 10)} />
      <Label x={300} y={680} width={336} align="center" color={COLORS.orange} opacity={progress(frame, fwAt, 10)}>Firewall / NAT</Label>
      <Label x={560} y={140} width={360} color={COLORS.green} opacity={progress(frame, relayAt, 10)}>Relay keeps it up</Label>
    </div>
  );
}
