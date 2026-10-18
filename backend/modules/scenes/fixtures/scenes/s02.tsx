// MOCK fixture scene 2: media goes direct (peer to peer) or via a relay.
import React from 'react';
import {Arrow, COLORS, Icon, Label, Packet, Svg, findWord, interior, progress} from './scene-kit';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  const {frame} = props;
  const inner = interior(props);
  const peer = findWord(props, 'peer');
  const relay = findWord(props, 'relay');
  const peerAt = peer ? peer.start : inner.start + 100;
  const relayAt = relay ? relay.start : peerAt + 40;
  const loop = (start: number, period: number) => (frame < start ? 0 : ((frame - start) % period) / period);
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <Icon kind="phone" x={20} y={420} size={200} opacity={progress(frame, inner.start, 10)} />
      <Icon kind="phone" x={716} y={420} size={200} opacity={progress(frame, inner.start, 10)} />
      <Icon kind="server" x={403} y={60} size={130} color={COLORS.orange} opacity={progress(frame, relayAt - 6, 10)} />
      <Svg>
        <Arrow from={{x: 200, y: 520}} to={{x: 736, y: 520}} progress={progress(frame, peerAt, 16)} color={COLORS.green} />
        {frame >= peerAt + 16 && <Packet from={{x: 210, y: 520}} to={{x: 726, y: 520}} progress={loop(peerAt + 16, 30)} color={COLORS.green} />}
        <Arrow from={{x: 190, y: 440}} to={{x: 420, y: 200}} progress={progress(frame, relayAt, 12)} color={COLORS.orange} dashed />
        <Arrow from={{x: 516, y: 200}} to={{x: 746, y: 440}} progress={progress(frame, relayAt + 8, 12)} color={COLORS.orange} dashed />
      </Svg>
      <Label x={268} y={560} width={400} align="center" color={COLORS.green} opacity={progress(frame, peerAt, 10)}>Peer to peer</Label>
      <Label x={568} y={110} width={300} color={COLORS.orange} opacity={progress(frame, relayAt, 10)}>Relay</Label>
      <Label x={0} y={0} width={936} align="center" color={COLORS.secondary} size={38} opacity={progress(frame, inner.start, 10)}>Where does the voice travel?</Label>
    </div>
  );
}
