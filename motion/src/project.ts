import {makeProject} from '@motion-canvas/core';

import generated from './scenes/generated?scene';

// The scene module is regenerated per build by
// content_studio.motion_canvas._scene_source(); it is not model-authored.
export default makeProject({
  scenes: [generated],
});
