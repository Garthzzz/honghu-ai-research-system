'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');

class MemoryStorage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

class MemoryLockManager {
  constructor() { this.tails = new Map(); }
  request(name, callback) {
    const previous = this.tails.get(name) || Promise.resolve();
    const current = previous.catch(() => {}).then(callback);
    this.tails.set(name, current.catch(() => {}));
    return current;
  }
}

globalThis.localStorage = new MemoryStorage();
Object.defineProperty(globalThis, 'navigator', {
  value: {locks: new MemoryLockManager()},
  configurable: true
});
require(path.resolve(__dirname, '../../tools/viewer/static/analyst_note_mutations.js'));
require(path.resolve(__dirname, '../../tools/viewer/static/domain_mutations.js'));

function response(status, body) {
  return {
    status,
    ok: status >= 200 && status < 300,
    async json() { return body; }
  };
}

async function main() {
  const identities = [];
  let mutationAttempt = 0;
  globalThis.fetch = async (url, options = {}) => {
    if (url === '/api/user-content/session') {
      return response(200, {
        security_ready: true,
        authenticated: true,
        principal: 'research-operator',
        csrf_token: 'csrf-1'
      });
    }
    mutationAttempt += 1;
    identities.push(options.headers['X-Idempotency-Key']);
    assert.equal(options.headers['X-CSRF-Token'], 'csrf-1');
    assert.equal(options.credentials, 'same-origin');
    if (mutationAttempt === 1) throw new Error('response lost after possible commit');
    return response(200, {ok: true});
  };

  const payload = {current_status: 'triggered', last_check_note: 'evidence'};
  const first = await globalThis.HonghuDomainMutations.postJSON(
    'hypothesis:/api/hypothesis/7/signal/3/check',
    '/api/hypothesis/7/signal/3/check',
    payload
  );
  assert.equal(first.uncertain, true);
  const replay = await globalThis.HonghuDomainMutations.postJSON(
    'hypothesis:/api/hypothesis/7/signal/3/check',
    '/api/hypothesis/7/signal/3/check',
    payload
  );
  assert.equal(replay.ok, true);
  assert.equal(identities.length, 2);
  assert.equal(identities[0], identities[1]);
  assert.match(identities[0], /^analyst-note-operation:/);

  globalThis.fetch = async () => response(200, {
    security_ready: true,
    authenticated: false,
    csrf_token: 'csrf-2'
  });
  await assert.rejects(
    globalThis.HonghuDomainMutations.postJSON('blocked', '/api/blocked', {}),
    error => error.code === 'authentication_required'
  );
}

main().catch(error => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
