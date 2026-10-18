import React from 'react';
import {Composition} from 'remotion';
import {Reel} from './Reel';
import {ScenePreview} from './ScenePreview';
import {VIDEO} from './scene-kit';
import type {RenderInputProps} from './types/contracts';

const empty = {} as RenderInputProps;

export const Root: React.FC = () => (
  <>
    <Composition id="Reel" component={Reel} durationInFrames={VIDEO.durationInFrames} fps={VIDEO.fps} width={VIDEO.width} height={VIDEO.height} defaultProps={empty} />
    <Composition
      id="ScenePreview"
      component={ScenePreview}
      durationInFrames={1}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
      defaultProps={empty}
      calculateMetadata={({props}) => {
        const slot = props.context?.timeline.scenes.find((s) => s.scene_id === props.preview_scene_id);
        return {durationInFrames: slot ? slot.end_frame - slot.start_frame : 1};
      }}
    />
  </>
);
