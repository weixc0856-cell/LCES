import {Circle, makeScene2D} from '@motion-canvas/2d';
import {createRef} from '@motion-canvas/core';

// LCES P0 spike: fixed 10-second animation for resource and frame-count checks.
export default makeScene2D(function* (view) {
  const circle = createRef<Circle>();

  view.add(<Circle ref={circle} size={320} fill={'lightseagreen'} />);

  yield* circle().scale(2, 5).to(1, 5);
});
