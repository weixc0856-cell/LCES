import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from 'playwright';

import {
  ContractError,
  assertEditorVersion,
  classifyState,
  countFrames,
  isRenderComplete,
  validateFrameCount,
} from './contract.mjs';

// LCES P0 driver. Modes:
//   render  (default) - render the full range and require EXPECTED_FRAMES
//   cancel           - abort mid-render and require partial, unpublished output
//   timeout          - prove the driver can detect and stop a stuck render
const mode = process.env.MODE || 'render';
const expected = Number(process.env.EXPECTED_FRAMES || '300');
const expectedVersion = process.env.EXPECTED_EDITOR_VERSION || '3.17.2';
const cancelAfter = Number(process.env.CANCEL_AFTER_MS || '1200');
const timeoutAfter = Number(process.env.TIMEOUT_MS || '1000');
const maxRenderMs = Number(process.env.MAX_RENDER_MS || '120000');
const out = process.env.OUTPUT_DIR || path.resolve('output');

function resetOutput() {
  fs.mkdirSync(out, {recursive: true});
  for (const entry of fs.readdirSync(out)) {
    fs.rmSync(path.join(out, entry), {recursive: true, force: true});
  }
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

  const readState = async () => {
    const labels = await page.evaluate(() =>
      Array.from(document.querySelectorAll('button')).map(b => (b.textContent || '').trim()),
    );
    const kind = classifyState(labels);
    return {kind, abort: kind === 'rendering', render: kind === 'idle'};
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
    await page.waitForTimeout(1500);
    const after = await readState();
    frames = countFrames(out);
    cancelled = during.abort && after.render && frames > 0 && frames < expected;
    elapsed = (Date.now() - started) / 1000;
    console.log('CANCEL', JSON.stringify({during, beforeAbort, after, frames}));
  } else if (mode === 'timeout') {
    await page.waitForTimeout(timeoutAfter);
    const during = await readState();
    timedOut = during.abort;
    if (during.abort) {
      await page.getByRole('button', {name: 'Abort', exact: true}).first().click();
      await page.waitForTimeout(1500);
    }
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
  }

  await page.screenshot({path: path.join(out, 'after.png'), fullPage: true});
} catch (error) {
  if (error instanceof ContractError) {
    errorCode = error.code;
    console.log('CONTRACT_ERROR', error.code, error.message);
  } else {
    console.log('DRIVER_ERROR', error && error.message ? error.message : String(error));
    console.log('SERVER_LOG', serverLog.slice(-1000));
  }
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  server.stdout?.destroy();
  server.stderr?.destroy();
}

const report = {
  mode,
  expected_frames: expected,
  expected_editor_version: expectedVersion,
  frames,
  finished,
  cancelled,
  timed_out: timedOut,
  elapsed_s: Number(elapsed.toFixed(2)),
  error_code: errorCode,
  external_requests: [...new Set(external)].slice(0, 20),
  request_failures: requestFailures,
  console_errors: consoleErrors.slice(0, 10),
};
fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));

if (errorCode) process.exit(3);
let ok = false;
if (mode === 'render') ok = finished && frames === expected;
if (mode === 'cancel') ok = cancelled;
if (mode === 'timeout') ok = timedOut && frames > 0;
process.exit(ok ? 0 : 2);
