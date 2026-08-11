(function (root) {
  'use strict';

  const STORAGE_PREFIX = 'honghu.analyst-note.pending.v1:';

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
      throw new Error('浏览器无法保存待确认 mutation identity，写入保持关闭。');
    }
    return storage;
  }

  function isDefinitiveFailureStatus(status) {
    return Number.isInteger(status) && status >= 400 && status < 500;
  }

  class MutationCoordinator {
    constructor(storage) {
      this.storage = requireStorage(storage);
      this.inflight = new Map();
    }

    storageKey(scope) {
      const normalized = String(scope || '').trim();
      if (!normalized) throw new Error('mutation scope 不能为空');
      return STORAGE_PREFIX + normalized;
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
      if (!record || record.schema_version !== 'honghu.browser_mutation_identity.v1' ||
          !record.operation_id || !record.payload_sha256) {
        throw new PendingMutationConflict('待确认 mutation identity 不完整，拒绝生成新的 identity。');
      }
      return record;
    }

    async begin({scope, payload, createNoteKey = false, noteKey = null}) {
      const fingerprint = await payloadFingerprint(payload);
      const existing = this.read(scope);
      if (existing) {
        if (existing.payload_sha256 !== fingerprint) {
          throw new PendingMutationConflict(
            '上一笔请求结果仍未确认；请恢复原内容后重试，不能生成新的 operation identity。'
          );
        }
        if (noteKey && existing.note_key && existing.note_key !== noteKey) {
          throw new PendingMutationConflict('待确认 mutation 的 note identity 与当前请求不一致。');
        }
        return {...existing, reused: true};
      }

      const resolvedNoteKey = createNoteKey ? newIdentity('note') : String(noteKey || '').trim();
      if (!resolvedNoteKey) throw new Error('mutation 缺少稳定 note identity');
      const record = {
        schema_version: 'honghu.browser_mutation_identity.v1',
        scope: String(scope),
        operation_id: newIdentity('analyst-note-operation'),
        note_key: resolvedNoteKey,
        payload_sha256: fingerprint,
        created_at: new Date().toISOString()
      };
      this.storage.setItem(this.storageKey(scope), JSON.stringify(record));
      return {...record, reused: false};
    }

    release(scope) {
      this.storage.removeItem(this.storageKey(scope));
    }

    execute({scope, payload, createNoteKey = false, noteKey = null, send}) {
      const normalizedScope = String(scope || '').trim();
      const payloadSignature = stableJson(payload);
      const existing = this.inflight.get(normalizedScope);
      if (existing) {
        if (existing.payloadSignature !== payloadSignature) {
          return Promise.reject(new PendingMutationConflict(
            '同一 mutation 正在提交；内容变化前必须等待当前结果明确。'
          ));
        }
        return existing.promise;
      }

      const promise = this._execute({
        scope: normalizedScope,
        payload,
        createNoteKey,
        noteKey,
        send
      });
      const inflight = {payloadSignature, promise};
      this.inflight.set(normalizedScope, inflight);
      promise.finally(() => {
        if (this.inflight.get(normalizedScope) === inflight) {
          this.inflight.delete(normalizedScope);
        }
      }).catch(() => {});
      return promise;
    }

    async _execute({scope, payload, createNoteKey = false, noteKey = null, send}) {
      const identity = await this.begin({scope, payload, createNoteKey, noteKey});
      let response;
      let body;
      try {
        response = await send(identity);
        body = await response.json();
      } catch (error) {
        return {ok: false, uncertain: true, identity, error};
      }

      if (response.ok && body && body.ok) {
        this.release(scope);
        return {ok: true, uncertain: false, response, body, identity};
      }
      if (isDefinitiveFailureStatus(response.status) || response.ok) {
        this.release(scope);
        return {ok: false, uncertain: false, response, body, identity};
      }
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
