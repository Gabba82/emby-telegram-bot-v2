/* Cliente de la API del panel (contrato docs/EMBY-003-API.md v1).
 * Solo mismo origen (/api/...), cookie de sesión + cabecera X-CSRF-Token en mutaciones.
 * Aquí no hay lógica de entrega: solo transporte y errores con tipo.
 */
(function (root) {
  'use strict';

  var TIMEOUT_MS = 20000;
  var RUN_TIMEOUT_MS = 120000;
  var csrf = '';

  /** kind: network | timeout | protocol | auth | forbidden | conflict | rate | unavailable | server | request */
  function ApiError(kind, message, status, code) {
    this.name = 'ApiError';
    this.kind = kind;
    this.message = message || '';
    this.status = status || 0;
    this.code = code || '';
  }
  ApiError.prototype = Object.create(Error.prototype);

  /** Errores en los que NO sabemos si el servidor llegó a procesar la petición. */
  function isUncertain(err) {
    return !!err && (err.kind === 'network' || err.kind === 'timeout' || err.kind === 'server' || err.kind === 'protocol');
  }

  var DEFAULT_TEXT = {
    network: 'No se pudo contactar con el servidor del panel. Comprueba que sigue en marcha y vuelve a intentarlo.',
    timeout: 'El servidor tardó demasiado en responder.',
    protocol: 'El servidor respondió algo que el panel no entiende.',
    auth: 'La sesión ha caducado o no se ha iniciado.',
    forbidden: 'El servidor ha rechazado la petición.',
    conflict: 'La petición entra en conflicto con el estado actual.',
    rate: 'Demasiados intentos. Espera un momento.',
    unavailable: 'El servicio no está disponible ahora mismo.',
    server: 'El servidor ha fallado al procesar la petición.',
    request: 'La petición no es válida.'
  };
  function describe(err) {
    if (!err) return '';
    if (err.kind === 'network' || err.kind === 'timeout' || err.kind === 'protocol') return DEFAULT_TEXT[err.kind];
    return err.message || DEFAULT_TEXT[err.kind] || 'Error inesperado.';
  }

  function kindOf(status) {
    if (status === 401) return 'auth';
    if (status === 403) return 'forbidden';
    if (status === 409) return 'conflict';
    if (status === 429) return 'rate';
    if (status === 503) return 'unavailable';
    if (status >= 500) return 'server';
    return 'request';
  }

  function qs(params) {
    var out = [];
    Object.keys(params || {}).forEach(function (k) {
      var v = params[k];
      if (v === undefined || v === null || v === '') return;
      out.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
    });
    return out.length ? '?' + out.join('&') : '';
  }

  function request(method, path, body, timeoutMs) {
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    var timedOut = false;
    var timer = ctl ? setTimeout(function () { timedOut = true; ctl.abort(); }, timeoutMs || TIMEOUT_MS) : null;
    var headers = { Accept: 'application/json' };
    var opts = { method: method, headers: headers, credentials: 'same-origin', cache: 'no-store' };
    if (ctl) opts.signal = ctl.signal;
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRF-Token'] = csrf;
      opts.body = JSON.stringify(body || {});
    }
    function done() { if (timer) clearTimeout(timer); }
    return fetch('/api' + path, opts).then(function (res) {
      return res.text().then(function (text) {
        var data;
        try { data = text ? JSON.parse(text) : undefined; } catch (e) { data = undefined; }
        if (res.ok) {
          if (data === null || typeof data !== 'object') throw new ApiError('protocol', '', res.status);
          return data;
        }
        throw new ApiError(kindOf(res.status), data && typeof data.message === 'string' ? data.message : '', res.status, data && typeof data.error === 'string' ? data.error : '');
      });
    }, function () {
      throw new ApiError(timedOut ? 'timeout' : 'network');
    }).then(function (v) { done(); return v; }, function (e) { done(); throw e; });
  }

  function expectArray(data, key) {
    if (!data || !Array.isArray(data[key])) throw new ApiError('protocol');
    return data;
  }

  function session(data) {
    if (!data || typeof data.authenticated !== 'boolean') throw new ApiError('protocol');
    csrf = typeof data.csrf_token === 'string' ? data.csrf_token : '';
    return data;
  }

  var Api = {
    ApiError: ApiError,
    isUncertain: isUncertain,
    describe: describe,
    qs: qs,
    session: function () { return request('GET', '/session').then(session); },
    login: function (password) { return request('POST', '/login', { password: password }).then(session); },
    logout: function () { return request('POST', '/logout', {}).then(session); },
    chats: function () { return request('GET', '/chats').then(function (d) { return expectArray(d, 'chats'); }); },
    setChatAlias: function (id, alias) { return request('POST', '/chats/' + encodeURIComponent(id) + '/alias', { alias: alias }); },
    catalog: function (p) { return request('GET', '/catalog' + qs(p)).then(function (d) { return expectArray(d, 'items'); }); },
    history: function (p) { return request('GET', '/history' + qs(p)).then(function (d) { return expectArray(d, 'items'); }); },
    delivery: function (id) { return request('GET', '/deliveries/' + encodeURIComponent(id)).then(function (d) { return expectArray(d, 'attempts'); }); },
    prepare: function (payload) { return request('POST', '/prepare', payload).then(function (d) { return expectArray(d, 'rows'); }); },
    confirm: function (batchId, acceptDuplicateRisk) {
      return request('POST', '/batches/' + encodeURIComponent(batchId) + '/confirm', { confirm: true, accept_duplicate_risk: !!acceptDuplicateRisk });
    },
    batch: function (batchId) { return request('GET', '/batches/' + encodeURIComponent(batchId)); },

    // Conciliación (contrato docs/EMBY-004-API.md). Ninguna de estas llamadas envía: solo prepare crea un lote sin ejecutar.
    reconConfig: function () { return request('GET', '/reconciliation/config').then(function (d) { return expectArray(d, 'chat_ids'); }); },
    setReconConfig: function (historyFrom) { return request('POST', '/reconciliation/config', { history_from: historyFrom }); },
    /** Consulta síncrona de solo lectura: puede tardar, de ahí el plazo largo. */
    startRun: function (payload) { return request('POST', '/reconciliation/runs', payload, RUN_TIMEOUT_MS); },
    runs: function (page) { return request('GET', '/reconciliation/runs' + qs({ page: page })).then(function (d) { return expectArray(d, 'items'); }); },
    run: function (runId, p) { return request('GET', '/reconciliation/runs/' + encodeURIComponent(runId) + qs(p)).then(function (d) { return expectArray(d, 'items'); }); },
    /** Lote exacto: solo las keys indicadas (pares título×destino), nunca el producto cartesiano. */
    reconPrepare: function (runId, keys, decisions) {
      return request('POST', '/reconciliation/runs/' + encodeURIComponent(runId) + '/prepare', { keys: keys, decisions: decisions || {} }).then(function (d) { return expectArray(d, 'rows'); });
    }
  };

  root.EmbyApi = Api;
})(self);
