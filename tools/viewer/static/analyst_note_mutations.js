(function (root) {
  'use strict';

  const STORAGE_PREFIX = 'honghu.analyst-note.pending.v2:';
  const ACTIVE_LEASE_MS = 30000;

  class PendingMutationConflict extends Error {
    constructor(message) {
      super(message);
      this.name = 'PendingMutationConflict';
      this.code = 'pending_mutation_conflict';
    }
  }

  function stableJson(value) {
    if (Array.isArray(value)) return '[' + value.map(stableJson).join(',') + ']';
    if (value && typeof value === 'object') {
      return '{' + Object.keys(value).sort().map(
        key => JSON.stringify(key) + ':' + stableJson(value[key])
      ).join(',') + '}';
    }
    return JSON.stringify(value);
  }

  async function payloadFingerprint(payload) {
    if (!root.crypto || !root.crypto.subtle) {
      throw new Error('浏览器不支持安全的 mutation fingerprint，写入保持关闭。');
    }
    const bytes = new TextEncoder().encode(stableJson(payload));
    const digest = await root.crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  }

  function newIdentity(prefix) {
    if (!root.crypto || typeof root.crypto.randomUUID !== 'function') {
      throw new Error('浏览器不支持安全的 mutation identity，写入保持关闭。');
    }
    return prefix + ':' + root.crypto.randomUUID();
  }

  function requireStorage(storage) {
    if (!storage || typeof storage.getItem !== 'function' ||
        typeof storage.setItem !== 'function' || typeof storage.removeItem !== 'function') {
      throw new Error('浏览器无法持久保存待确认 mutation identity，写入保持关闭。');
    }
    return storage;
  }

  function requirePrincipal(principalKey) {
    const principal = String(principalKey || '').trim();
    if (!principal) throw new Error('mutation 缺少可信登录 principal，写入保持关闭。');
    return principal;
  }

  function isDefinitiveFailureStatus(status) {
    return Number.isInteger(status) && status >= 400 && status < 500;
  }

  class MutationCoordinator {
    constructor(storage, lockManager = root.navigator && root.navigator.locks) {
      this.storage = requireStorage(storage);
      this.lockManager = lockManager;
      this.inflight = new Map();
      this.ownerId = newIdentity('browser-mutation-owner');
    }

    storageKey(scope) {
      const normalized = String(scope || '').trim();
      if (!normalized) throw new Error('mutation scope 不能为空');
      return STORAGE_PREFIX + normalized;
    }

    async withLock(scope, callback) {
      if (!this.lockManager || typeof this.lockManager.request !== 'function') {
        throw new Error('浏览器不支持跨标签页 mutation 互斥，写入保持关闭。');
      }
      return this.lockManager.request(this.storageKey(scope), callback);
    }

    read(scope) {
      const raw = this.storage.getItem(this.storageKey(scope));
      if (!raw) return null;
      let record;
      try {
        record = JSON.parse(raw);
      } catch (error) {
        throw new PendingMutationConflict('待确认 mutation identity 已损坏，拒绝生成新的 identity。');
      }
      if (!record || record.schema_version !== 'honghu.browser_mutation_identity.v2' ||
          !record.operation_id || !record.payload_sha256 || !record.principal_key ||
          !['in_flight', 'uncertain'].includes(record.state)) {
        throw new PendingMutationConflict('待确认 mutation identity 不完整，拒绝生成新的 identity。');
      }
      return record;
    }

    validateExisting(existing, {fingerprint, principal, noteKey}) {
      if (existing.principal_key !== principal) {
        throw new PendingMutationConflict(
          '存在属于其他登录 principal 的待确认 mutation；必须由原 principal 精确重放或人工对账。'
        );
      }
      if (existing.payload_sha256 !== fingerprint) {
        throw new PendingMutationConflict(
          '上一笔请求结果仍未确认；请恢复原内容后重试，不能生成新的 operation identity。'
        );
      }
      if (noteKey && existing.note_key && existing.note_key !== noteKey) {
        throw new PendingMutationConflict('待确认 mutation 的 note identity 与当前请求不一致。');
      }
    }

    async prepare({scope, payload, principalKey, createNoteKey = false, noteKey = null}) {
      const fingerprint = await payloadFingerprint(payload);
      const principal = requirePrincipal(principalKey);
      return this.withLock(scope, async () => {
        const existing = this.read(scope);
        if (existing) {
          this.validateExisting(existing, {fingerprint, principal, noteKey});
          const age = Date.now() - Date.parse(existing.updated_at || existing.created_at);
          if (existing.state === 'in_flight' && existing.owner_id !== this.ownerId &&
              Number.isFinite(age) && age < ACTIVE_LEASE_MS) {
            return {identity: {...existing, reused: true}, deferred: true};
          }
          const claimed = {
            ...existing,
            state: 'in_flight',
            owner_id: this.ownerId,
            updated_at: new Date().toISOString()
          };
          this.storage.setItem(this.storageKey(scope), JSON.stringify(claimed));
          return {identity: {...claimed, reused: true}, deferred: false};
        }

        const resolvedNoteKey = createNoteKey ? newIdentity('note') : String(noteKey || '').trim();
        if (!resolvedNoteKey) throw new Error('mutation 缺少稳定 note identity');
        const now = new Date().toISOString();
        const record = {
          schema_version: 'honghu.browser_mutation_identity.v2',
          scope: String(scope),
          principal_key: principal,
          operation_id: newIdentity('analyst-note-operation'),
          note_key: resolvedNoteKey,
          payload_sha256: fingerprint,
          state: 'in_flight',
          owner_id: this.ownerId,
          created_at: now,
          updated_at: now
        };
        this.storage.setItem(this.storageKey(scope), JSON.stringify(record));
        return {identity: {...record, reused: false}, deferred: false};
      });
    }

    async markUncertain(scope, operationId) {
      await this.withLock(scope, async () => {
        const current = this.read(scope);
        if (!current || current.operation_id !== operationId) return;
        this.storage.setItem(this.storageKey(scope), JSON.stringify({
          ...current,
          state: 'uncertain',
          owner_id: null,
          updated_at: new Date().toISOString()
        }));
      });
    }

    async release(scope, operationId) {
      await this.withLock(scope, async () => {
        const current = this.read(scope);
        if (current && current.operation_id === operationId) {
          this.storage.removeItem(this.storageKey(scope));
        }
      });
    }

    execute({scope, payload, principalKey, createNoteKey = false, noteKey = null, send}) {
      const normalizedScope = String(scope || '').trim();
      const payloadSignature = stableJson({payload, principalKey});
      const existing = this.inflight.get(normalizedScope);
      if (existing) {
        if (existing.payloadSignature !== payloadSignature) {
          return Promise.reject(new PendingMutationConflict(
            '同一 mutation 正在提交；内容或 principal 变化前必须等待当前结果明确。'
          ));
        }
        return existing.promise;
      }

      const promise = this._execute({
        scope: normalizedScope,
        payload,
        principalKey,
        createNoteKey,
        noteKey,
        send
      });
      const inflight = {payloadSignature, promise};
      this.inflight.set(normalizedScope, inflight);
      promise.finally(() => {
        if (this.inflight.get(normalizedScope) === inflight) this.inflight.delete(normalizedScope);
      }).catch(() => {});
      return promise;
    }

    async _execute({scope, payload, principalKey, createNoteKey, noteKey, send}) {
      const prepared = await this.prepare({scope, payload, principalKey, createNoteKey, noteKey});
      const identity = prepared.identity;
      if (prepared.deferred) {
        return {ok: false, uncertain: true, pendingElsewhere: true, identity};
      }
      let response;
      let body;
      try {
        response = await send(identity);
        body = await response.json();
      } catch (error) {
        await this.markUncertain(scope, identity.operation_id);
        return {ok: false, uncertain: true, identity, error};
      }

      if (response.ok && body && body.ok) {
        await this.release(scope, identity.operation_id);
        return {ok: true, uncertain: false, response, body, identity};
      }
      if (isDefinitiveFailureStatus(response.status) || response.ok) {
        await this.release(scope, identity.operation_id);
        return {ok: false, uncertain: false, response, body, identity};
      }
      await this.markUncertain(scope, identity.operation_id);
      return {ok: false, uncertain: true, response, body, identity};
    }
  }

  root.HonghuAnalystNoteMutations = Object.freeze({
    MutationCoordinator,
    PendingMutationConflict,
    isDefinitiveFailureStatus,
    payloadFingerprint
  });
})(typeof globalThis !== 'undefined' ? globalThis : window);
