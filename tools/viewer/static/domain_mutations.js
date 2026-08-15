(function (root) {
  'use strict';

  let coordinator = null;

  function mutationCoordinator() {
    if (!root.HonghuAnalystNoteMutations) {
      throw new Error('stable browser mutation coordinator is unavailable');
    }
    if (!coordinator) {
      coordinator = new root.HonghuAnalystNoteMutations.MutationCoordinator(
        root.localStorage,
        root.navigator && root.navigator.locks
      );
    }
    return coordinator;
  }

  async function session() {
    const response = await root.fetch('/api/user-content/session', {
      credentials: 'same-origin'
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.security_ready) {
      const error = new Error(payload.error || 'trusted mutation security is unavailable');
      error.code = payload.code || 'security_not_ready';
      throw error;
    }
    if (!payload.authenticated || !payload.principal || !payload.csrf_token) {
      const error = new Error('authentication is required before a domain mutation');
      error.code = 'authentication_required';
      throw error;
    }
    return payload;
  }

  async function postJSON(scope, url, payload) {
    const current = await session();
    const normalizedScope = 'domain:' + String(scope);
    const result = await mutationCoordinator().execute({
      scope: normalizedScope,
      payload,
      principalKey: current.principal,
      noteKey: normalizedScope,
      send: identity => root.fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': current.csrf_token,
          'X-Idempotency-Key': identity.operation_id
        },
        body: JSON.stringify(payload)
      })
    });
    if (result.ok) return {ok: true, data: result.body, identity: result.identity};
    if (result.uncertain) {
      return {
        ok: false,
        uncertain: true,
        data: result.body || {error: 'mutation result is uncertain; retry unchanged'},
        identity: result.identity
      };
    }
    return {ok: false, uncertain: false, data: result.body || {}, identity: result.identity};
  }

  root.HonghuDomainMutations = Object.freeze({postJSON, session});
})(typeof globalThis !== 'undefined' ? globalThis : window);
