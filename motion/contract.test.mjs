import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import test, {after, before} from 'node:test';
import {chromium} from 'playwright';

import {
  CODES,
  ContractError,
  ERROR_TABLE,
  SUPPORTED_PLATFORMS,
  assertEditorVersion,
  assertSupportedPlatform,
  classifyState,
  countFrames,
  exitCodeFor,
  isRenderComplete,
  readPngSize,
  terminalFor,
  validateFrameCount,
} from './contract.mjs';

const EXPECTED_FRAMES = Number(process.env.EXPECTED_FRAMES || '300');
const EXPECTED_VERSION = process.env.EXPECTED_EDITOR_VERSION || '3.17.2';
const OUT = process.env.OUTPUT_DIR || path.resolve('output');
const PUBLISH = process.env.PUBLISH_DIR || path.resolve('publish');

let server;
let browser;

function startServer() {
  const vite = path.join('node_modules', 'vite', 'bin', 'vite.js');
  server = spawn(process.execPath, [vite, '--port', '9000', '--host', '127.0.0.1'], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.stdout.on('data', () => {});
  server.stderr.on('data', () => {});
  server.on('error', error => console.error('SERVER_ERROR', error.message));
}

async function waitForServer() {
  for (let i = 0; i < 120; i++) {
    try {
      const response = await fetch('http://127.0.0.1:9000/');
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error('vite server did not start');
}

function resetOutput() {
  fs.mkdirSync(OUT, {recursive: true});
  for (const entry of fs.readdirSync(OUT)) {
    fs.rmSync(path.join(OUT, entry), {recursive: true, force: true});
  }
}

function resetPublish() {
  fs.rmSync(PUBLISH, {recursive: true, force: true});
  fs.mkdirSync(PUBLISH, {recursive: true});
  fs.writeFileSync(path.join(PUBLISH, 'asset.txt'), 'sentinel');
}

function firstFrame(dir) {
  for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      const found = firstFrame(full);
      if (found) return found;
    } else if (/^\d{6}\.png$/.test(entry.name)) {
      return full;
    }
  }
  return null;
}

function assertPublishUntouched() {
  assert.equal(fs.readFileSync(path.join(PUBLISH, 'asset.txt'), 'utf8'), 'sentinel');
  assert.equal(fs.existsSync(path.join(PUBLISH, 'final.mp4')), false);
}

async function openEditor() {
  const page = await browser.newPage({viewport: {width: 1600, height: 1000}});
  await page.goto('http://127.0.0.1:9000/', {waitUntil: 'networkidle', timeout: 60000});
  await page.waitForTimeout(2000);
  return page;
}

async function buttonLabels(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll('button')).map(b => (b.textContent || '').trim()),
  );
}

async function waitForState(page, desired, timeoutMs = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const state = classifyState(await buttonLabels(page));
    if (state === desired) return state;
    await page.waitForTimeout(100);
  }
  throw new Error(`timed out waiting for state ${desired}`);
}

async function waitForRender(page) {
  let stable = 0;
  let previous = -1;
  const started = Date.now();
  while (Date.now() - started < 120000) {
    await page.waitForTimeout(250);
    const frames = countFrames(OUT);
    const state = classifyState(await buttonLabels(page));
    stable = frames === previous ? stable + 1 : 0;
    previous = frames;
    if (isRenderComplete({state, frames, expected: EXPECTED_FRAMES, stableSamples: stable})) {
      return frames;
    }
  }
  throw new Error('render did not complete');
}

before(async () => {
  startServer();
  await waitForServer();
  browser = await chromium.launch({args: ['--no-sandbox', '--disable-dev-shm-usage']});
});

after(async () => {
  if (browser) await browser.close();
  if (server) {
    server.kill('SIGTERM');
    server.stdout?.destroy();
    server.stderr?.destroy();
  }
});

test('editor version is pinned', () => {
  const manifest = JSON.parse(
    fs.readFileSync('node_modules/@motion-canvas/core/package.json', 'utf8'),
  );
  assertEditorVersion(manifest.version, EXPECTED_VERSION);
});

test('unknown editor version fails before rendering', () => {
  assert.throws(
    () => assertEditorVersion('9.9.9', EXPECTED_VERSION),
    error => error instanceof ContractError && error.code === CODES.driverProtocolMismatch,
  );
});

test('P1 platform gate rejects non-Linux', () => {
  assertSupportedPlatform('linux');
  assert.throws(
    () => assertSupportedPlatform('win32'),
    error => error instanceof ContractError && error.code === CODES.unsupportedPlatform,
  );
});

test('idle DOM contract', async () => {
  const page = await openEditor();
  try {
    assert.equal(classifyState(await buttonLabels(page)), 'idle');
    assert.equal(await page.getByRole('button', {name: 'Render', exact: true}).count(), 1);
  } finally {
    await page.close();
  }
});

test('ambiguous controls are not guessed', async () => {
  const page = await openEditor();
  try {
    await page.evaluate(() => {
      const button = document.createElement('button');
      button.textContent = 'Abort';
      document.body.appendChild(button);
    });
    await assert.rejects(async () => classifyState(await buttonLabels(page)), error => {
      assert.equal(error.code, CODES.driverProtocolMismatch);
      return true;
    });
    // Missing controls are a non-terminal transition, never a success state.
    assert.equal(classifyState([]), 'transition');
    assert.equal(
      isRenderComplete({state: 'transition', frames: 300, expected: 300, stableSamples: 5}),
      false,
    );
  } finally {
    await page.close();
  }
});

test('lingering ETA does not mean rendering', async () => {
  const page = await openEditor();
  try {
    await page.evaluate(() => {
      const eta = document.createElement('div');
      eta.textContent = 'ETA: 00:00:01';
      document.body.appendChild(eta);
    });
    assert.equal(classifyState(await buttonLabels(page)), 'idle');
  } finally {
    await page.close();
  }
});

test('rendering and completion contract', async () => {
  const page = await openEditor();
  resetOutput();
  resetPublish();
  try {
    await page.getByRole('button', {name: 'Render', exact: true}).first().click();
    await waitForState(page, 'rendering');
    assert.equal(await page.getByRole('button', {name: 'Abort', exact: true}).count(), 1);
    assert.match(await page.locator('body').innerText(), /ETA:/);
    const loading = await page.evaluate(
      () => document.querySelectorAll('[class*=loading]').length,
    );
    assert.ok(loading >= 1, 'expected a loading indicator');

    const frames = await waitForRender(page);
    validateFrameCount(frames, EXPECTED_FRAMES);
    assert.equal(classifyState(await buttonLabels(page)), 'idle');
    assertPublishUntouched();

    const first = firstFrame(OUT);
    assert.ok(first, 'expected a rendered frame');
    const size = readPngSize(first);
    assert.deepEqual(size, {width: 1920, height: 1080});

    // The driver writes after.png into the output; it must not count as a frame.
    assert.equal(fs.existsSync(path.join(OUT, 'after.png')), false);
    fs.writeFileSync(path.join(OUT, 'after.png'), 'screenshot');
    fs.writeFileSync(path.join(OUT, 'report.json'), '{}');
    assert.equal(countFrames(OUT), EXPECTED_FRAMES);
  } finally {
    await page.close();
  }
});

test('frame shortfall fails even when the DOM completes', () => {
  assert.throws(
    () => validateFrameCount(EXPECTED_FRAMES, EXPECTED_FRAMES + 1),
    error => error instanceof ContractError && error.code === CODES.frameMismatch,
  );
  validateFrameCount(EXPECTED_FRAMES, EXPECTED_FRAMES);
});

test('cancel keeps partial output out of publish', async () => {
  const page = await openEditor();
  resetOutput();
  resetPublish();
  try {
    await page.getByRole('button', {name: 'Render', exact: true}).first().click();
    await page.waitForTimeout(1200);
    assert.equal(classifyState(await buttonLabels(page)), 'rendering');
    await page.getByRole('button', {name: 'Abort', exact: true}).first().click();
    await waitForState(page, 'idle');
    const frames = countFrames(OUT);
    assert.ok(frames > 0 && frames < EXPECTED_FRAMES, `partial frames: ${frames}`);
    assertPublishUntouched();
  } finally {
    await page.close();
  }
});

test('timeout leaves no published output', async () => {
  const page = await openEditor();
  resetOutput();
  resetPublish();
  try {
    await page.getByRole('button', {name: 'Render', exact: true}).first().click();
    await page.waitForTimeout(1000);
    assert.equal(classifyState(await buttonLabels(page)), 'rendering');
    await page.getByRole('button', {name: 'Abort', exact: true}).first().click();
    await waitForState(page, 'idle');
    assert.ok(countFrames(OUT) > 0);
    assertPublishUntouched();
  } finally {
    await page.close();
  }
});

test('corrupt frame is rejected structurally', async () => {
  resetOutput();
  const page = await openEditor();
  try {
    await page.getByRole('button', {name: 'Render', exact: true}).first().click();
    await waitForRender(page);
  } finally {
    await page.close();
  }
  const frame = firstFrame(OUT);
  assert.ok(frame, 'expected a rendered frame');
  assert.deepEqual(readPngSize(frame), {width: 1920, height: 1080});

  const broken = path.join(OUT, 'broken.png');
  fs.writeFileSync(broken, fs.readFileSync(frame).subarray(0, 120));
  assert.throws(
    () => readPngSize(broken),
    error => error instanceof ContractError && error.code === CODES.outputCorrupt,
  );
});


test('error table is the single source of truth', () => {
  const names = Object.keys(ERROR_TABLE);
  assert.ok(names.length > 0);
  for (const code of Object.values(CODES)) {
    assert.ok(names.includes(code), `CODES value ${code} missing from the table`);
  }
  const terminals = [...new Set(names.map(name => ERROR_TABLE[name].terminal))].sort();
  assert.deepEqual(terminals, ['cancelled', 'failed']);
  const exits = names.map(name => ERROR_TABLE[name].exit_code);
  assert.equal(new Set(exits).size, exits.length, 'exit codes must be unique');
  for (const name of names) {
    assert.equal(exitCodeFor(name), ERROR_TABLE[name].exit_code);
    assert.equal(terminalFor(name), ERROR_TABLE[name].terminal);
  }
});

test('P0 spike codes stay a subset of the shared table', async () => {
  const spike = await import('../spike/motion-canvas/contract.mjs');
  for (const code of Object.values(spike.CODES)) {
    assert.ok(code in ERROR_TABLE, `spike code ${code} missing from config/error_codes.json`);
  }
  assert.deepEqual(spike.SUPPORTED_PLATFORMS, SUPPORTED_PLATFORMS);
});
