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
  const coordinator = new MutationCoordinator(storage);
  const create = {
    scope: 'create:company:7',
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

  let replayIdentity;
  const replay = await coordinator.execute({
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
  assert.equal(coordinator.read(create.scope), null);

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
  const concurrentFirst = coordinator.execute({...create, send: concurrentSend});
  const concurrentSecond = coordinator.execute({...create, send: concurrentSend});
  assert.strictEqual(concurrentSecond, concurrentFirst);
  await assert.rejects(
    coordinator.execute({
      ...create,
      payload: {...create.payload, content: '并发修改后的内容'},
      send: concurrentSend
    }),
    error => error instanceof PendingMutationConflict && error.code === 'pending_mutation_conflict'
  );
  await concurrentSendStarted;
  assert.equal(concurrentSendCount, 1);
  resolveConcurrent();
  const [concurrentResultOne, concurrentResultTwo] = await Promise.all([
    concurrentFirst,
    concurrentSecond
  ]);
  assert.strictEqual(concurrentResultOne, concurrentResultTwo);
  assert.equal(concurrentResultOne.ok, true);
  assert.equal(coordinator.read(create.scope), null);

  const unresolved = await coordinator.execute({
    ...create,
    send: async () => response(503, {ok: false, error: 'upstream unavailable'})
  });
  assert.equal(unresolved.uncertain, true);
  await assert.rejects(
    () => coordinator.begin({...create, payload: {...create.payload, content: '另一条内容'}}),
    error => error instanceof PendingMutationConflict && error.code === 'pending_mutation_conflict'
  );
  coordinator.release(create.scope);

  const deterministicFailure = await coordinator.execute({
    ...create,
    send: async () => response(409, {ok: false, code: 'stale_revision'})
  });
  assert.equal(deterministicFailure.uncertain, false);
  assert.equal(coordinator.read(create.scope), null);

  const deleteRequest = {
    scope: 'delete:note:stable-7',
    payload: {note_key: 'note:stable-7', expected_revision: 4},
    noteKey: 'note:stable-7'
  };
  const deleteFirst = await coordinator.execute({
    ...deleteRequest,
    send: async () => response(200, null, {jsonError: new Error('truncated response')})
  });
  assert.equal(deleteFirst.uncertain, true);
  let deleteReplayIdentity;
  const deleteReplay = await coordinator.execute({
    ...deleteRequest,
    send: async identity => {
      deleteReplayIdentity = identity;
      return response(200, {ok: true});
    }
  });
  assert.equal(deleteReplay.ok, true);
  assert.equal(deleteReplayIdentity.operation_id, deleteFirst.identity.operation_id);
  assert.equal(deleteReplayIdentity.note_key, 'note:stable-7');
}

main().catch(error => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
