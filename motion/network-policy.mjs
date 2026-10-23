// Local-only network policy for the Motion Canvas driver (P2.3-D).
//
// Scope: this constrains requests the *browser page* makes. It is not
// operating-system isolation — the `--network none` CI job and the offline
// Docker image are what prove the process tree cannot reach the network.
// This policy makes the default explicit and auditable in every build,
// including builds that run on a networked machine.
//
// Evidence rules: URLs are reduced to origin + path. Query strings,
// fragments and credentials never enter the report, because reports are
// uploaded as CI artifacts.

export const EDITOR_ORIGIN = 'http://127.0.0.1:9000';
export const ALLOWED_SCHEMES = ['data:', 'blob:', 'file:'];
export const BLOCKED_REASON = 'blocked-by-policy';
const MAX_PATH = 80;

export function isAllowedUrl(url, editorOrigin = EDITOR_ORIGIN) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (ALLOWED_SCHEMES.includes(parsed.protocol)) return true;
  return parsed.origin === editorOrigin;
}

export function describeRequest(url, resourceType = '') {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return {origin: '', path: '<invalid>', type: resourceType || 'unknown', reason: BLOCKED_REASON};
  }
  const path = parsed.pathname.length > MAX_PATH
    ? `${parsed.pathname.slice(0, MAX_PATH - 3)}...`
    : parsed.pathname;
  return {
    origin: parsed.origin,
    path,
    type: resourceType || 'unknown',
    reason: BLOCKED_REASON,
  };
}

// Install the policy on a Playwright page. Returns the array the handler
// appends blocked requests to; the driver reports a deduplicated view.
export function installLocalOnlyPolicy(page, {editorOrigin = EDITOR_ORIGIN, blocked = []} = {}) {
  page.route('**/*', async (route, request) => {
    const url = request.url();
    if (isAllowedUrl(url, editorOrigin)) {
      await route.continue();
      return;
    }
    blocked.push(describeRequest(url, request.resourceType()));
    await route.abort('blockedbyclient');
  });
  return blocked;
}
