import fs from 'node:fs';
import path from 'node:path';
import {crc32} from 'node:zlib';

export const CODES = {
  driverProtocolMismatch: 'driver_protocol_mismatch',
  frameMismatch: 'frame_mismatch',
  outputCorrupt: 'output_corrupt',
};

export class ContractError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.name = 'ContractError';
  }
}

// The editor's DOM text is "Render"/"Abort"; CSS only uppercases it visually.
// ETA or loading classes never decide the state on their own.
export function classifyState(labels) {
  const lowered = labels.map(label => String(label).trim().toLowerCase());
  const render = lowered.includes('render');
  const abort = lowered.includes('abort');
  if (render === abort) {
    throw new ContractError(
      CODES.driverProtocolMismatch,
      `ambiguous render controls: render=${render} abort=${abort}`,
    );
  }
  return abort ? 'rendering' : 'idle';
}

export function assertEditorVersion(actual, expected) {
  if (actual !== expected) {
    throw new ContractError(
      CODES.driverProtocolMismatch,
      `editor version ${actual} does not match pinned ${expected}`,
    );
  }
}

export function validateFrameCount(actual, expected) {
  if (actual !== expected) {
    throw new ContractError(
      CODES.frameMismatch,
      `expected ${expected} frames, found ${actual}`,
    );
  }
}

export function isRenderComplete({state, frames, expected, stableSamples}) {
  return state === 'idle' && frames === expected && stableSamples >= 2;
}

// Frame files are six-digit PNGs; screenshots and reports are not frames.
export function countFrames(dir) {
  let count = 0;
  const walk = current => {
    for (const entry of fs.readdirSync(current, {withFileTypes: true})) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/^\d{6}\.png$/.test(entry.name)) count++;
    }
  };
  if (fs.existsSync(dir)) walk(dir);
  return count;
}

export function readPngSize(file) {
  const data = fs.readFileSync(file);
  const name = path.basename(file);
  if (data.length < 33 || data.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') {
    throw new ContractError(CODES.outputCorrupt, `${name} is not a PNG`);
  }
  let offset = 8;
  let width = 0;
  let height = 0;
  let sawHeader = false;
  let sawEnd = false;
  while (offset + 12 <= data.length) {
    const length = data.readUInt32BE(offset);
    const type = data.subarray(offset + 4, offset + 8).toString('latin1');
    const end = offset + 12 + length;
    if (end > data.length) {
      throw new ContractError(CODES.outputCorrupt, `${name} is truncated at ${type}`);
    }
    const expected = data.readUInt32BE(end - 4);
    const actual = crc32(data.subarray(offset + 4, end - 4)) >>> 0;
    if (expected !== actual) {
      throw new ContractError(CODES.outputCorrupt, `${name} chunk ${type} CRC mismatch`);
    }
    if (!sawHeader && type !== 'IHDR') {
      throw new ContractError(CODES.outputCorrupt, `${name} does not start with IHDR`);
    }
    if (type === 'IHDR') {
      sawHeader = true;
      width = data.readUInt32BE(offset + 8);
      height = data.readUInt32BE(offset + 12);
    }
    if (type === 'IEND') {
      sawEnd = true;
      break;
    }
    offset = end;
  }
  if (!sawHeader || !sawEnd || !width || !height) {
    throw new ContractError(CODES.outputCorrupt, `${name} is missing IHDR/IEND or dimensions`);
  }
  return {width, height};
}
