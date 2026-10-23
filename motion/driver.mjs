import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from 'playwright';

import {
  CODES,
  ContractError,
  assertEditorVersion,
  assertSupportedPlatform,
  classifyState,
  countFrames,
  exitCodeFor,
  isRenderComplete,
  terminalFor,
  validateFrameCount,
} from './contract.mjs';
import {installLocalOnlyPolicy} from './network-policy.mjs';
import {prepareOutputDir} from './output-dir.mjs';

// LCES Motion Canvas driver (P1). Modes:
//   render  (default) - render the full range and require EXPECTED_FRAMES
//   cancel            - abort mid-render and require partial, unpublished output
//   timeout           - prove the driver can detect and stop a stuck render
const mode = process.env.MODE || 'render';
const expected = Number(process.env.EXPECTED_FRAMES || '300');
const expectedVersion = process.env.EXPECTED_EDITOR_VERSION || '3.17.2';
const buildId = process.env.BUILD_ID || '';
const cancelAfter = Number(process.env.CANCEL_AFTER_MS || '1200');
const timeoutAfter = Number(process.env.TIMEOUT_MS || '1000');
const maxRenderMs = Number(process.env.MAX_RENDER_MS || '120000');
const out = process.env.OUTPUT_DIR || path.resolve('output');
const reportPath = path.join(out, 'report.json');
// P2.3-D: scene text is pinned to locally available families. The adapter
// passes the same stack it writes into the generated scene.
const sceneFont = process.env.MC_SCENE_FONT || "'DejaVu Sans', 'Liberation Sans', Arial, sans-serif";

function sceneFontFamilies(css) {
  return css
    .split(',')
    .map(entry => entry.trim().replace(/^['"]|['"]$/g, ''))
    .filter(Boolean);
}

function uniqueBlocked(items) {
  const seen = new Map();
  for (const item of items) seen.set(`${item.origin}${item.path}|${item.type}`, item);
  return [...seen.values()];
}

// The platform gate runs before anything touches the filesystem, so an
// unsupported host cannot leave a half-created build behind.
try {
  assertSupportedPlatform(process.platform);
} catch (error) {
  if (error instanceof ContractError) {
    console.log('CONTRACT_ERROR', error.code, error.message);
    process.exit(exitCodeFor(error.code));
  }
  throw error;
}

let outputReady = false;
function resetOutput() {
  prepareOutputDir(out);
  outputReady = true;
}

const vite = path.join('node_modules', 'vite', 'bin', 'vite.js');
const server = spawn(process.execPath, [vite, '--port', '9000', '--host', '127.0.0.1'], {
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serverLog = '';
server.stdout.on('data', d => (serverLog += d));
server.stderr.on('data', d => (serverLog += d));

async function waitForServer() {
  for (let i = 0; i < 120; i++) {
    try {
      const response = await fetch('http://127.0.0.1:9000/');
      if (response.ok) return;
    } catch {}
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error('vite server did not start');
}

const external = [];
const consoleErrors = [];
let blocked = [];
let sceneFonts = {requested: sceneFontFamilies(sceneFont), available: []};
let requestFailures = 0;
let browser;
let finished = false;
let cancelled = false;
let timedOut = false;
let frames = 0;
let elapsed = 0;
let errorCode = '';

try {
  const manifest = JSON.parse(
    fs.readFileSync('node_modules/@motion-canvas/core/package.json', 'utf8'),
  );
  assertEditorVersion(manifest.version, expectedVersion);

  resetOutput();
  await waitForServer();
  browser = await chromium.launch({args: ['--no-sandbox', '--disable-dev-shm-usage']});
  const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
  // Blocked before the first navigation: the editor's Google Fonts, unpkg
  // stylesheet and npm update check never leave the machine.
  blocked = installLocalOnlyPolicy(page);
  page.on('request', r => {
    const u = r.url();
    if (!u.startsWith('http://127.0.0.1:9000') && !u.startsWith('data:') && !u.startsWith('blob:')) {
      external.push(u);
    }
  });
  page.on('requestfailed', () => requestFailures++);
  page.on('console', m => {
    if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200));
  });
  await page.goto('http://127.0.0.1:9000/', {waitUntil: 'networkidle', timeout: 60000});
  await page.waitForTimeout(2500);

  const families = sceneFontFamilies(sceneFont);
  const available = await page.evaluate(names => {
    return names.filter(name => {
      try {
        return document.fonts.check(`12px "${name}"`);
      } catch {
        return false;
      }
    });
  }, families);
  const generic = new Set(['sans-serif', 'serif', 'monospace', 'system-ui', 'cursive', 'fantasy']);
  const named = available.filter(name => !generic.has(name.toLowerCase()));
  sceneFonts = {requested: families, available, named_available: named};
  if (named.length === 0) {
    // Generic css families always resolve; only a named local font proves the
    // text is not silently rendered with an arbitrary fallback.
    throw new ContractError(
      CODES.environmentUnavailable,
      `no named scene font is available from: ${families.join(', ')}`,
    );
  }

  const readState = async () => {
    const labels = await page.evaluate(() =>
      Array.from(document.querySelectorAll('button')).map(b => (b.textContent || '').trim()),
    );
    const kind = classifyState(labels);
    return {kind, abort: kind === 'rendering', render: kind === 'idle'};
  };

  const waitForIdle = async (timeoutMs = 15000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const state = await readState();
      if (state.kind === 'idle') return state;
      await page.waitForTimeout(100);
    }
    throw new Error('editor did not return to idle');
  };

  const started = Date.now();
  await page.getByRole('button', {name: 'Render', exact: true}).first().click();

  if (mode === 'cancel') {
    await page.waitForTimeout(cancelAfter);
    const during = await readState();
    const beforeAbort = countFrames(out);
    if (during.abort) {
      await page.getByRole('button', {name: 'Abort', exact: true}).first().click();
    }
    const after = await waitForIdle();
    frames = countFrames(out);
    cancelled = during.abort && after.render && frames > 0 && frames < expected;
    if (cancelled) errorCode = CODES.cancelled;
    elapsed = (Date.now() - started) / 1000;
    console.log('CANCEL', JSON.stringify({during, beforeAbort, after, frames}));
  } else if (mode === 'timeout') {
    await page.waitForTimeout(timeoutAfter);
    const during = await readState();
    timedOut = during.abort;
    if (during.abort) {
      await page.getByRole('button', {name: 'Abort', exact: true}).first().click();
      await waitForIdle();
    }
    if (timedOut) errorCode = CODES.renderTimeout;
    frames = countFrames(out);
    elapsed = (Date.now() - started) / 1000;
    console.log('TIMEOUT', JSON.stringify({during, timedOut, frames}));
  } else {
    let stable = 0;
    let previous = 0;
    const deadline = started + maxRenderMs;
    while (Date.now() < deadline) {
      await page.waitForTimeout(250);
      const next = countFrames(out);
      const now = await readState();
      stable = next === previous ? stable + 1 : 0;
      previous = next;
      if (isRenderComplete({state: now.kind, frames: next, expected, stableSamples: stable})) {
        finished = true;
        break;
      }
    }
    frames = countFrames(out);
    elapsed = (Date.now() - started) / 1000;
    if (finished) validateFrameCount(frames, expected);
    else {
      throw new ContractError(
        CODES.frameMismatch,
        `render did not complete: ${frames} of ${expected} frames`,
      );
    }
  }

  await page.screenshot({path: path.join(out, 'after.png'), fullPage: true});
} catch (error) {
  if (error instanceof ContractError) {
    errorCode = error.code;
    console.log('CONTRACT_ERROR', error.code, error.message);
  } else {
    errorCode = CODES.renderFailed;
    console.log('DRIVER_ERROR', error && error.message ? error.message : String(error));
    console.log('SERVER_LOG', serverLog.slice(-1000));
  }
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  server.stdout?.destroy();
  server.stderr?.destroy();
}

if (mode === 'cancel' && cancelled) errorCode = CODES.cancelled;

if (!outputReady) {
  // The output directory was rejected. Do not write a report into it: that
  // would create an artifact in a directory this build does not own.
  console.log('DRIVER_ERROR', 'OUTPUT_DIR was rejected; no report written');
  process.exit(exitCodeFor(errorCode || CODES.invalidInput));
}

const report = {
  schema_version: '1.1',
  mode,
  build_id: buildId,
  expected_frames: expected,
  expected_editor_version: expectedVersion,
  frames,
  finished,
  cancelled,
  timed_out: timedOut,
  terminal: errorCode ? terminalFor(errorCode) : finished ? 'completed' : 'failed',
  elapsed_s: Number(elapsed.toFixed(2)),
  error_code: errorCode,
  network_policy: 'local-only',
  external_requests: [...new Set(external)].slice(0, 20),
  blocked_requests: uniqueBlocked(blocked).slice(0, 20),
  blocked_count: blocked.length,
  scene_fonts: sceneFonts,
  request_failures: requestFailures,
  console_errors: consoleErrors.slice(0, 10),
};
fs.mkdirSync(out, {recursive: true});
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));

if (errorCode && mode === 'render') process.exit(exitCodeFor(errorCode));
let ok = false;
if (mode === 'render') ok = finished && frames === expected;
if (mode === 'cancel') ok = cancelled;
if (mode === 'timeout') ok = timedOut && frames > 0;
process.exit(ok ? 0 : exitCodeFor(errorCode || CODES.frameMismatch));
