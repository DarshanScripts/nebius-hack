# Scene authoring guide (shared context for every scene agent)

You write ONE Remotion scene: a single TypeScript/React module `Scene.tsx` that draws the
animated workboard content for one of six scenes in a 60-second educational reel. Six agents
work independently with the same guide; you never see or change another scene.

## What you own and what you do not

- You own ONLY the scene content area: **936 × 816 px**. Your coordinates are relative to its
  top-left corner (it sits at video `x=72, y=288` on a 1080×1920 canvas).
- The global shell already draws, and you must NOT draw: the white dot-grid background, the
  topic title, captions, the two character images (Sundar left, Jensen right), and all audio.
- Scene start and end state is a **clear content area**. The worker fades your content in over
  the first 12 frames and out over the last 12. Keep your own animation in the interior interval
  `[12, durationInFrames - 12)` (use `interior(props)`); do not add your own fade-out at the end.
- Scene length, dialogue, audio and word timings are fixed. You cannot change them.

## Module contract

```tsx
import React from 'react';
import {interpolate} from 'remotion';
import {Box, COLORS, findWord, interior, progress} from './scene-kit';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  // props.frame is SCENE-LOCAL (0 = this scene's first frame).
  return <div style={{position: 'absolute', inset: 0}}>...</div>;
}
```

`SceneProps = {frame, durationInFrames, slot, context, cues}`. `context` holds the research
(`context.research.claims`), the whole script (`context.script.turns`), image selections,
audio with measured words, and the timeline. `cues` are the cues you submit with the draft.

## Hard rules (the validator rejects violations)

- Imports ONLY from `react`, `remotion`, and `./scene-kit`. No other packages or files.
- From `remotion` only: `interpolate, interpolateColors, spring, Easing, AbsoluteFill, Sequence,
  Series, useCurrentFrame, useVideoConfig, random, Freeze, Loop, measureSpring`.
- Pure function of the frame: no `useState/useEffect/useRef/useReducer`, no `setTimeout`,
  `setInterval`, `requestAnimationFrame`, `Date`, `performance`, `Math.random` (use
  `random('seed')` if you need noise), no `fetch`, `window`, `document`, `process`.
- No `<img>`, `<video>`, `<audio>`, `<iframe>`, `<image>`, `<use>`, `<style>`; no URL strings
  (`http:`, `//`, `file:`), no CSS `url(...)`. Use `SceneImage` for the scene's research image.
- `export default` a function component. TypeScript strict mode must pass.
- Text size at least **36 px**: the kit's `Label` and `Box` enforce it, and the validator rejects any literal `fontSize` below 36. Font: DejaVu Sans
  (`FONT`). Keep every element inside 0 ≤ x < 936, 0 ≤ y < 816.

## Theme

| Token | Value | Meaning |
| --- | --- | --- |
| `COLORS.ink` | `#111827` | main ink |
| `COLORS.secondary` | `#64748B` | secondary text |
| `COLORS.blue` | `#2563EB` | signalling / control / questions |
| `COLORS.green` | `#16A34A` | data, media, success |
| `COLORS.orange` | `#EA580C` | attention, obstacles, caveats |
| `COLORS.panel`, `COLORS.line` | `#F8FAFC`, `#CBD5E1` | card fill, neutral lines |

Use the accent meanings consistently. White background is already drawn — do not paint a
full-area background.

## Timing: animate on the measured words

Word times come from forced alignment of the real audio. Drive motion from them:

- `sceneTurns(props)` → this scene's two turns, each `{turn, start, end, words}` with
  scene-local frames; each word is `{word_id, text, start, end}` (half-open frames).
- `findWord(props, 'relay')` → first matching word in this scene (case/punctuation-insensitive)
  or `null`. ALWAYS handle `null` with a fallback frame.
- `wordWindow(props, 'd004_w007')` → `{start, end}` for a word id, or `null`.
- `cueWindow(props, 'cue_id')` → frames of one of your submitted cues.
- `interior(props)` → `{start: 12, end: durationInFrames - 12}`.
- `progress(frame, start, length=12)` → eased 0..1; `pop(frame, start)` → spring 0..~1;
  `isActive(frame, window)`.

Clamp every start to `interior(props).start` or later so content appears after the fade-in.

## Kit components (content coordinates)

- `<Label x y width? size? color? weight? align? opacity?>text</Label>`
- `<Box x y width height label? sublabel? color? fill? highlight?(0..1) opacity? scale?>`
- `<Svg>…</Svg>` full-area SVG layer; inside it: `<Arrow from={{x,y}} to={{x,y}} progress color
  dashed? width?/>` and `<Packet from to progress(0..1) color? size? label?/>` (hidden at 0 and 1).
- `<Icon kind="phone|server|cloud|lock|user|chip" x y size? color? opacity?/>`
- `<ClaimTag context={props.context} ids={['c003']} x y opacity?/>` — citation chip; only
  existing claim ids render.
- `<SceneImage scene={props} x y width height opacity?/>` — the image selected for this scene,
  renders nothing if unavailable (then draw a vector diagram instead). `sceneImage(props)`
  tells you whether one exists.
- Helpers: `shorten(text, max)`, `claimById(context, id)`, constants `W=936`, `H=816`, `FONT`,
  `COLORS`.

## Content rules

- Prefer a clear diagram (e.g. phone → signalling server → phone, packets moving along a path)
  with motion and highlights at meaningful words. 2–5 visual elements, readable at phone size.
- Topic-specific facts must come from `context.research.claims`; reference them by claim id in
  your cues (`claim_ids`) and optionally with `ClaimTag`. Never invent numbers (latency, users,
  traffic) for visual interest. Preserve stated uncertainty.
- Do not repeat the spoken sentence as a paragraph — captions already show it. Short labels.
- Never overlap text: each text element gets its own region, at most one label + one sublabel per
  `Box` (use its `label`/`sublabel` props, not extra `Label`s on top), and leave ≥ 24 px between
  text blocks. Two texts that occupy the same area at the same frame are a defect.

## Output (SceneDraft)

Return `source_code` (the complete module), a one-sentence `summary`, and `cues`:
`{cue_id, word_ids, start_frame, end_frame, description, claim_ids}` with SCENE-LOCAL frames.
If `word_ids` are given, frames are recomputed from the measured words (yours are ignored);
untimed cues must satisfy `0 <= start_frame < end_frame <= durationInFrames`. Word ids must
belong to this scene's two turns.

## Working example

```tsx
import React from 'react';
import {Arrow, COLORS, Icon, Label, Packet, Svg, findWord, interior, progress} from './scene-kit';
import type {SceneProps} from './scene-kit';

export default function Scene(props: SceneProps) {
  const {frame} = props;
  const inner = interior(props);
  const peer = findWord(props, 'peer');
  const relay = findWord(props, 'relay');
  const peerAt = Math.max(inner.start, peer ? peer.start : inner.start + 100);
  const relayAt = Math.max(inner.start, relay ? relay.start : peerAt + 40);
  const loop = (start: number, period: number) => (frame < start ? 0 : ((frame - start) % period) / period);
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <Icon kind="phone" x={20} y={420} size={200} opacity={progress(frame, inner.start, 10)} />
      <Icon kind="phone" x={716} y={420} size={200} opacity={progress(frame, inner.start, 10)} />
      <Icon kind="server" x={403} y={60} size={130} color={COLORS.orange} opacity={progress(frame, relayAt - 6, 10)} />
      <Svg>
        <Arrow from={{x: 200, y: 520}} to={{x: 736, y: 520}} progress={progress(frame, peerAt, 16)} color={COLORS.green} />
        {frame >= peerAt + 16 && <Packet from={{x: 210, y: 520}} to={{x: 726, y: 520}} progress={loop(peerAt + 16, 30)} />}
        <Arrow from={{x: 190, y: 440}} to={{x: 420, y: 200}} progress={progress(frame, relayAt, 12)} color={COLORS.orange} dashed />
        <Arrow from={{x: 516, y: 200}} to={{x: 746, y: 440}} progress={progress(frame, relayAt + 8, 12)} color={COLORS.orange} dashed />
      </Svg>
      <Label x={268} y={560} width={400} align="center" color={COLORS.green} opacity={progress(frame, peerAt, 10)}>Peer to peer</Label>
      <Label x={568} y={110} width={300} color={COLORS.orange} opacity={progress(frame, relayAt, 10)}>Relay</Label>
    </div>
  );
}
```
