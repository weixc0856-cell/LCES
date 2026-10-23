import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import {CODES, ContractError} from './contract.mjs';
import {prepareOutputDir} from './output-dir.mjs';

const POSIX = process.platform !== 'win32';

function tempDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'lces-output-'));
}

function rejectsInvalid(run, pattern) {
  assert.throws(run, error => {
    assert.ok(error instanceof ContractError, `expected ContractError, got ${error}`);
    assert.equal(error.code, CODES.invalidInput);
    if (pattern) assert.match(error.message, pattern);
    return true;
  });
}

test('rejects a relative path', () => {
  rejectsInvalid(() => prepareOutputDir('output'), /absolute path/);
});

test('rejects an empty path', () => {
  rejectsInvalid(() => prepareOutputDir(''), /not set/);
});

test('creates a missing directory', () => {
  const root = tempDir();
  const out = path.join(root, 'frames');
  assert.equal(prepareOutputDir(out), out);
  assert.ok(fs.statSync(out).isDirectory());
});

test('cleans only artifacts the build owns', () => {
  const out = path.join(tempDir(), 'frames');
  fs.mkdirSync(out);
  fs.writeFileSync(path.join(out, '000000.png'), 'frame');
  fs.writeFileSync(path.join(out, 'report.json'), '{}');
  fs.writeFileSync(path.join(out, 'after.png'), 'png');

  prepareOutputDir(out);

  assert.deepEqual(fs.readdirSync(out), []);
});

test('refuses entries this build does not own', () => {
  const out = path.join(tempDir(), 'frames');
  fs.mkdirSync(out);
  fs.writeFileSync(path.join(out, 'thesis.pdf'), 'not ours');

  rejectsInvalid(() => prepareOutputDir(out), /does not own/);
  assert.ok(fs.existsSync(path.join(out, 'thesis.pdf')), 'foreign files must survive');
});

test('refuses a regular file', () => {
  const out = path.join(tempDir(), 'frames');
  fs.writeFileSync(out, 'file');

  rejectsInvalid(() => prepareOutputDir(out), /not a directory/);
});

test('refuses a symlinked directory', {skip: !POSIX}, () => {
  const root = tempDir();
  const target = path.join(root, 'target');
  fs.mkdirSync(target);
  const out = path.join(root, 'frames');
  fs.symlinkSync(target, out, 'dir');

  rejectsInvalid(() => prepareOutputDir(out), /symlink/);
});

test('refuses a path through a symlinked parent', {skip: !POSIX}, () => {
  const root = tempDir();
  const real = path.join(root, 'real');
  fs.mkdirSync(real);
  const link = path.join(root, 'link');
  fs.symlinkSync(real, link, 'dir');

  rejectsInvalid(() => prepareOutputDir(path.join(link, 'frames')), /symlink/);
  assert.deepEqual(fs.readdirSync(real), [], 'nothing may be created through the link');
});

test('refuses a symlink among owned names', {skip: !POSIX}, () => {
  const root = tempDir();
  const out = path.join(root, 'frames');
  fs.mkdirSync(out);
  const target = path.join(root, 'elsewhere.json');
  fs.writeFileSync(target, '{}');
  fs.symlinkSync(target, path.join(out, 'report.json'));

  rejectsInvalid(() => prepareOutputDir(out), /symlink/);
  assert.ok(fs.existsSync(target), 'the link target must not be touched');
});
