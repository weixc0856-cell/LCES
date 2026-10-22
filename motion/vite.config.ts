import {defineConfig} from 'vite';
import motionCanvas from '@motion-canvas/vite-plugin';

// A build project is a copy of this project with node_modules symlinked back
// here. Vite's default file allow-list stops at the copy's own root, so the
// real node_modules path must be admitted explicitly.
const allow = [process.cwd(), process.env.MC_NODE_MODULES].filter(
  (entry): entry is string => Boolean(entry),
);

export default defineConfig({
  plugins: [motionCanvas({output: process.env.MC_OUTPUT_DIR || 'output'})],
  server: {
    fs: {allow},
  },
});
