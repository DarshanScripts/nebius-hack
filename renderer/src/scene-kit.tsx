// Shared scene kit: the ONLY local module generated scenes may import.
// Everything here is frame-driven and deterministic (no timers, wall clock,
// randomness, or network). Coordinates are unscaled video pixels; scene
// geometry is relative to the 936x816 scene content area.
import React, {createContext, useContext} from 'react';
import {Easing, Img, interpolate, spring, staticFile} from 'remotion';
import type {
  AnimationCue,
  Claim,
  DialogueTurn,
  ImageSelection,
  SceneContext,
  SceneSlot,
  SpeakerId,
  UtteranceAudio,
} from './types/contracts';

export type {AnimationCue, SceneContext, SceneSlot, DialogueTurn, Claim} from './types/contracts';

export interface SceneProps {
  /** SCENE-LOCAL frame: global_frame - slot.start_frame. */
  frame: number;
  durationInFrames: number;
  slot: SceneSlot;
  context: SceneContext;
  cues: AnimationCue[];
}

// ---------------------------------------------------------------- theme
export const FPS = 30;
export const VIDEO = {width: 1080, height: 1920, fps: FPS, durationInFrames: 1800} as const;
export const WORKBOARD = {x: 0, y: 0, width: 1080, height: 1344} as const;
export const TITLE_BOX = {x: 72, y: 120, width: 936, height: 120} as const;
export const CONTENT_BOX = {x: 72, y: 288, width: 936, height: 816} as const;
export const CAPTION_BOX = {x: 72, y: 1152, width: 936, height: 144} as const;
export const CHARACTER_REGION = {x: 0, y: 1344, width: 1080, height: 576} as const;
export const CHARACTER_BOXES: Record<SpeakerId, {x: number; y: number; width: number; height: number}> = {
  sundar: {x: 48, y: 1344, width: 420, height: 576},
  jensen: {x: 612, y: 1344, width: 420, height: 576},
};
/** Scene content size; generated geometry lives in [0,W) x [0,H). */
export const W = 936;
export const H = 816;
export const BOUNDARY_FRAMES = 12;
export const MIN_LABEL_SIZE = 36;
export const FONT = "'DejaVu Sans', 'DejaVu Sans Fallback', sans-serif";
export const COLORS = {
  background: '#FFFFFF',
  dot: '#D8DEE8',
  ink: '#111827',
  secondary: '#64748B',
  /** blue = signalling/control, green = media/success, orange = attention/caveat */
  blue: '#2563EB',
  green: '#16A34A',
  orange: '#EA580C',
  panel: '#F8FAFC',
  line: '#CBD5E1',
} as const;
export type Accent = 'blue' | 'green' | 'orange' | 'ink' | 'secondary';
export const accent = (a: Accent): string => COLORS[a];

// ---------------------------------------------------------------- assets
/** Provided by the worker wrapper: artifact key -> job-local static path. */
export const AssetContext = createContext<Record<string, string>>({});

export const resolveAsset = (assets: Record<string, string>, key: string | null | undefined): string | null => {
  if (!key) return null;
  const rel = assets[key];
  return rel ? staticFile(rel) : null;
};

export const useAssetUrl = (key: string | null | undefined): string | null =>
  resolveAsset(useContext(AssetContext), key);

// ---------------------------------------------------------------- timing
export interface TimedWord {
  word_id: string;
  text: string;
  /** Global frames, half-open [start, end). */
  start: number;
  end: number;
}

export interface TimedTurn {
  turn: DialogueTurn;
  audio: UtteranceAudio | undefined;
  /** Global frames, half-open. */
  start: number;
  end: number;
  words: TimedWord[];
}

/** plan.md section 7: floor(start_ms*30/1000) / ceil(end_ms*30/1000), clamped to the utterance. */
export const msToFrameFloor = (ms: number): number => Math.floor((ms * FPS) / 1000);
export const msToFrameCeil = (ms: number): number => Math.ceil((ms * FPS) / 1000);

export const timedTurns = (context: SceneContext): TimedTurn[] => {
  const audioById = new Map(context.audio.utterances.map((u) => [u.dialogue_id, u]));
  const timingById = new Map(context.timeline.utterances.map((u) => [u.dialogue_id, u]));
  return context.script.turns
    .slice()
    .sort((a, b) => a.order - b.order)
    .flatMap((turn) => {
      const timing = timingById.get(turn.dialogue_id);
      if (!timing) return [];
      const audio = audioById.get(turn.dialogue_id);
      const words = (audio?.words ?? []).map((w) => {
        const start = Math.min(timing.end_frame - 1, timing.start_frame + msToFrameFloor(w.start_ms));
        const end = Math.max(start + 1, Math.min(timing.end_frame, timing.start_frame + msToFrameCeil(w.end_ms)));
        return {word_id: w.word_id, text: w.text, start, end};
      });
      return [{turn, audio, start: timing.start_frame, end: timing.end_frame, words}];
    });
};

/** This scene's two turns with SCENE-LOCAL frames. */
export const sceneTurns = (props: Pick<SceneProps, 'context' | 'slot'>): TimedTurn[] =>
  timedTurns(props.context)
    .filter((t) => props.slot.dialogue_ids.includes(t.turn.dialogue_id))
    .map((t) => ({
      ...t,
      start: t.start - props.slot.start_frame,
      end: t.end - props.slot.start_frame,
      words: t.words.map((w) => ({...w, start: w.start - props.slot.start_frame, end: w.end - props.slot.start_frame})),
    }));

/** Scene-local [start,end) of a word id such as "d011_w003", or null if unknown. */
export const wordWindow = (props: Pick<SceneProps, 'context' | 'slot'>, wordId: string): {start: number; end: number} | null => {
  for (const t of sceneTurns(props)) {
    const w = t.words.find((x) => x.word_id === wordId);
    if (w) return {start: w.start, end: w.end};
  }
  return null;
};

/** First word in this scene whose text matches (case/punctuation-insensitive). */
export const findWord = (props: Pick<SceneProps, 'context' | 'slot'>, text: string): TimedWord | null => {
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
  const target = norm(text);
  for (const t of sceneTurns(props)) {
    const w = t.words.find((x) => norm(x.text) === target);
    if (w) return w;
  }
  return null;
};

export const cueWindow = (props: Pick<SceneProps, 'cues'>, cueId: string): {start: number; end: number} | null => {
  const c = props.cues.find((x) => x.cue_id === cueId);
  return c ? {start: c.start_frame, end: c.end_frame} : null;
};

/** Interior animation interval; the worker owns the outer 12-frame fades. */
export const interior = (props: Pick<SceneProps, 'durationInFrames'>): {start: number; end: number} => ({
  start: BOUNDARY_FRAMES,
  end: Math.max(BOUNDARY_FRAMES + 1, props.durationInFrames - BOUNDARY_FRAMES),
});

/** 0..1 eased progress from `start` over `length` frames. */
export const progress = (frame: number, start: number, length = 12): number =>
  interpolate(frame, [start, start + Math.max(1, length)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.cubic),
  });

/** Deterministic spring pop-in starting at `start` (0..~1). */
export const pop = (frame: number, start: number): number =>
  spring({frame: frame - start, fps: FPS, config: {damping: 14, stiffness: 120, mass: 0.6}});

/** True while frame is within the half-open window. */
export const isActive = (frame: number, win: {start: number; end: number} | null): boolean =>
  !!win && frame >= win.start && frame < win.end;

export const claimById = (context: SceneContext, claimId: string): Claim | undefined =>
  context.research.claims.find((c) => c.claim_id === claimId);

export const sceneImage = (props: Pick<SceneProps, 'context' | 'slot'>): ImageSelection | null => {
  const sel = props.context.images.selections.find((s) => s.query.scene_index === props.slot.index);
  return sel && sel.status === 'selected' && sel.asset ? sel : null;
};

// ---------------------------------------------------------------- components
type XY = {x: number; y: number};

export const Label: React.FC<{
  x: number;
  y: number;
  width?: number;
  size?: number;
  color?: string;
  weight?: number;
  align?: 'left' | 'center' | 'right';
  opacity?: number;
  children: React.ReactNode;
}> = ({x, y, width = 400, size = 40, color = COLORS.ink, weight = 600, align = 'left', opacity = 1, children}) => (
  <div
    style={{
      position: 'absolute',
      left: x,
      top: y,
      width,
      fontFamily: FONT,
      fontSize: Math.max(MIN_LABEL_SIZE, size),
      fontWeight: weight,
      lineHeight: 1.2,
      color,
      textAlign: align,
      opacity,
    }}
  >
    {children}
  </div>
);

export const Box: React.FC<{
  x: number;
  y: number;
  width: number;
  height: number;
  label?: React.ReactNode;
  sublabel?: React.ReactNode;
  color?: string;
  fill?: string;
  highlight?: number;
  opacity?: number;
  scale?: number;
  children?: React.ReactNode;
}> = ({x, y, width, height, label, sublabel, color = COLORS.ink, fill = COLORS.panel, highlight = 0, opacity = 1, scale = 1, children}) => (
  <div
    style={{
      position: 'absolute',
      left: x,
      top: y,
      width,
      height,
      boxSizing: 'border-box',
      border: `${4 + 4 * highlight}px solid ${color}`,
      borderRadius: 28,
      background: fill,
      boxShadow: highlight > 0 ? `0 0 0 ${12 * highlight}px ${color}22` : 'none',
      opacity,
      transform: `scale(${scale})`,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: FONT,
      color: COLORS.ink,
      textAlign: 'center',
      padding: 12,
      overflow: 'hidden',
    }}
  >
    {label !== undefined && <div style={{fontSize: 40, fontWeight: 700, lineHeight: 1.15}}>{label}</div>}
    {sublabel !== undefined && <div style={{fontSize: 36, color: COLORS.secondary, marginTop: 6, lineHeight: 1.15}}>{sublabel}</div>}
    {children}
  </div>
);

/** Full-content SVG layer; children use content coordinates. */
export const Svg: React.FC<{children: React.ReactNode; opacity?: number}> = ({children, opacity = 1}) => (
  <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{position: 'absolute', left: 0, top: 0, opacity, overflow: 'visible'}}>
    {children}
  </svg>
);

/** Arrow drawn progressively (progress 0..1). Use inside <Svg>. */
export const Arrow: React.FC<{from: XY; to: XY; progress?: number; color?: string; width?: number; dashed?: boolean}> = ({
  from,
  to,
  progress: p = 1,
  color = COLORS.ink,
  width = 6,
  dashed = false,
}) => {
  const ex = from.x + (to.x - from.x) * p;
  const ey = from.y + (to.y - from.y) * p;
  const ang = Math.atan2(to.y - from.y, to.x - from.x);
  const head = 22;
  return (
    <g opacity={p > 0 ? 1 : 0}>
      <line x1={from.x} y1={from.y} x2={ex} y2={ey} stroke={color} strokeWidth={width} strokeLinecap="round" strokeDasharray={dashed ? '18 14' : undefined} />
      {p > 0.98 && (
        <polygon
          points={`${to.x},${to.y} ${to.x - head * Math.cos(ang - 0.45)},${to.y - head * Math.sin(ang - 0.45)} ${to.x - head * Math.cos(ang + 0.45)},${to.y - head * Math.sin(ang + 0.45)}`}
          fill={color}
        />
      )}
    </g>
  );
};

/** A packet dot travelling from -> to (progress 0..1). Use inside <Svg>. */
export const Packet: React.FC<{from: XY; to: XY; progress: number; color?: string; size?: number; label?: string}> = ({
  from,
  to,
  progress: p,
  color = COLORS.green,
  size = 18,
  label,
}) => {
  if (p <= 0 || p >= 1) return null;
  const x = from.x + (to.x - from.x) * p;
  const y = from.y + (to.y - from.y) * p;
  return (
    <g>
      <rect x={x - size} y={y - size * 0.7} width={size * 2} height={size * 1.4} rx={6} fill={color} />
      {label && (
        <text x={x} y={y - size - 8} fontFamily={FONT} fontSize={36} fill={color} textAnchor="middle" fontWeight={700}>
          {label}
        </text>
      )}
    </g>
  );
};

/** Simple line icons drawn in a size x size box. */
export const Icon: React.FC<{kind: 'phone' | 'server' | 'cloud' | 'lock' | 'user' | 'chip'; x: number; y: number; size?: number; color?: string; opacity?: number}> = ({
  kind,
  x,
  y,
  size = 140,
  color = COLORS.ink,
  opacity = 1,
}) => {
  const s = size;
  const sw = Math.max(4, s / 22);
  const common = {fill: 'none', stroke: color, strokeWidth: sw, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const};
  let body: React.ReactNode;
  switch (kind) {
    case 'phone':
      body = (
        <>
          <rect x={s * 0.28} y={s * 0.06} width={s * 0.44} height={s * 0.88} rx={s * 0.08} {...common} />
          <line x1={s * 0.44} y1={s * 0.16} x2={s * 0.56} y2={s * 0.16} {...common} />
          <circle cx={s * 0.5} cy={s * 0.82} r={s * 0.03} fill={color} />
        </>
      );
      break;
    case 'server':
      body = (
        <>
          {[0.1, 0.4, 0.7].map((t) => (
            <g key={t}>
              <rect x={s * 0.14} y={s * t} width={s * 0.72} height={s * 0.22} rx={s * 0.04} {...common} />
              <circle cx={s * 0.28} cy={s * (t + 0.11)} r={s * 0.03} fill={color} />
            </g>
          ))}
        </>
      );
      break;
    case 'cloud':
      body = <path d={`M${s * 0.25},${s * 0.72} a${s * 0.16},${s * 0.16} 0 0 1 0,-${s * 0.32} a${s * 0.22},${s * 0.22} 0 0 1 ${s * 0.42},-${s * 0.06} a${s * 0.16},${s * 0.16} 0 0 1 ${s * 0.1},${s * 0.38} z`} {...common} />;
      break;
    case 'lock':
      body = (
        <>
          <rect x={s * 0.2} y={s * 0.45} width={s * 0.6} height={s * 0.45} rx={s * 0.06} {...common} />
          <path d={`M${s * 0.32},${s * 0.45} v-${s * 0.12} a${s * 0.18},${s * 0.18} 0 0 1 ${s * 0.36},0 v${s * 0.12}`} {...common} />
        </>
      );
      break;
    case 'user':
      body = (
        <>
          <circle cx={s * 0.5} cy={s * 0.32} r={s * 0.17} {...common} />
          <path d={`M${s * 0.16},${s * 0.9} a${s * 0.34},${s * 0.34} 0 0 1 ${s * 0.68},0`} {...common} />
        </>
      );
      break;
    case 'chip':
      body = (
        <>
          <rect x={s * 0.22} y={s * 0.22} width={s * 0.56} height={s * 0.56} rx={s * 0.06} {...common} />
          {[0.32, 0.5, 0.68].map((t) => (
            <g key={t}>
              <line x1={s * t} y1={s * 0.08} x2={s * t} y2={s * 0.22} {...common} />
              <line x1={s * t} y1={s * 0.78} x2={s * t} y2={s * 0.92} {...common} />
            </g>
          ))}
        </>
      );
      break;
  }
  return (
    <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} style={{position: 'absolute', left: x, top: y, opacity, overflow: 'visible'}}>
      {body}
    </svg>
  );
};

/** Small citation chip, e.g. <ClaimTag ids={['c003']} />. Only show claim ids that exist. */
export const ClaimTag: React.FC<{context: SceneContext; ids: string[]; x: number; y: number; opacity?: number}> = ({context, ids, x, y, opacity = 1}) => {
  const valid = ids.filter((id) => claimById(context, id));
  if (valid.length === 0) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        fontFamily: FONT,
        fontSize: 36,
        color: COLORS.secondary,
        border: `3px solid ${COLORS.line}`,
        borderRadius: 999,
        padding: '4px 18px',
        background: COLORS.background,
        opacity,
      }}
    >
      {valid.join(' · ')}
    </div>
  );
};

/** The research image selected for this scene, if any (otherwise renders nothing). */
export const SceneImage: React.FC<{scene: Pick<SceneProps, 'context' | 'slot'>; x: number; y: number; width: number; height: number; opacity?: number}> = ({
  scene,
  x,
  y,
  width,
  height,
  opacity = 1,
}) => {
  const sel = sceneImage(scene);
  const src = useAssetUrl(sel?.asset?.key);
  if (!sel || !src) return null;
  return (
    <div style={{position: 'absolute', left: x, top: y, width, height, borderRadius: 24, overflow: 'hidden', border: `4px solid ${COLORS.line}`, background: COLORS.background, opacity}}>
      <Img src={src} style={{width: '100%', height: '100%', objectFit: 'contain'}} />
    </div>
  );
};

/** Clip text deterministically to at most `max` characters on a word boundary. */
export const shorten = (text: string, max: number): string => {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const sp = cut.lastIndexOf(' ');
  return `${(sp > max * 0.5 ? cut.slice(0, sp) : cut).replace(/[\s,.;:]+$/, '')}…`;
};
