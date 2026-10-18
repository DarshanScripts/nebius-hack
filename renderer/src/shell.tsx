// Global shell shared by previews and the final reel: dot background, title,
// captions, persistent characters, audio, and the centrally applied scene
// boundary envelope. Generated scenes never render these layers.
import React from 'react';
import {AbsoluteFill, Audio, Img, interpolate, Sequence, useCurrentFrame} from 'remotion';
import {
  AssetContext,
  BOUNDARY_FRAMES,
  CAPTION_BOX,
  CHARACTER_BOXES,
  CHARACTER_REGION,
  COLORS,
  CONTENT_BOX,
  FONT,
  TITLE_BOX,
  VIDEO,
  resolveAsset,
  shorten,
  timedTurns,
  type SceneProps,
  type TimedTurn,
  type TimedWord,
} from './scene-kit';
import type {RenderInputProps, SceneBuild, SceneSlot, SpeakerId} from './types/contracts';

export const CHARACTER_SLIDE_FRAMES = 8;

const DotBackground: React.FC = () => (
  <svg width={VIDEO.width} height={VIDEO.height} style={{position: 'absolute', left: 0, top: 0}}>
    <defs>
      <pattern id="dots" x={0} y={0} width={24} height={24} patternUnits="userSpaceOnUse">
        <circle cx={12} cy={12} r={1} fill={COLORS.dot} />
      </pattern>
    </defs>
    <rect width={VIDEO.width} height={VIDEO.height} fill={COLORS.background} />
    <rect width={VIDEO.width} height={VIDEO.height} fill="url(#dots)" />
  </svg>
);

const Title: React.FC<{title: string}> = ({title}) => (
  <div
    style={{
      position: 'absolute',
      left: TITLE_BOX.x,
      top: TITLE_BOX.y,
      width: TITLE_BOX.width,
      height: TITLE_BOX.height,
      display: 'flex',
      alignItems: 'center',
      fontFamily: FONT,
      fontSize: 52,
      fontWeight: 700,
      lineHeight: 1.1,
      color: COLORS.ink,
      overflow: 'hidden',
    }}
  >
    {shorten(title, 60)}
  </div>
);

// ---------------------------------------------------------------- captions
interface Chunk {
  words: TimedWord[];
  start: number;
  end: number;
}

const MAX_CHUNK_WORDS = 6;
const MAX_CHUNK_CHARS = 34;

export const captionChunks = (turn: TimedTurn): Chunk[] => {
  const groups: TimedWord[][] = [];
  let cur: TimedWord[] = [];
  let chars = 0;
  for (const w of turn.words) {
    if (cur.length > 0 && (cur.length >= MAX_CHUNK_WORDS || chars + 1 + w.text.length > MAX_CHUNK_CHARS)) {
      groups.push(cur);
      cur = [];
      chars = 0;
    }
    cur.push(w);
    chars += (chars ? 1 : 0) + w.text.length;
    if (/[.?!;:]$/.test(w.text) && cur.length >= 2) {
      groups.push(cur);
      cur = [];
      chars = 0;
    }
  }
  if (cur.length) groups.push(cur);
  return groups.map((words, i) => ({
    words,
    start: i === 0 ? turn.start : words[0].start,
    end: i + 1 < groups.length ? groups[i + 1][0].start : turn.end,
  }));
};

const Captions: React.FC<{turns: TimedTurn[]; frame: number}> = ({turns, frame}) => {
  const turn = turns.find((t) => frame >= t.start && frame < t.end);
  const chunk = turn ? captionChunks(turn).find((c) => frame >= c.start && frame < c.end) : undefined;
  return (
    <div
      style={{
        position: 'absolute',
        left: CAPTION_BOX.x,
        top: CAPTION_BOX.y,
        width: CAPTION_BOX.width,
        height: CAPTION_BOX.height,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        fontFamily: FONT,
        fontSize: 48,
        fontWeight: 700,
        lineHeight: '64px',
        maxHeight: 128,
        overflow: 'hidden',
      }}
    >
      {chunk && (
        <div>
          {chunk.words.map((w, i) => {
            const next = chunk.words[i + 1];
            const active = frame >= w.start && (next ? frame < next.start : frame < chunk.end);
            return (
              <span key={w.word_id} style={{color: active ? COLORS.blue : COLORS.ink}}>
                {i > 0 ? ' ' : ''}
                {w.text}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------- characters
const Silhouette: React.FC<{name: string; color: string}> = ({name, color}) => (
  <svg width={420} height={576} viewBox="0 0 420 576">
    <circle cx={210} cy={170} r={90} fill={color} opacity={0.85} />
    <path d="M20,576 Q20,290 210,290 Q400,290 400,576 Z" fill={color} opacity={0.85} />
    <text x={210} y={450} fontFamily={FONT} fontSize={36} fontWeight={700} fill="#FFFFFF" textAnchor="middle" textLength={name.length > 12 ? 340 : undefined} lengthAdjust="spacingAndGlyphs">
      {name}
    </text>
  </svg>
);

/** Horizontal offset in px for a speaker at a global frame; null if hidden. */
export const characterOffset = (turns: TimedTurn[], speaker: SpeakerId, frame: number): number | null => {
  const box = CHARACTER_BOXES[speaker];
  const off = speaker === 'sundar' ? -(box.x + box.width) : VIDEO.width - box.x;
  let best: number | null = null;
  for (const t of turns) {
    if (t.turn.speaker_id !== speaker) continue;
    if (frame < t.start - CHARACTER_SLIDE_FRAMES || frame >= t.end + CHARACTER_SLIDE_FRAMES) continue;
    const enter = interpolate(frame, [t.start - CHARACTER_SLIDE_FRAMES, t.start], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
    const exit = interpolate(frame, [t.end, t.end + CHARACTER_SLIDE_FRAMES], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
    const x = off * Math.max(enter, exit) || 0;
    best = best === null ? x : Math.abs(x) < Math.abs(best) ? x : best;
  }
  return best;
};

const Characters: React.FC<{props: RenderInputProps; turns: TimedTurn[]; frame: number}> = ({props, turns, frame}) => {
  const assets = props.assets;
  return (
    <div
      style={{
        position: 'absolute',
        left: CHARACTER_REGION.x,
        top: CHARACTER_REGION.y,
        width: CHARACTER_REGION.width,
        height: CHARACTER_REGION.height,
        overflow: 'hidden',
      }}
    >
      {(['sundar', 'jensen'] as const).map((id) => {
        const dx = characterOffset(turns, id, frame);
        if (dx === null) return null;
        const box = CHARACTER_BOXES[id];
        const spec = props.context.characters.find((c) => c.character_id === id);
        const src = resolveAsset(assets, spec?.image?.key);
        return (
          <div
            key={id}
            style={{
              position: 'absolute',
              left: box.x,
              top: 0,
              width: box.width,
              height: box.height,
              transform: `translateX(${dx}px)`,
              display: 'flex',
              alignItems: 'flex-end',
              justifyContent: 'center',
            }}
          >
            {src ? (
              <Img src={src} style={{width: '100%', height: '100%', objectFit: 'contain', objectPosition: 'center bottom'}} />
            ) : (
              <Silhouette name={spec?.display_name ?? id} color={id === 'sundar' ? COLORS.blue : COLORS.green} />
            )}
          </div>
        );
      })}
    </div>
  );
};

// ---------------------------------------------------------------- audio
const AudioTrack: React.FC<{props: RenderInputProps; turns: TimedTurn[]; offset: number; duration: number}> = ({props, turns, offset, duration}) => (
  <>
    {turns
      .filter((t) => t.end > offset && t.start < offset + duration)
      .map((t) => {
        const src = resolveAsset(props.assets, t.audio?.wav.key);
        if (!src) throw new Error(`Missing local audio asset for ${t.turn.dialogue_id}`);
        const from = t.start - offset;
        return (
          <Sequence key={t.turn.dialogue_id} from={Math.max(0, from)} durationInFrames={t.end - t.start - Math.max(0, -from)} layout="none">
            <Audio src={src} trimBefore={Math.max(0, -from)} />
          </Sequence>
        );
      })}
  </>
);

// ---------------------------------------------------------------- scene frame
export type SceneComponent = React.ComponentType<SceneProps>;

/** Content-area wrapper with the central 12-frame boundary fades. Frame is scene-local. */
export const SceneFrame: React.FC<{Scene: SceneComponent; slot: SceneSlot; build: SceneBuild; props: RenderInputProps}> = ({Scene, slot, build, props}) => {
  const frame = useCurrentFrame();
  const duration = slot.end_frame - slot.start_frame;
  const opacity = interpolate(frame, [0, BOUNDARY_FRAMES, duration - BOUNDARY_FRAMES, duration], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        left: CONTENT_BOX.x,
        top: CONTENT_BOX.y,
        width: CONTENT_BOX.width,
        height: CONTENT_BOX.height,
        overflow: 'hidden',
        opacity,
      }}
    >
      <Scene frame={frame} durationInFrames={duration} slot={slot} context={props.context} cues={build.cues} />
    </div>
  );
};

/**
 * Shell layers in global time. `offset` is the global frame shown at local
 * frame 0 (0 for the reel, slot.start_frame for a preview).
 */
export const Shell: React.FC<{props: RenderInputProps; offset: number; duration: number; children: React.ReactNode}> = ({props, offset, duration, children}) => {
  const frame = useCurrentFrame() + offset;
  const turns = timedTurns(props.context);
  return (
    <AssetContext.Provider value={props.assets}>
      <AbsoluteFill style={{backgroundColor: COLORS.background}}>
        <DotBackground />
        <Title title={props.context.script.title} />
        {children}
        <Captions turns={turns} frame={frame} />
        <Characters props={props} turns={turns} frame={frame} />
        <AudioTrack props={props} turns={turns} offset={offset} duration={duration} />
      </AbsoluteFill>
    </AssetContext.Provider>
  );
};
