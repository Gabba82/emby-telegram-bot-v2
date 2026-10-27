/* Estado y acciones del panel. Sin DOM. Todo dato viene de la API; aquí solo hay selección,
 * filtros y decisiones del usuario. El servidor decide qué se envía (plan) y qué pasó (resultado).
 */
(function (root) {
  'use strict';

  var Api = root.EmbyApi;
  var MAX_ITEMS = 20, MAX_CHATS = 8;
  var STATUSES = ['sent', 'failed', 'pending', 'uncertain', 'history_unknown'];
  var RECOVERABLE = ['failed', 'pending', 'uncertain', 'history_unknown'];
  var STATUS_LABEL = {
    sent: 'Enviado', failed: 'Fallido', pending: 'Pendiente', uncertain: 'Incierto',
    history_unknown: 'Historial desconocido', skipped: 'Omitido', possible_omission: 'Posible omisión'
  };
  var STATUS_HELP = {
    sent: 'Entrega confirmada.',
    failed: 'El envío falló y se sabe que no llegó.',
    pending: 'En cola, aún sin intento terminado.',
    uncertain: 'Se intentó, pero no se pudo confirmar si llegó.',
    history_unknown: 'No hay evidencia de envío: no se sabe si se envió.'
  };

  function newSession() { return { authenticated: false, csrf: '', mode: 'demo', sends: false, user: null }; }

  function createStore() {
    var subs = [];
    var seq = { catalog: 0, history: 0, plan: 0, chats: 0 };
    var prepareTimer = null, searchTimer = null;
    var resetHooks = [], viewHooks = {}, finishHooks = [];

    var state = {
      boot: 'loading', bootError: null,
      session: newSession(),
      loginBusy: false, loginError: '', notice: '',
      view: 'library',
      chats: { status: 'idle', list: [], error: null },
      library: { status: 'idle', items: [], page: 1, pages: 1, total: 0, error: null, f: { query: '', kind: 'all', chat: '', status: '' } },
      history: { status: 'idle', items: [], page: 1, pages: 1, total: 0, error: null, f: { chat: '', status: '' }, open: {}, detail: {}, recoverMsg: '' },
      known: {},
      selected: [],
      selChats: [],
      mode: 'recover',
      decisions: {},
      plan: { status: 'idle', batch: null, error: null },
      previewIndex: 0,
      confirm: { open: false, ack: false, busy: false, error: null },
      phase: 'compose',
      result: null,
      recovering: false, openGroups: {},
      // Lote exacto de conciliación: {run_id, keys, pairs, saved}. Mientras exista, el plan se prepara SOLO con esas keys.
      scope: null,
      announce: ''
    };

    function emit() { subs.slice().forEach(function (fn) { fn(state); }); }
    function say(msg) { state.announce = msg; }

    // ---------- Sesión ----------

    function applySession(s) {
      state.session = { authenticated: !!s.authenticated, csrf: s.csrf_token || '', mode: s.mode === 'operational' ? 'operational' : 'demo', sends: !!s.sends_enabled, user: s.user || null };
    }

    function resetData() {
      clearTimeout(prepareTimer); clearTimeout(searchTimer);
      seq.catalog++; seq.history++; seq.plan++; seq.chats++;
      state.chats = { status: 'idle', list: [], error: null };
      state.library = { status: 'idle', items: [], page: 1, pages: 1, total: 0, error: null, f: { query: '', kind: 'all', chat: '', status: '' } };
      state.history = { status: 'idle', items: [], page: 1, pages: 1, total: 0, error: null, f: { chat: '', status: '' }, open: {}, detail: {}, recoverMsg: '' };
      state.known = {}; state.selected = []; state.selChats = []; state.mode = 'recover'; state.decisions = {};
      state.plan = { status: 'idle', batch: null, error: null };
      state.previewIndex = 0;
      state.confirm = { open: false, ack: false, busy: false, error: null };
      state.phase = 'compose'; state.result = null; state.view = 'library';
      state.scope = null;
      resetHooks.forEach(function (fn) { fn(); });
    }

    /** Cualquier 401 devuelve al inicio de sesión. Devuelve true si lo era. */
    function lostSession(err) {
      if (!err || err.kind !== 'auth' || !state.session.authenticated) return false;
      resetData();
      state.session = newSession();
      state.notice = 'Tu sesión ha caducado. Vuelve a entrar para continuar.';
      emit();
      return true;
    }

    function init() {
      state.boot = 'loading'; state.bootError = null; emit();
      return Api.session().then(function (s) {
        applySession(s);
        state.boot = 'ready';
        emit();
        if (state.session.authenticated) enterApp();
      }, function (err) {
        state.boot = 'error'; state.bootError = err; emit();
      });
    }

    function enterApp() {
      loadChats();
      loadCatalog(1);
    }

    function login(password) {
      if (state.loginBusy) return Promise.resolve();
      state.loginBusy = true; state.loginError = ''; state.notice = ''; emit();
      return Api.login(password).then(function (s) {
        applySession(s);
        state.loginBusy = false;
        if (state.session.authenticated) { resetData(); enterApp(); say('Sesión iniciada.'); }
        else state.loginError = 'No se pudo iniciar sesión.';
        emit();
      }, function (err) {
        state.loginBusy = false;
        state.loginError = err.kind === 'auth' || err.kind === 'forbidden' || err.kind === 'request' ? (err.message || 'Contraseña incorrecta.') : Api.describe(err);
        // 403 puede ser un token CSRF viejo: se pide uno nuevo en segundo plano
        if (err.kind === 'forbidden') Api.session().then(applySession, function () {});
        emit();
      });
    }

    function logout() {
      return Api.logout().then(function (s) {
        resetData(); applySession(s); state.notice = 'Sesión cerrada.'; emit();
      }, function (err) {
        // sin respuesta no sabemos si se cerró: se comprueba en lugar de suponerlo
        if (lostSession(err)) return;
        say('No se pudo cerrar la sesión: ' + Api.describe(err));
        state.notice = 'No se pudo cerrar la sesión: ' + Api.describe(err);
        emit();
      });
    }

    // ---------- Consultas ----------

    function loadChats() {
      var my = ++seq.chats;
      state.chats.status = 'loading'; state.chats.error = null; emit();
      return Api.chats().then(function (d) {
        if (my !== seq.chats) return;
        state.chats = { status: 'ok', list: d.chats, error: null }; emit();
      }, function (err) {
        if (my !== seq.chats || lostSession(err)) return;
        state.chats.status = 'error'; state.chats.error = err; emit();
      });
    }

    function saveChatAlias(id, alias) {
      return Api.setChatAlias(id, alias).then(function (data) {
        var index = state.chats.list.findIndex(function (chat) { return chat.id === id; });
        if (index >= 0 && data.chat) state.chats.list[index] = data.chat;
        say(data.chat && data.chat.alias ? 'Alias guardado para ' + data.chat.label + '.' : 'Alias eliminado.');
        emit();
      }, function (err) {
        if (lostSession(err)) return;
        say('No se pudo guardar el alias: ' + Api.describe(err));
        emit();
      });
    }

    function remember(items) {
      items.forEach(function (it) { state.known[it.id] = it; });
    }

    function loadCatalog(page) {
      var my = ++seq.catalog, f = state.library.f;
      state.library.status = 'loading'; state.library.error = null;
      emit();
      return Api.catalog({ query: f.query.trim(), kind: f.kind, chat_id: f.chat, status: f.status, page: page || state.library.page }).then(function (d) {
        if (my !== seq.catalog) return;
        remember(d.items);
        state.library = Object.assign(state.library, { status: 'ok', items: d.items, page: d.page || 1, pages: d.pages || 1, total: d.total || 0, error: null });
        emit();
      }, function (err) {
        if (my !== seq.catalog || lostSession(err)) return;
        state.library.status = 'error'; state.library.error = err; emit();
      });
    }

    function loadHistory(page) {
      var my = ++seq.history, f = state.history.f;
      state.history.status = 'loading'; state.history.error = null; emit();
      return Api.history({ chat_id: f.chat, status: f.status, page: page || state.history.page }).then(function (d) {
        if (my !== seq.history) return;
        state.history = Object.assign(state.history, { status: 'ok', items: d.items, page: d.page || 1, pages: d.pages || 1, total: d.total || 0, error: null });
        emit();
      }, function (err) {
        if (my !== seq.history || lostSession(err)) return;
        state.history.status = 'error'; state.history.error = err; emit();
      });
    }

    function loadDelivery(id) {
      var cur = state.history.detail[id];
      state.history.detail[id] = { status: 'loading', data: cur && cur.data, error: null }; emit();
      return Api.delivery(id).then(function (d) {
        state.history.detail[id] = { status: 'ok', data: d, error: null }; emit();
      }, function (err) {
        if (lostSession(err)) return;
        state.history.detail[id] = { status: 'error', data: null, error: err }; emit();
      });
    }

    function toggleDetail(id) {
      var open = !state.history.open[id];
      state.history.open[id] = open;
      if (open && !(state.history.detail[id] && state.history.detail[id].status === 'ok')) loadDelivery(id); else emit();
    }

    function retry(what) {
      if (what === 'chats') loadChats();
      else if (what === 'library') loadCatalog();
      else if (what === 'history') loadHistory();
      else if (what === 'plan') preparePlan();
      else if (what === 'boot') init();
    }

    // ---------- Vistas y filtros ----------

    function setView(v) {
      if ((['library', 'history', 'send'].indexOf(v) < 0 && !viewHooks[v]) || state.view === v) return;
      state.view = v;
      if (viewHooks[v]) viewHooks[v]();
      if (v === 'history' && state.history.status === 'idle') loadHistory(1);
      if (v === 'send' && state.phase === 'compose') preparePlan();
      emit();
    }

    function setLibraryFilter(key, value) {
      state.library.f[key] = value;
      if (key === 'query') {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () { state.library.page = 1; loadCatalog(1); }, 300);
        return;
      }
      state.library.page = 1;
      loadCatalog(1);
    }

    function setHistoryFilter(key, value) {
      state.history.f[key] = value; state.history.page = 1; loadHistory(1);
    }

    function setPage(target, delta) {
      var p = state[target];
      var next = Math.min(Math.max(1, p.page + delta), p.pages);
      if (next === p.page) return;
      if (target === 'library') loadCatalog(next); else loadHistory(next);
    }

    // ---------- Selección ----------

    /** Con un lote exacto de conciliación activo la selección manual está bloqueada: cambiarla ampliaría los pares. */
    function scopeLocked() {
      if (!state.scope) return false;
      say('Hay un lote exacto de conciliación en curso. Cancélalo para elegir títulos o destinos a mano.');
      emit();
      return true;
    }

    function toggleItem(id, on) {
      if (scopeLocked()) return;
      var i = state.selected.indexOf(id);
      var want = on === undefined ? i < 0 : !!on;
      if (want && i < 0) {
        if (state.selected.length >= MAX_ITEMS) { say('Un lote admite como máximo ' + MAX_ITEMS + ' títulos.'); state.notice = ''; emit(); return; }
        state.selected.push(id);
      } else if (!want && i >= 0) state.selected.splice(i, 1);
      afterBatchInputsChanged(); emit();
    }

    function selectVisible() {
      if (scopeLocked()) return;
      var added = 0;
      state.library.items.forEach(function (it) {
        if (state.selected.indexOf(it.id) < 0 && state.selected.length < MAX_ITEMS) { state.selected.push(it.id); added++; }
      });
      if (added < state.library.items.filter(function (it) { return state.selected.indexOf(it.id) < 0; }).length) say('Límite de ' + MAX_ITEMS + ' títulos alcanzado.');
      afterBatchInputsChanged(); emit();
    }

    function clearItems() { if (scopeLocked()) return; state.selected = []; afterBatchInputsChanged(); emit(); }

    function toggleChat(id, on) {
      if (scopeLocked()) return;
      var i = state.selChats.indexOf(id);
      if (on && i < 0) {
        if (state.selChats.length >= MAX_CHATS) { say('Un lote admite como máximo ' + MAX_CHATS + ' destinos.'); emit(); return; }
        state.selChats.push(id);
      } else if (!on && i >= 0) state.selChats.splice(i, 1);
      afterBatchInputsChanged(); emit();
    }

    function setAllChats(on) {
      if (scopeLocked()) return;
      state.selChats = on ? state.chats.list.slice(0, MAX_CHATS).map(function (c) { return c.id; }) : [];
      afterBatchInputsChanged(); emit();
    }

    /** Cambia el lote: lo ya preparado deja de valer y se vuelve a preparar si estamos en Envío. */
    function afterBatchInputsChanged() {
      state.previewIndex = 0;
      state.decisions = pruneDecisions(state.decisions);
      if (state.view === 'send' && state.phase === 'compose') schedulePrepare(); else invalidatePlan();
    }

    function pruneDecisions(dec) {
      var out = {};
      Object.keys(dec).forEach(function (k) {
        var p = k.split('|');
        if (state.selected.indexOf(p[0]) >= 0 && state.selChats.indexOf(p[1]) >= 0) out[k] = dec[k];
      });
      return out;
    }

    // ---------- Preparar (plan persistido en el servidor) ----------

    function invalidatePlan() {
      seq.plan++; clearTimeout(prepareTimer);
      state.plan = { status: 'idle', batch: null, error: null };
    }

    function schedulePrepare() {
      clearTimeout(prepareTimer);
      seq.plan++;
      state.plan.status = state.selected.length && state.selChats.length ? 'loading' : 'idle';
      if (state.plan.status === 'idle') { state.plan.batch = null; state.plan.error = null; return; }
      prepareTimer = setTimeout(preparePlan, 250);
    }

    function preparePlan() {
      clearTimeout(prepareTimer);
      var my = ++seq.plan;
      if (!state.selected.length || !state.selChats.length) { state.plan = { status: 'idle', batch: null, error: null }; emit(); return Promise.resolve(); }
      state.plan.status = 'loading'; state.plan.error = null; emit();
      var scope = state.scope;
      var call = scope
        ? Api.reconPrepare(scope.run_id, scope.keys.slice(), Object.assign({}, state.decisions))
        : Api.prepare({ item_ids: state.selected.slice(), chat_ids: state.selChats.slice(), mode: state.mode, decisions: Object.assign({}, state.decisions) });
      return call.then(function (b) {
        if (my !== seq.plan) return;
        if (Array.isArray(b.recovery_items)) remember(b.recovery_items.map(function (it) { return Object.assign({ kind: 'series' }, it); }));
        if (scope && !scopeRowsExact(scope, b)) {
          // El servidor devolvió pares que no se pidieron: ese lote no se muestra ni se puede confirmar.
          state.plan = { status: 'error', batch: null, error: new Api.ApiError('request', 'El servidor devolvió pares que no estaban en tu selección. El lote se ha descartado y no se puede confirmar; vuelve a Conciliación y prepáralo de nuevo.') };
          emit();
          return;
        }
        state.plan = { status: 'ok', batch: b, error: null };
        state.previewIndex = Math.min(state.previewIndex, Math.max(0, state.selected.length - 1));
        emit();
      }, function (err) {
        if (my !== seq.plan || lostSession(err)) return;
        state.plan.status = 'error'; state.plan.error = err; emit();
      });
    }

    /** Todo par (título, destino) del lote debe estar entre los pares pedidos; nunca se acepta uno de más. */
    function scopeRowsExact(scope, b) {
      return b.rows.every(function (r) { return !!scope.pairs[r.item_id + '|' + r.chat_id]; });
    }

    function setDecision(key, value) {
      if (value === null) delete state.decisions[key]; else state.decisions[key] = value;
      schedulePrepare(); emit();
    }

    /** Decide a la vez todas las filas dudosas (inciertas o sin historial), estén o no ya decididas. */
    function decideAllPending(value) {
      var b = state.plan.batch;
      if (!b) return;
      b.rows.forEach(function (r) {
        if (r.state === 'uncertain' || r.state === 'history_unknown') { if (value === null) delete state.decisions[r.key]; else state.decisions[r.key] = value; }
      });
      schedulePrepare(); emit();
    }

    function clearDecisions() { state.decisions = {}; schedulePrepare(); emit(); }

    function setMode(mode) {
      if (mode === state.mode) return;
      if (state.scope) { say('Un lote de conciliación solo recupera: el reenvío voluntario no está permitido.'); emit(); return; }
      state.mode = mode;
      // al cambiar de modo se descartan las marcas sobre lo ya enviado
      var b = state.plan.batch, dec = {};
      Object.keys(state.decisions).forEach(function (k) {
        var row = b && b.rows.filter(function (r) { return r.key === k; })[0];
        if (!row || row.state !== 'sent') dec[k] = state.decisions[k];
      });
      state.decisions = dec;
      schedulePrepare(); emit();
    }

    function setPreviewIndex(i) {
      var n = state.selected.length;
      state.previewIndex = n ? ((i % n) + n) % n : 0;
      emit();
    }

    // ---------- Confirmar y resultados ----------

    function openConfirm() {
      var b = state.plan.batch;
      if (!canConfirm()) return;
      state.confirm = { open: true, ack: false, busy: false, error: null };
      state.confirm.batchId = b.batch_id;
      emit();
    }

    function closeConfirm() {
      if (state.confirm.busy) return;
      state.confirm = { open: false, ack: false, busy: false, error: null };
      emit();
    }

    function setAck(on) { state.confirm.ack = !!on; emit(); }

    /** Hay plan vigente, completo y el servidor lo da por confirmable. */
    function canConfirm() {
      var p = state.plan, b = p.batch;
      return p.status === 'ok' && !!b && b.can_confirm === true && state.session.sends && !state.confirm.busy;
    }

    function needsDuplicateAck() {
      var b = state.plan.batch;
      return !!b && !!b.rows.some(function (r) { return r.duplicate_risk && (r.action === 'send' || r.action === 'retry'); });
    }

    function confirmSend() {
      var c = state.confirm, b = state.plan.batch;
      if (c.busy || !b || !canConfirm()) return Promise.resolve();
      if (needsDuplicateAck() && !c.ack) { say('Marca la casilla para aceptar el riesgo de duplicados.'); emit(); return Promise.resolve(); }
      c.busy = true; c.error = null; emit();
      var batchId = b.batch_id;
      return Api.confirm(batchId, c.ack).then(function (r) {
        if (isTerminal(r)) finishBatch(r); else holdBatch(r, batchId);
      }, function (err) {
        if (lostSession(err)) return;
        c.busy = false;
        if (Api.isUncertain(err)) {
          // No se sabe si el servidor ejecutó el lote: se consulta ese mismo lote, nunca se crea otro.
          state.confirm = { open: false, ack: false, busy: false, error: null };
          state.phase = 'results';
          state.result = { unknown: true, batchId: batchId, error: err, checking: true };
          emit();
          checkBatch();
        } else {
          c.error = err; emit();
        }
      });
    }

    /** Solo completed e interrupted son finales; cualquier otro estado (p. ej. executing) no se da por terminado. */
    function isTerminal(r) { return !!r && (r.status === 'completed' || r.status === 'interrupted'); }

    /** El servidor devolvió un lote que no ha terminado: se muestra como en curso, sin anunciar fin ni permitir lote nuevo. */
    function holdBatch(r, batchId) {
      state.confirm = { open: false, ack: false, busy: false, error: null };
      state.phase = 'results';
      state.result = { unknown: true, batchId: batchId, error: null, checking: false, checkError: null, notExecuted: false, inProgress: true, status: r.status, partial: Array.isArray(r.results) ? r.results : [], summary: r.summary || {} };
      say('El lote sigue en curso en el servidor; todavía no hay resultado final.');
      emit();
    }

    function finishBatch(r) {
      state.confirm = { open: false, ack: false, busy: false, error: null };
      state.phase = 'results';
      state.result = { unknown: false, batchId: r.batch_id, status: r.status, results: Array.isArray(r.results) ? r.results : [], summary: r.summary || {}, mode: state.mode, at: new Date().toISOString() };
      // el lote ejecutado no se reutiliza ni se arrastran decisiones: lo siguiente se prepara desde cero
      state.plan = { status: 'idle', batch: null, error: null };
      state.decisions = {}; state.mode = 'recover';
      var closed = state.scope;
      if (closed) {
        // el lote exacto ya se ejecutó: se recuerda el run para "Recuperar" y vuelve la selección manual previa
        state.result.scope = { run_id: closed.run_id };
        endScope();
      }
      finishHooks.forEach(function (fn) { fn(closed ? closed.run_id : null); });
      say('Envío terminado: ' + (r.status === 'interrupted' ? 'interrumpido, revisa los resultados.' : 'completado.'));
      emit();
      loadCatalog(); // los estados de la biblioteca ya no son los de antes
      state.history.status = 'idle';
    }

    /** Recupera la respuesta perdida consultando el lote ya creado. */
    function checkBatch() {
      var res = state.result;
      if (!res || !res.unknown) return Promise.resolve();
      res.checking = true; res.checkError = null; emit();
      return Api.batch(res.batchId).then(function (r) {
        if (state.result !== res) return;
        if (r.status === 'prepared') {
          res.checking = false; res.notExecuted = true; res.inProgress = false; res.checkError = null; emit();
        } else if (isTerminal(r)) {
          finishBatch(r);
        } else {
          res.checking = false; res.notExecuted = false; res.inProgress = true; res.status = r.status; res.partial = Array.isArray(r.results) ? r.results : []; res.summary = r.summary || {}; res.checkError = null;
          say('El lote sigue en curso; todavía no hay resultado final.');
          emit();
        }
      }, function (err) {
        if (state.result !== res || lostSession(err)) return;
        res.checking = false; res.checkError = err; emit();
      });
    }

    function backToCompose() {
      state.phase = 'compose'; state.result = null;
      // si el lote no llegó a ejecutarse se conserva (confirmarlo de nuevo es idempotente); si no, se prepara uno nuevo
      if (!state.plan.batch) preparePlan(); else emit();
    }

    /** Tras un resultado: vuelve a Envío con los fallidos, pendientes e inciertos, en modo recuperar. */
    function recoverFromResult() {
      var res = state.result;
      if (!res || !res.results) return;
      if (res.scope) {
        // misma conciliación: solo los pares exactos que quedaron por resolver, nunca items×chats
        var rows = res.results.filter(function (r) { return RECOVERABLE.indexOf(r.status) >= 0; });
        if (!rows.length) return;
        startScope(res.scope.run_id, rows.slice(0, MAX_ITEMS).map(function (r) { return { key: r.key, item_id: r.item_id, chat_id: r.chat_id, title: r.title }; }));
        return;
      }
      var items = [], chats = [];
      res.results.forEach(function (r) {
        if (RECOVERABLE.indexOf(r.status) < 0) return;
        if (items.indexOf(r.item_id) < 0) items.push(r.item_id);
        if (chats.indexOf(r.chat_id) < 0) chats.push(r.chat_id);
      });
      if (!items.length) return;
      state.selected = items.slice(0, MAX_ITEMS); state.selChats = chats.slice(0, MAX_CHATS);
      state.mode = 'recover'; state.decisions = {}; state.phase = 'compose'; state.result = null; state.previewIndex = 0;
      state.plan = { status: 'idle', batch: null, error: null };
      preparePlan();
    }

    function newBatch() {
      state.scope = null;
      state.selected = []; state.selChats = []; state.decisions = {}; state.mode = 'recover';
      state.phase = 'compose'; state.result = null; state.view = 'library'; state.previewIndex = 0;
      invalidatePlan(); emit();
    }

    function viewHistoryAfterResult() {
      state.history.status = 'idle'; state.history.page = 1;
      setView('history');
      if (state.history.status === 'idle') loadHistory(1);
    }

    // ---------- Lote exacto de conciliación ----------

    /** Termina el lote exacto y devuelve la selección manual que había antes. */
    function endScope() {
      var sc = state.scope;
      if (!sc) return;
      state.selected = sc.saved.selected; state.selChats = sc.saved.selChats;
      state.scope = null;
    }

    /**
     * Abre Envío con los pares exactos elegidos en Conciliación. `rows` son filas del run
     * ({key,item_id,chat_id,title,...}); el lote se prepara con sus keys y nunca con items×chats.
     */
    function startScope(runId, rows) {
      if (!runId || !rows || !rows.length || rows.length > MAX_ITEMS) return Promise.resolve();
      if (state.confirm.busy) return Promise.resolve();
      var saved = state.scope ? state.scope.saved : { selected: state.selected.slice(), selChats: state.selChats.slice() };
      var pairs = {}, items = [], chats = [], keys = [];
      rows.forEach(function (r) {
        pairs[r.item_id + '|' + r.chat_id] = true;
        keys.push(r.key);
        if (items.indexOf(r.item_id) < 0) items.push(r.item_id);
        if (chats.indexOf(r.chat_id) < 0) chats.push(r.chat_id);
        if (!state.known[r.item_id]) state.known[r.item_id] = { id: r.item_id, title: r.title, kind: r.item_type === 'Movie' ? 'movie' : 'series', year: null };
      });
      state.scope = { run_id: runId, keys: keys, pairs: pairs, saved: saved };
      state.selected = items; state.selChats = chats;
      state.mode = 'recover'; state.decisions = {};
      state.phase = 'compose'; state.result = null; state.previewIndex = 0;
      state.plan = { status: 'idle', batch: null, error: null };
      state.view = 'send';
      say(plural_(keys.length) + ' en un lote exacto de conciliación. Aún no se ha enviado nada.');
      preparePlan();
      return Promise.resolve();
    }

    function plural_(n) { return n + (n === 1 ? ' par seleccionado' : ' pares seleccionados'); }

    /** Descarta el lote exacto sin enviar y vuelve a la pestaña Conciliación. */
    function cancelScope() {
      if (state.confirm.busy) return;
      invalidatePlan();
      endScope();
      state.decisions = {}; state.mode = 'recover'; state.previewIndex = 0;
      state.confirm = { open: false, ack: false, busy: false, error: null };
      state.phase = 'compose'; state.result = null;
      state.view = 'reconciliation';
      if (viewHooks.reconciliation) viewHooks.reconciliation();
      emit();
    }

    // ---------- Recuperación desde un chat ----------

    /** Selecciona los títulos con envíos por resolver en un chat (máx. MAX_ITEMS) y abre Envío. */
    function prepareRecovery(chatId) {
      if (!chatId || state.recovering) return Promise.resolve();
      if (scopeLocked()) return Promise.resolve();
      state.recovering = true; emit();
      var found = [], truncated = false;
      function fetchStatus(st, page) {
        return Api.catalog({ chat_id: chatId, status: st, page: page }).then(function (d) {
          remember(d.items);
          d.items.forEach(function (it) {
            if (found.indexOf(it.id) >= 0) return;
            if (found.length < MAX_ITEMS) found.push(it.id); else truncated = true;
          });
          if (page < (d.pages || 1) && found.length < MAX_ITEMS) return fetchStatus(st, page + 1);
          if (page < (d.pages || 1)) truncated = true;
        });
      }
      var chain = RECOVERABLE.reduce(function (p, st) { return p.then(function () { return fetchStatus(st, 1); }); }, Promise.resolve());
      return chain.then(function () {
        state.recovering = false;
        if (!found.length) { state.notice = ''; say('No hay nada que recuperar en este chat.'); state.history.recoverMsg = 'No hay nada que recuperar en ese chat.'; emit(); return; }
        state.history.recoverMsg = '';
        state.selected = found; state.selChats = [chatId]; state.mode = 'recover'; state.decisions = {};
        state.phase = 'compose'; state.result = null; state.previewIndex = 0;
        state.plan = { status: 'idle', batch: null, error: null };
        state.view = 'send';
        say(found.length + ' títulos seleccionados para recuperar' + (truncated ? ' (límite de ' + MAX_ITEMS + ')' : '') + '.');
        preparePlan();
      }, function (err) {
        state.recovering = false;
        if (lostSession(err)) return;
        state.history.recoverMsg = 'No se pudo preparar la recuperación: ' + Api.describe(err);
        emit();
      });
    }

    return {
      state: state,
      MAX_ITEMS: MAX_ITEMS, MAX_CHATS: MAX_CHATS,
      subscribe: function (fn) { subs.push(fn); },
      emit: emit,
      init: init, login: login, logout: logout, retry: retry,
      setView: setView, setLibraryFilter: setLibraryFilter, setHistoryFilter: setHistoryFilter, setPage: setPage,
      toggleItem: toggleItem, selectVisible: selectVisible, clearItems: clearItems, toggleChat: toggleChat, setAllChats: setAllChats,
      setDecision: setDecision, decideAllPending: decideAllPending, clearDecisions: clearDecisions, setMode: setMode, setPreviewIndex: setPreviewIndex,
      openConfirm: openConfirm, closeConfirm: closeConfirm, setAck: setAck, confirmSend: confirmSend, canConfirm: canConfirm, needsDuplicateAck: needsDuplicateAck,
      checkBatch: checkBatch, backToCompose: backToCompose, recoverFromResult: recoverFromResult, newBatch: newBatch, viewHistoryAfterResult: viewHistoryAfterResult,
      toggleDetail: toggleDetail, loadDelivery: loadDelivery, prepareRecovery: prepareRecovery, saveChatAlias: saveChatAlias,
      startScope: startScope, cancelScope: cancelScope,
      // enganches para módulos de vista (reconciliation.js)
      registerView: function (name, onEnter) { viewHooks[name] = onEnter; },
      onReset: function (fn) { resetHooks.push(fn); },
      onBatchFinished: function (fn) { finishHooks.push(fn); },
      lostSession: lostSession, say: say,
      selectedItems: function () { return state.selected.map(function (id) { return state.known[id]; }).filter(Boolean); },
      selectedChats: function () { return state.chats.list.filter(function (c) { return state.selChats.indexOf(c.id) >= 0; }); },
      chatLabel: function (id) { var c = state.chats.list.filter(function (x) { return x.id === id; })[0]; return c ? c.label : id; },
      chatOptionLabel: function (id) {
        var c = state.chats.list.filter(function (x) { return x.id === id; })[0];
        if (!c) return id;
        var parts = [c.label];
        if (c.telegram_name && c.telegram_name !== c.label) parts.push(c.telegram_name);
        if (c.id !== c.label) parts.push(c.id);
        return parts.join(' · ');
      }
    };
  }

  root.EmbyStore = { createStore: createStore, STATUSES: STATUSES, RECOVERABLE: RECOVERABLE, STATUS_LABEL: STATUS_LABEL, STATUS_HELP: STATUS_HELP, MAX_ITEMS: MAX_ITEMS, MAX_CHATS: MAX_CHATS };
})(self);
