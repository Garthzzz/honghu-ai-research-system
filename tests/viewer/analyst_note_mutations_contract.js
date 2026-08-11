'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');

require(path.resolve(__dirname, '../../tools/viewer/static/analyst_note_mutations.js'));

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
    const tail = current.catch(() => {}).finally(() => {
      if (this.tails.get(name) === tail) this.tails.delete(name);
    });
    this.tails.set(name, tail);
    return current;
  }
}

function response(status, body, {jsonError = null} = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    async json() {
      if (jsonError) throw jsonError;
      return body;
    }
  };
}

async function main() {
  const {MutationCoordinator, PendingMutationConflict} = globalThis.HonghuAnalystNoteMutations;
  const storage = new MemoryStorage();
  const locks = new MemoryLockManager();
  const coordinator = new MutationCoordinator(storage, locks);
  const create = {
    scope: 'create:company:7',
    principalKey: 'analyst-a',
    payload: {entity_type: 'company', entity_id: '7', content: '研究结论', expected_revision: 0},
    createNoteKey: true
  };

  const first = await coordinator.execute({
    ...create,
    send: async () => { throw new Error('response lost after possible commit'); }
  });
  assert.equal(first.uncertain, true);
  assert.match(first.identity.note_key, /^note:/);
  assert.match(first.identity.operation_id, /^analyst-note-operation:/);
  assert.equal(first.identity.principal_key, 'analyst-a');

  // A newly created tab/coordinator reuses the durable identity after the first tab disappears.
  const reopenedTab = new MutationCoordinator(storage, locks);
  let replayIdentity;
  const replay = await reopenedTab.execute({
    ...create,
    send: async identity => {
      replayIdentity = identity;
      return response(200, {ok: true, note: {note_key: identity.note_key}});
    }
  });
  assert.equal(replay.ok, true);
  assert.equal(replayIdentity.reused, true);
  assert.equal(replayIdentity.note_key, first.identity.note_key);
  assert.equal(replayIdentity.operation_id, first.identity.operation_id);
  assert.equal(reopenedTab.read(create.scope), null);

  // Same-tab double click shares one Promise and sends one request.
  let resolveConcurrent;
  let concurrentSendCount = 0;
  let markConcurrentSendStarted;
  const concurrentSendStarted = new Promise(resolve => { markConcurrentSendStarted = resolve; });
  const concurrentSend = async identity => {
    concurrentSendCount += 1;
    markConcurrentSendStarted();
    return new Promise(resolve => {
      resolveConcurrent = () => resolve(response(200, {ok: true, note: {note_key: identity.note_key}}));
    });
  };
  const concurrentFirst = reopenedTab.execute({...create, send: concurrentSend});
  const concurrentSecond = reopenedTab.execute({...create, send: concurrentSend});
  assert.strictEqual(concurrentSecond, concurrentFirst);
  await assert.rejects(
    reopenedTab.execute({
      ...create,
      payload: {...create.payload, content: '并发修改后的内容'},
      send: concurrentSend
    }),
    error => error instanceof PendingMutationConflict && error.code === 'pending_mutation_conflict'
  );
  await concurrentSendStarted;
  assert.equal(concurrentSendCount, 1);
  resolveConcurrent();
  await Promise.all([concurrentFirst, concurrentSecond]);

  // A second tab sees a live lease and must not emit a second HTTP request.
  let releaseCrossTab;
  let crossTabSends = 0;
  const firstTab = new MutationCoordinator(storage, locks);
  const secondTab = new MutationCoordinator(storage, locks);
  const crossFirst = firstTab.execute({
    ...create,
    send: async identity => {
      crossTabSends += 1;
      return new Promise(resolve => {
        releaseCrossTab = () => resolve(response(200, {ok: true, note: {note_key: identity.note_key}}));
      });
    }
  });
  await new Promise(resolve => setTimeout(resolve, 0));
  const crossSecond = await secondTab.execute({
    ...create,
    send: async () => {
      crossTabSends += 1;
      return response(200, {ok: true});
    }
  });
  assert.equal(crossSecond.uncertain, true);
  assert.equal(crossSecond.pendingElsewhere, true);
  assert.equal(crossTabSends, 1);
  releaseCrossTab();
  await crossFirst;

  const unresolved = await reopenedTab.execute({
    ...create,
    send: async () => response(503, {ok: false, error: 'upstream unavailable'})
  });
  assert.equal(unresolved.uncertain, true);
  const durableOperation = unresolved.identity.operation_id;

  // Login changes do not clear or replace an uncertain operation identity.
  const anotherPrincipal = new MutationCoordinator(storage, locks);
  await assert.rejects(
    anotherPrincipal.execute({...create, principalKey: 'analyst-b', send: async () => response(200, {ok: true})}),
    error => error instanceof PendingMutationConflict && error.code === 'pending_mutation_conflict'
  );
  assert.equal(anotherPrincipal.read(create.scope).operation_id, durableOperation);
  await assert.rejects(
    anotherPrincipal.execute({
      ...create,
      payload: {...create.payload, content: '另一条内容'},
      send: async () => response(200, {ok: true})
    }),
    error => error instanceof PendingMutationConflict && error.code === 'pending_mutation_conflict'
  );

  const exactReplay = await anotherPrincipal.execute({
    ...create,
    send: async identity => response(200, {ok: true, operation_id: identity.operation_id})
  });
  assert.equal(exactReplay.ok, true);
  assert.equal(exactReplay.identity.operation_id, durableOperation);

  const deterministicFailure = await reopenedTab.execute({
    ...create,
    send: async () => response(409, {ok: false, code: 'stale_revision'})
  });
  assert.equal(deterministicFailure.uncertain, false);
  assert.equal(reopenedTab.read(create.scope), null);

  const deleteRequest = {
    scope: 'delete:note:stable-7',
    principalKey: 'analyst-a',
    payload: {note_key: 'note:stable-7', expected_revision: 4},
    noteKey: 'note:stable-7'
  };
  const deleteFirst = await reopenedTab.execute({
    ...deleteRequest,
    send: async () => response(200, null, {jsonError: new Error('truncated response')})
  });
  assert.equal(deleteFirst.uncertain, true);
  const deleteReplay = await reopenedTab.execute({
    ...deleteRequest,
    send: async () => response(200, {ok: true})
  });
  assert.equal(deleteReplay.ok, true);
  assert.equal(deleteReplay.identity.operation_id, deleteFirst.identity.operation_id);
  assert.equal(deleteReplay.identity.note_key, 'note:stable-7');

  const noLocks = new MutationCoordinator(new MemoryStorage(), null);
  await assert.rejects(
    noLocks.execute({...create, send: async () => response(200, {ok: true})}),
    /跨标签页 mutation 互斥/
  );
}

main().catch(error => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
