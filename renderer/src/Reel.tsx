import React from 'react';
import {Sequence} from 'remotion';
import {scenes} from './generated-scenes';
import {SceneFrame, Shell} from './shell';
import {VIDEO} from './scene-kit';
import type {RenderInputProps} from './types/contracts';

/** Final master composition: six scenes at their fixed frame ranges, one audio pass. */
export const Reel: React.FC<RenderInputProps> = (props) => {
  const slots = props.context.timeline.scenes.slice().sort((a, b) => a.index - b.index);
  return (
    <Shell props={props} offset={0} duration={VIDEO.durationInFrames}>
      {slots.map((slot) => {
        const build = props.builds.find((b) => b.scene_id === slot.scene_id);
        const Scene = scenes[slot.scene_id];
        if (!build || !Scene) throw new Error(`Missing scene build/module for ${slot.scene_id}`);
        return (
          <Sequence key={slot.scene_id} from={slot.start_frame} durationInFrames={slot.end_frame - slot.start_frame} layout="none">
            <SceneFrame Scene={Scene} slot={slot} build={build} props={props} />
          </Sequence>
        );
      })}
    </Shell>
  );
};
