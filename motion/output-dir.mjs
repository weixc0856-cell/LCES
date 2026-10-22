import fs from 'node:fs';
import path from 'node:path';

import {CODES, ContractError} from './contract.mjs';

// The only entries a build owns inside OUTPUT_DIR: exported frames and its
// own report/screenshot. Everything else belongs to someone else.
export const OWNED_ENTRY = /^(?:report\.json|after\.png|\d{6}\.png)$/;

function reject(message) {
  throw new ContractError(CODES.invalidInput, message);
}

function samePath(left, right) {
  return process.platform === 'win32' ? left.toLowerCase() === right.toLowerCase() : left === right;
}

// Walk to the nearest existing ancestor before creating anything: mkdir
// through a symlinked parent would already write outside the intended tree.
function assertNoSymlinkAncestor(target) {
  let current = path.dirname(target);
  for (;;) {
    try {
      const stat = fs.lstatSync(current);
      if (stat.isSymbolicLink()) {
        reject(`OUTPUT_DIR resolves through a symlink: ${target}`);
      }
      if (!samePath(fs.realpathSync(current), current)) {
        reject(`OUTPUT_DIR resolves through a symlink: ${target}`);
      }
      return;
    } catch (error) {
      if (error instanceof ContractError) throw error;
      if (error.code !== 'ENOENT') throw error;
    }
    const parent = path.dirname(current);
    if (parent === current) return;
    current = parent;
  }
}

/**
 * Prepare a dedicated frame directory before the editor writes into it.
 *
 * The driver used to delete every entry it found, so a wrong OUTPUT_DIR could
 * clear an unrelated directory. It now requires an absolute, real directory
 * whose contents are only artifacts a previous render of this build could
 * have written, and deletes those explicitly.
 */
export function prepareOutputDir(dir) {
  if (typeof dir !== 'string' || dir.trim() === '') {
    reject('OUTPUT_DIR is not set');
  }
  if (!path.isAbsolute(dir)) {
    reject(`OUTPUT_DIR must be an absolute path: ${dir}`);
  }

  const resolved = path.resolve(dir);
  assertNoSymlinkAncestor(resolved);

  let stat = null;
  try {
    stat = fs.lstatSync(dir);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  if (stat === null) {
    fs.mkdirSync(dir, {recursive: true});
    stat = fs.lstatSync(dir);
  }
  if (stat.isSymbolicLink()) {
    reject(`OUTPUT_DIR must not be a symlink: ${dir}`);
  }
  if (!stat.isDirectory()) {
    reject(`OUTPUT_DIR is not a directory: ${dir}`);
  }

  if (!samePath(fs.realpathSync(dir), resolved)) {
    reject(`OUTPUT_DIR resolves through a symlink: ${dir}`);
  }

  const entries = fs.readdirSync(dir);
  const foreign = entries.filter(name => !OWNED_ENTRY.test(name));
  if (foreign.length > 0) {
    reject(`OUTPUT_DIR contains entries this build does not own: ${foreign.slice(0, 5).join(', ')}`);
  }
  const links = entries.filter(name => fs.lstatSync(path.join(dir, name)).isSymbolicLink());
  if (links.length > 0) {
    reject(`OUTPUT_DIR contains a symlink: ${links[0]}`);
  }

  for (const name of entries) {
    fs.rmSync(path.join(dir, name), {recursive: true, force: true});
  }
  return dir;
}
