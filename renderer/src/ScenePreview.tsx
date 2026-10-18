import React from 'react';
import {scenes} from './generated-scenes';
import {SceneFrame, Shell} from './shell';
import type {RenderInputProps} from './types/contracts';

/** One scene with the same shell/captions/characters/audio as the reel; frame 0 = slot.start_frame. */
export const ScenePreview: React.FC<RenderInputProps> = (props) => {
  const slot = props.context.timeline.scenes.find((s) => s.scene_id === props.preview_scene_id);
  const build = props.builds.find((b) => b.scene_id === props.preview_scene_id);
  const Scene = props.preview_scene_id ? scenes[props.preview_scene_id] : undefined;
  if (!slot || !build || !Scene) throw new Error(`Missing preview slot/build/module for ${props.preview_scene_id}`);
  const duration = slot.end_frame - slot.start_frame;
  return (
    <Shell props={props} offset={slot.start_frame} duration={duration}>
      <SceneFrame Scene={Scene} slot={slot} build={build} props={props} />
    </Shell>
  );
};
