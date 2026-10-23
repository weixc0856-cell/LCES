import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ALLOWED_SCHEMES,
  BLOCKED_REASON,
  EDITOR_ORIGIN,
  describeRequest,
  installLocalOnlyPolicy,
  isAllowedUrl,
} from './network-policy.mjs';

test('the editor origin is allowed', () => {
  assert.equal(isAllowedUrl(`${EDITOR_ORIGIN}/`), true);
  assert.equal(isAllowedUrl(`${EDITOR_ORIGIN}/src/main.tsx?t=1`), true);
});

test('external http and https hosts are blocked', () => {
  assert.equal(isAllowedUrl('https://fonts.googleapis.com/css2?family=Roboto'), false);
  assert.equal(isAllowedUrl('https://unpkg.com/highlightjs@9.16.2/a.css'), false);
  assert.equal(isAllowedUrl('https://registry.npmjs.org/@motion-canvas/core/latest'), false);
  assert.equal(isAllowedUrl('http://127.0.0.1:9001/'), false);
  assert.equal(isAllowedUrl('http://localhost:9000/'), false);
});

test('data, blob and file schemes are allowed', () => {
  for (const scheme of ALLOWED_SCHEMES) {
    assert.equal(isAllowedUrl(`${scheme}asset`), true, scheme);
  }
});

test('malformed urls are blocked rather than allowed', () => {
  assert.equal(isAllowedUrl('not a url'), false);
  assert.equal(isAllowedUrl(''), false);
});

test('describeRequest drops query strings and fragments and truncates the path', () => {
  const described = describeRequest(
    'https://fonts.googleapis.com/css2?family=Roboto&token=secret#frag',
    'stylesheet',
  );
  assert.deepEqual(described, {
    origin: 'https://fonts.googleapis.com',
    path: '/css2',
    type: 'stylesheet',
    reason: BLOCKED_REASON,
  });
  const long = describeRequest(`https://example.test/${'a'.repeat(120)}`, 'xhr');
  assert.equal(long.path.length, 80);
  assert.ok(long.path.endsWith('...'));
  assert.equal(JSON.stringify(described).includes('secret'), false);
});

test('the policy continues local requests and aborts external ones', async () => {
  const calls = [];
  const page = {route: (pattern, handler) => calls.push({pattern, handler})};
  const blocked = installLocalOnlyPolicy(page);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].pattern, '**/*');
  const handler = calls[0].handler;

  const routeFor = url => ({
    continue: async () => calls.push({action: 'continue', url}),
    abort: async reason => calls.push({action: 'abort', url, reason}),
  });
  const requestFor = (url, type) => ({url: () => url, resourceType: () => type});

  await handler(routeFor(`${EDITOR_ORIGIN}/src/main.tsx`), requestFor(`${EDITOR_ORIGIN}/src/main.tsx`, 'script'));
  await handler(
    routeFor('https://fonts.googleapis.com/css2?family=Roboto'),
    requestFor('https://fonts.googleapis.com/css2?family=Roboto', 'stylesheet'),
  );

  assert.deepEqual(calls[1], {action: 'continue', url: `${EDITOR_ORIGIN}/src/main.tsx`});
  assert.deepEqual(calls[2], {
    action: 'abort',
    url: 'https://fonts.googleapis.com/css2?family=Roboto',
    reason: 'blockedbyclient',
  });
  assert.equal(blocked.length, 1);
  assert.equal(blocked[0].origin, 'https://fonts.googleapis.com');
  assert.equal(blocked[0].type, 'stylesheet');
});

test('an explicit editor origin replaces the default', async () => {
  const calls = [];
  const page = {route: (pattern, handler) => calls.push({handler})};
  installLocalOnlyPolicy(page, {editorOrigin: 'http://127.0.0.1:9100'});
  const actions = [];
  const route = {
    continue: async () => actions.push('continue'),
    abort: async () => actions.push('abort'),
  };
  const request = {url: () => 'http://127.0.0.1:9100/x', resourceType: () => 'document'};
  await calls[0].handler(route, request);
  assert.deepEqual(actions, ['continue']);
});
