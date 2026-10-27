/* Pestaña «Conciliación» (contrato docs/EMBY-004-API.md). Consulta de solo lectura + selección manual de pares
 * título×destino. Preparar abre el lote exacto en Envío (store.startScope); aquí nunca se envía nada.
 * attach(store) cuelga el estado en store.state.recon y las acciones en store.recon; view(store) pinta la pestaña.
 */
(function (root) {
  'use strict';

  var Api = root.EmbyApi, V = root.EmbyViews, H = V.h, esc = V.esc;
  var MAX_PAIRS = 20;
  var STATUS_ORDER = ['delivered', 'failed', 'pending', 'uncertain', 'history_unknown', 'possible_omission'];
  var LABEL = {
    delivered: 'Enviado', failed: 'Fallido', pending: 'Pendiente', uncertain: 'Incierto',
    history_unknown: 'Historial desconocido', possible_omission: 'Posible omisión'
  };
  var KIND = { delivered: 'sent', failed: 'failed', pending: 'pending', uncertain: 'uncertain', history_unknown: 'history_unknown', possible_omission: 'possible_omission' };
  var HELP = {
    delivered: 'Hay un envío confirmado para ese título y destino.',
    failed: 'El envío falló y se sabe que no llegó.',
    pending: 'En cola, aún sin intento terminado.',
    uncertain: 'Se intentó, pero no se pudo confirmar si llegó.',
    history_unknown: 'Sin evidencia de envío y sin base para decir que debía haberse enviado.',
    possible_omission: 'Sin evidencia de envío, con fecha dentro del historial conocido y lectura completa. No significa que se perdiera: revísalo antes de enviar.'
  };
  var RUN_STATUS = { complete: ['sent', 'Lectura completa'], partial: ['uncertain', 'Lectura incompleta'], failed: ['failed', 'Lectura fallida'] };
  var SCENARIOS = [['complete', 'Completa'], ['timeout', 'Tiempo agotado a mitad'], ['partial', 'Parcial'], ['duplicates', 'Con duplicados']];
  var TYPES = [['Movie', 'Películas'], ['Episode', 'Episodios']];

  function dateOnly(iso) { return typeof iso === 'string' && /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10) : ''; }
  function fmtDay(iso) {
    var d = new Date(iso);
    return !iso || isNaN(d.getTime()) ? '' : d.toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  /** Estado visible de una fila: sin lectura completa nunca se enseña «posible omisión», aunque llegara así. */
  function effStatus(row, run) {
    var s = LABEL[row.status] ? row.status : 'history_unknown';
    return s === 'possible_omission' && !(run && run.complete) ? 'history_unknown' : s;
  }
  function statusBadge(s) { return H.badge(KIND[s], LABEL[s]); }

  function episodeTag(r) {
    if (r.item_type !== 'Episode') return '';
    var se = (r.season !== null && r.season !== undefined ? 'T' + r.season : '') + (r.episode !== null && r.episode !== undefined ? 'E' + pad2(r.episode) : '');
    return [r.series_name, se].filter(Boolean).join(' · ');
  }
  function rowTitle(r) {
    var tag = episodeTag(r);
    return tag ? tag + ' · ' + r.title : r.title;
  }

  function initial() {
    return {
      config: { status: 'idle', data: null, error: null },
      form: null, formError: '',
      hf: { value: '', ack: false, busy: false, error: '', msg: '' },
      start: { busy: false, error: '', unknown: false },
      runs: { status: 'idle', items: [], page: 1, pages: 1, total: 0, error: null },
      cur: freshCur(null),
      sel: {}, order: [], open: {}
    };
  }
  function freshCur(run) {
    return { status: run ? 'loading' : 'idle', run: run, items: [], page: 1, pages: 1, total: 0, error: null, f: { status: '', chat: '', query: '' }, stale: false };
  }

  function attach(store) {
    var seq = { config: 0, runs: 0, cur: 0 };
    var qTimer = null;
    store.state.recon = initial();

    function R() { return store.state.recon; }
    function emit() { store.emit(); }

    // ---------- Carga ----------

    function loadConfig() {
      var my = ++seq.config;
      R().config.status = 'loading'; R().config.error = null; emit();
      return Api.reconConfig().then(function (d) {
        if (my !== seq.config) return;
        var r = R();
        r.config = { status: 'ok', data: d, error: null };
        if (!r.form) r.form = defaultForm(d);
        r.hf.value = dateOnly(d.history_from);
        emit();
      }, function (err) {
        if (my !== seq.config || store.lostSession(err)) return;
        R().config.status = 'error'; R().config.error = err; emit();
      });
    }

    function defaultForm(d) {
      var df = d.defaults || {};
      return {
        chat_ids: (d.chat_ids || []).slice(),
        library_ids: (d.libraries || []).map(function (l) { return l.id; }),
        item_types: (df.item_types && df.item_types.length ? df.item_types : ['Movie', 'Episode']).slice(),
        date_from: dateOnly(df.date_from), date_to: dateOnly(df.date_to),
        scenario: 'complete'
      };
    }

    function loadRuns(page) {
      var my = ++seq.runs;
      R().runs.status = 'loading'; R().runs.error = null; emit();
      return Api.runs(page || R().runs.page).then(function (d) {
        if (my !== seq.runs) return;
        Object.assign(R().runs, { status: 'ok', items: d.items, page: d.page || 1, pages: d.pages || 1, total: d.total || 0, error: null });
        emit();
      }, function (err) {
        if (my !== seq.runs || store.lostSession(err)) return;
        R().runs.status = 'error'; R().runs.error = err; emit();
      });
    }

    function loadItems(page) {
      var my = ++seq.cur, cur = R().cur, f = cur.f;
      if (!cur.run) return Promise.resolve();
      cur.status = 'loading'; cur.error = null; emit();
      return Api.run(cur.run.run_id, { page: page || cur.page, status: f.status, chat_id: f.chat, query: f.query.trim() }).then(function (d) {
        if (my !== seq.cur) return;
        var c = R().cur;
        if (d.run) c.run = d.run;
        Object.assign(c, { status: 'ok', items: d.items, page: d.page || 1, pages: d.pages || 1, total: d.total || 0, error: null });
        emit();
      }, function (err) {
        if (my !== seq.cur || store.lostSession(err)) return;
        R().cur.status = 'error'; R().cur.error = err; emit();
      });
    }

    function retry(what) {
      if (what === 'config') loadConfig();
      else if (what === 'runs') loadRuns();
      else if (what === 'items') loadItems();
    }

    // ---------- Formulario y fecha de inicio del historial ----------

    function toggleIn(list, value, on) {
      var i = list.indexOf(value);
      if (on && i < 0) list.push(value); else if (!on && i >= 0) list.splice(i, 1);
    }
    function setField(field, value, on) {
      var f = R().form;
      if (!f) return;
      if (field === 'chat_ids' || field === 'library_ids' || field === 'item_types') toggleIn(f[field], value, on);
      else f[field] = value;
      R().formError = '';
      emit();
    }

    function setHistoryValue(v) { R().hf.value = v; R().hf.error = ''; R().hf.msg = ''; emit(); }
    function setHistoryAck(on) { R().hf.ack = !!on; R().hf.error = ''; emit(); }

    /** clear=true quita la fecha (queda «sin fecha conocida», lo más prudente); si no, exige confirmar que es una fecha conocida. */
    function saveHistory(clear) {
      var hf = R().hf, value = null;
      if (hf.busy) return Promise.resolve();
      if (!clear) {
        if (!hf.value) { hf.error = 'Elige una fecha o usa «Quitar fecha».'; emit(); return Promise.resolve(); }
        if (!hf.ack) { hf.error = 'Confirma que es una fecha conocida del registro, no una estimación.'; emit(); return Promise.resolve(); }
        value = hf.value + 'T00:00:00Z';
      }
      hf.busy = true; hf.error = ''; hf.msg = ''; emit();
      return Api.setReconConfig(value).then(function (d) {
        var r = R();
        r.hf.busy = false; r.hf.ack = false;
        if (d && Array.isArray(d.chat_ids)) r.config.data = d;
        else if (r.config.data) r.config.data.history_from = value;
        r.hf.value = dateOnly(r.config.data && r.config.data.history_from);
        r.hf.msg = value ? 'Inicio del historial guardado. Las consultas anteriores conservan la fecha con la que se calcularon: haz una nueva para aplicarla.' : 'Fecha eliminada: sin inicio conocido, nada se marcará como posible omisión.';
        store.say(r.hf.msg);
        emit();
      }, function (err) {
        if (store.lostSession(err)) return;
        var h = R().hf;
        h.busy = false;
        h.error = Api.describe(err) + (Api.isUncertain(err) ? ' No se sabe si se guardó: se recarga la configuración para comprobarlo.' : '');
        if (Api.isUncertain(err)) loadConfig();
        emit();
      });
    }

    // ---------- Consulta ----------

    function startRun() {
      var r = R(), f = r.form, c = r.config.data;
      if (!f || !c || r.start.busy) return Promise.resolve();
      var msg = '';
      if (!f.chat_ids.length) msg = 'Elige al menos un destino.';
      else if ((c.libraries || []).length && !f.library_ids.length) msg = 'Elige al menos una biblioteca.';
      else if (!f.item_types.length) msg = 'Elige películas, episodios o ambos.';
      else if (f.date_from && f.date_to && f.date_from > f.date_to) msg = 'La fecha «Desde» es posterior a «Hasta».';
      if (msg) { r.formError = msg; emit(); return Promise.resolve(); }
      var payload = {
        chat_ids: f.chat_ids.slice(),
        date_from: f.date_from ? f.date_from + 'T00:00:00Z' : null,
        date_to: f.date_to ? f.date_to + 'T23:59:59Z' : null,
        library_ids: f.library_ids.slice(),
        item_types: f.item_types.slice()
      };
      if (c.mode === 'demo') payload.scenario = f.scenario;
      r.formError = ''; r.start = { busy: true, error: '', unknown: false };
      store.say('Consultando la biblioteca…');
      emit();
      return Api.startRun(payload).then(function (run) {
        var r2 = R();
        r2.start.busy = false;
        if (!run || !run.run_id) { r2.start.error = Api.describe(new Api.ApiError('protocol')); emit(); return; }
        r2.sel = {}; r2.order = []; r2.open = {};
        r2.cur = freshCur(run);
        store.say(run.complete ? 'Consulta terminada.' : 'Consulta incompleta: no se marca ninguna omisión.');
        emit();
        loadItems(1);
        loadRuns(1);
      }, function (err) {
        if (store.lostSession(err)) return;
        var s = R().start;
        s.busy = false; s.error = Api.describe(err); s.unknown = Api.isUncertain(err);
        if (s.unknown) loadRuns(1);
        emit();
      });
    }

    function openRun(runId) {
      var r = R(), known = r.runs.items.filter(function (x) { return x.run_id === runId; })[0];
      if (!r.cur.run || r.cur.run.run_id !== runId) { r.sel = {}; r.order = []; r.open = {}; r.cur = freshCur(known || { run_id: runId }); }
      else { r.cur.f = { status: '', chat: '', query: '' }; r.cur.page = 1; r.cur.status = 'loading'; }
      emit();
      return loadItems(1);
    }

    function setFilter(key, value) {
      var cur = R().cur;
      cur.f[key] = value; cur.page = 1;
      if (key === 'query') {
        clearTimeout(qTimer);
        qTimer = setTimeout(function () { loadItems(1); }, 300);
        emit();
        return;
      }
      loadItems(1);
    }

    function setPage(delta) {
      var cur = R().cur, next = Math.min(Math.max(1, cur.page + delta), cur.pages);
      if (next !== cur.page) loadItems(next);
    }
    function setRunsPage(delta) {
      var rs = R().runs, next = Math.min(Math.max(1, rs.page + delta), rs.pages);
      if (next !== rs.page) loadRuns(next);
    }

    // ---------- Selección manual de pares exactos ----------

    function toggleRow(key, on) {
      var r = R(), i = r.order.indexOf(key);
      if (on) {
        if (i >= 0) return;
        var row = r.cur.items.filter(function (x) { return x.key === key; })[0];
        if (!row || !row.can_prepare) return;
        if (r.order.length >= MAX_PAIRS) { store.say('Un lote admite como máximo ' + MAX_PAIRS + ' pares.'); emit(); return; }
        r.sel[key] = row; r.order.push(key);
      } else if (i >= 0) {
        r.order.splice(i, 1); delete r.sel[key];
      }
      emit();
    }

    function selectPage() {
      var r = R(), full = false;
      r.cur.items.forEach(function (row) {
        if (!row.can_prepare || r.sel[row.key]) return;
        if (r.order.length >= MAX_PAIRS) { full = true; return; }
        r.sel[row.key] = row; r.order.push(row.key);
      });
      if (full) store.say('Límite de ' + MAX_PAIRS + ' pares alcanzado.');
      emit();
    }

    function clearSelection() { var r = R(); r.sel = {}; r.order = []; emit(); }
    function toggleDetail(key) { var r = R(); r.open[key] = !r.open[key]; emit(); }

    /** Abre Envío con exactamente los pares elegidos; no envía. */
    function prepare() {
      var r = R();
      if (!r.order.length || !r.cur.run || r.cur.stale || store.state.scope) return;
      store.startScope(r.cur.run.run_id, r.order.map(function (k) {
        var x = r.sel[k];
        return { key: x.key, item_id: x.item_id, chat_id: x.chat_id, title: rowTitle(x), item_type: x.item_type };
      }));
    }

    // ---------- Enganches con el store ----------

    store.registerView('reconciliation', function () {
      var r = R();
      if (r.config.status === 'idle' || r.config.status === 'error') loadConfig();
      if (r.runs.status === 'idle') loadRuns(1);
    });
    store.onReset(function () {
      clearTimeout(qTimer);
      seq.config++; seq.runs++; seq.cur++;
      store.state.recon = initial();
    });
    // La consulta es una instantánea: tras enviar desde ella hay que repetirla para ver estados reales.
    store.onBatchFinished(function (runId) {
      var r = R();
      if (runId && r.cur.run && r.cur.run.run_id === runId) { r.cur.stale = true; r.sel = {}; r.order = []; }
    });

    store.recon = {
      retry: retry, setField: setField, setHistoryValue: setHistoryValue, setHistoryAck: setHistoryAck, saveHistory: saveHistory,
      startRun: startRun, openRun: openRun, setFilter: setFilter, setPage: setPage, setRunsPage: setRunsPage,
      toggleRow: toggleRow, selectPage: selectPage, clearSelection: clearSelection, toggleDetail: toggleDetail, prepare: prepare
    };
  }

  // ---------- Vista ----------

  function note(cls, role, html) { return '<div class="alert ' + cls + '"' + (role ? ' role="' + role + '"' : '') + '>' + html + '</div>'; }
  function retryBtn(what, label) {
    return '<div class="btn-row"><button type="button" class="btn btn--sm" data-fid="recon-retry-' + what + '" data-action="recon-retry" data-id="' + what + '">' + esc(label || 'Reintentar consulta') + '</button></div>';
  }

  function checkList(legend, name, options, selected, firstFid) {
    if (!options.length) return '';
    return '<fieldset class="inline-opts"><legend>' + esc(legend) + '</legend>' + options.map(function (o, i) {
      return '<label class="check"><input type="checkbox" data-fid="' + (i === 0 && firstFid ? firstFid : 'rf-' + name + '-' + esc(o[0])) + '" data-action="recon-field" data-field="' + name + '" data-value="' + esc(o[0]) + '"' + (selected.indexOf(o[0]) >= 0 ? ' checked' : '') + '><span>' + esc(o[1]) + '</span></label>';
    }).join('') + '</fieldset>';
  }

  function formPanel(store, r) {
    var head = '<section class="panel" aria-labelledby="h-rq"><h3 id="h-rq"><span class="step">1</span> Consulta</h3>';
    var c = r.config;
    if (c.status === 'error') return head + note('alert--err', 'alert', '<p><b>No se pudo cargar la configuración.</b> ' + esc(Api.describe(c.error)) + '</p>' + retryBtn('config')) + '</section>';
    if (c.status !== 'ok' || !r.form) return head + H.spinner('Cargando la configuración…') + '</section>';
    var d = c.data, f = r.form, demo = d.mode === 'demo';
    var chats = (d.chat_ids || []).map(function (id) { return [id, store.chatLabel(id)]; });
    var libs = (d.libraries || []).map(function (l) { return [l.id, l.label || l.id]; });
    var scen = demo
      ? '<label class="field"><span>Escenario de prueba (solo demostración)</span><select data-fid="rf-scenario" data-action="recon-field" data-field="scenario">' + SCENARIOS.map(function (s) {
        return '<option value="' + s[0] + '"' + (f.scenario === s[0] ? ' selected' : '') + '>' + esc(s[1]) + '</option>';
      }).join('') + '</select></label>' : '';
    return head +
      '<p class="muted small">Elige qué parte de la biblioteca y qué destinos comparar. La consulta solo lee: no envía ni cambia nada. Las fechas se interpretan en UTC (de 00:00 a 23:59).</p>' +
      '<form id="recon-form" class="rform" novalidate>' +
      checkList('Destinos', 'chat_ids', chats, f.chat_ids, 'rf-first') +
      checkList('Bibliotecas', 'library_ids', libs, f.library_ids) +
      checkList('Tipo de título', 'item_types', TYPES, f.item_types, chats.length ? '' : 'rf-first') +
      '<div class="toolbar">' +
      '<label class="field"><span>Añadidos desde</span><input type="date" data-fid="rf-date_from" data-action="recon-field" data-field="date_from" value="' + esc(f.date_from) + '"></label>' +
      '<label class="field"><span>Añadidos hasta</span><input type="date" data-fid="rf-date_to" data-action="recon-field" data-field="date_to" value="' + esc(f.date_to) + '"></label>' +
      scen + '</div>' +
      (r.formError ? '<p class="login__error" role="alert">' + esc(r.formError) + '</p>' : '') +
      (r.start.error ? note(r.start.unknown ? 'alert--warn' : 'alert--err', 'alert', '<p><b>' + (r.start.unknown ? 'No sabemos si la consulta terminó.' : 'La consulta falló.') + '</b> ' + esc(r.start.error) +
        (r.start.unknown ? ' Es de solo lectura: puedes repetirla sin riesgo o mirar el histórico de consultas, abajo, por si se llegó a guardar.' : '') + '</p>') : '') +
      '<div class="btn-row"><button type="submit" class="btn btn--primary" data-fid="rf-submit"' + (r.start.busy ? ' disabled' : '') + '>' + (r.start.busy ? 'Consultando…' : 'Consultar biblioteca') + '</button></div>' +
      (r.start.busy ? H.spinner('Leyendo la biblioteca por páginas. Puede tardar; no se envía nada.') : '') +
      '</form></section>';
  }

  function historyPanel(r) {
    var head = '<section class="panel" aria-labelledby="h-hf"><h3 id="h-hf"><span class="step">2</span> Inicio del historial</h3>';
    var c = r.config;
    if (c.status !== 'ok') return head + '<p class="muted small">Se muestra cuando carga la configuración.</p></section>';
    var hf = r.hf, saved = c.data.history_from, demo = c.data.mode === 'demo';
    return head +
      '<p class="muted small">Es la fecha desde la que el historial de entregas está completo: solo desde ahí la falta de un envío puede ser una «posible omisión». ' +
      '<b>Debe ser una fecha conocida de registro, no una conjetura</b>: no se deduce de contenido antiguo ni del primer envío. Es independiente del filtro de fechas de la consulta.</p>' +
      '<p>' + (saved ? 'Guardado: <b>' + esc(fmtDay(saved)) + '</b> (UTC)' + (demo ? ' · fecha sintética de demostración' : '') + '.' : '<b class="warn">Sin fecha conocida.</b> Mientras no haya una, ninguna fila se marcará como posible omisión: las que no tengan evidencia saldrán como «historial desconocido».') + '</p>' +
      '<form id="recon-hf-form" class="rform" novalidate><div class="toolbar">' +
      '<label class="field"><span>Fecha de inicio conocida</span><input type="date" data-fid="hf-date" data-action="recon-hf-date" value="' + esc(hf.value) + '"></label>' +
      '<label class="check"><input type="checkbox" data-fid="hf-ack" data-action="recon-hf-ack"' + (hf.ack ? ' checked' : '') + '><span>Confirmo que es una fecha conocida del registro, no una estimación</span></label></div>' +
      (hf.error ? '<p class="login__error" role="alert">' + esc(hf.error) + '</p>' : '') +
      (hf.msg ? '<p class="alert alert--ok" role="status">' + esc(hf.msg) + '</p>' : '') +
      '<div class="btn-row"><button type="submit" class="btn" data-fid="hf-save"' + (hf.busy ? ' disabled' : '') + '>' + (hf.busy ? 'Guardando…' : 'Guardar fecha') + '</button>' +
      '<button type="button" class="btn btn--ghost" data-fid="hf-clear" data-action="recon-hf-clear"' + (hf.busy || !saved ? ' disabled' : '') + '>Quitar fecha</button></div></form></section>';
  }

  function scopeText(store, run, r) {
    var sc = run.scope || {}, bits = [];
    if (sc.chat_ids && sc.chat_ids.length) bits.push('Destinos: ' + sc.chat_ids.map(function (id) { return esc(store.chatLabel(id)); }).join(', '));
    if (sc.library_ids && sc.library_ids.length) {
      var libs = (r.config.data && r.config.data.libraries) || [];
      bits.push('Bibliotecas: ' + sc.library_ids.map(function (id) { var l = libs.filter(function (x) { return x.id === id; })[0]; return esc(l ? l.label : id); }).join(', '));
    }
    if (sc.item_types && sc.item_types.length) bits.push('Tipos: ' + sc.item_types.map(function (t) { return t === 'Movie' ? 'películas' : t === 'Episode' ? 'episodios' : esc(t); }).join(', '));
    if (sc.date_from || sc.date_to) bits.push('Añadidos ' + (sc.date_from ? 'desde ' + esc(fmtDay(sc.date_from)) : '') + (sc.date_from && sc.date_to ? ' ' : '') + (sc.date_to ? 'hasta ' + esc(fmtDay(sc.date_to)) : ''));
    var hfrom = 'history_from' in sc ? sc.history_from : null;
    if ('history_from' in sc) bits.push('Inicio del historial: ' + (hfrom ? esc(fmtDay(hfrom)) : '<b>sin fecha conocida</b>'));
    return bits.length ? '<p class="small muted">' + bits.join(' · ') + '</p>' : '';
  }

  function pageNav(action, p) {
    if (p.pages <= 1 && p.total <= 0) return '';
    return '<nav class="pagination" aria-label="Paginación"><button type="button" class="btn btn--ghost btn--sm" data-fid="' + action + '-prev" data-action="' + action + '" data-id="-1"' + (p.page <= 1 ? ' disabled' : '') + '>‹ Anterior</button>' +
      '<span class="pagination__label" role="status">Página ' + p.page + ' de ' + p.pages + ' · ' + H.plural(p.total, 'resultado', 'resultados') + '</span>' +
      '<button type="button" class="btn btn--ghost btn--sm" data-fid="' + action + '-next" data-action="' + action + '" data-id="1"' + (p.page >= p.pages ? ' disabled' : '') + '>Siguiente ›</button></nav>';
  }

  function detail(row, run, store) {
    var s = effStatus(row, run);
    function dt(k, v) { return '<div><dt>' + k + '</dt><dd>' + v + '</dd></div>'; }
    var tag = episodeTag(row);
    return '<dl class="rdetail">' +
      dt('Motivo', esc(row.reason || 'Sin motivo indicado')) +
      dt('Estado', esc(LABEL[s]) + (s !== row.status ? ' <span class="muted">(el servidor indicó «' + esc(LABEL[row.status] || row.status) + '», pero la lectura no está completa)</span>' : '')) +
      dt('Id del título', '<code>' + esc(row.item_id) + '</code>') +
      dt('Tipo', row.item_type === 'Movie' ? 'Película' : 'Episodio' + (tag ? ' · ' + esc(tag) : '')) +
      dt('Destino', esc(row.chat_label || store.chatLabel(row.chat_id)) + ' · <code>' + esc(row.chat_id) + '</code>') +
      dt('Evento', row.event === 'library' ? 'Publicación de biblioteca' : esc(row.event)) +
      dt('Biblioteca', esc(row.library_id || '—')) +
      dt('Añadido', row.added_at ? esc(H.fmtDateTime(row.added_at)) : 'Sin fecha') +
      dt('Entrega registrada', row.delivery_id !== null && row.delivery_id !== undefined ? '#' + esc(row.delivery_id) : 'Ninguna') +
      dt('Intentos', esc(row.attempt_count || 0)) +
      dt('Dentro del ámbito y del historial conocido', row.eligible ? 'Sí' : 'No') +
      dt('Se puede preparar', row.can_prepare ? 'Sí' : 'No') + '</dl>';
  }

  function rowItem(row, run, r, store) {
    var s = effStatus(row, run), on = !!r.sel[row.key], full = !on && r.order.length >= MAX_PAIRS, open = !!r.open[row.key];
    var who = esc(row.title) + ' en ' + esc(row.chat_label || row.chat_id);
    var disabled = !row.can_prepare || full || r.cur.stale;
    var sub = [row.item_type === 'Movie' ? 'Película' : 'Episodio', episodeTag(row), row.chat_label || row.chat_id, row.added_at ? 'añadido ' + H.fmtDateTime(row.added_at) : 'sin fecha de alta'].filter(Boolean).map(esc).join(' · ');
    return '<li class="rrow' + (on ? ' is-selected' : '') + '">' +
      '<label class="rrow__pick"><input type="checkbox" data-fid="rr-' + esc(row.key) + '" data-action="recon-toggle" data-key="' + esc(row.key) + '"' + (on ? ' checked' : '') + (disabled ? ' disabled' : '') + ' aria-label="Seleccionar ' + who + '"><span class="sr-only">Seleccionar</span></label>' +
      '<div class="rrow__main"><strong>' + esc(row.title) + '</strong><span class="muted small">' + sub + '</span>' +
      '<span class="small">' + esc(row.reason || '') + '</span>' +
      (row.can_prepare ? '' : '<span class="small muted">No se puede preparar desde aquí' + (s === 'delivered' ? ': ya consta como enviado.' : '.') + '</span>') + '</div>' +
      '<div class="rrow__state">' + statusBadge(s) + '</div>' +
      '<div class="rrow__more"><button type="button" class="btn btn--ghost btn--sm" data-fid="rd-' + esc(row.key) + '" data-action="recon-detail" data-id="' + esc(row.key) + '" aria-expanded="' + open + '">' + (open ? 'Ocultar detalle' : 'Ver detalle') + '</button>' +
      (open ? '<div class="rrow__detail">' + detail(row, run, store) + '</div>' : '') + '</div></li>';
  }

  function runPanel(store, r) {
    var cur = r.cur, run = cur.run, head = '<section class="panel" aria-labelledby="h-rr"><h3 id="h-rr"><span class="step">3</span> Resultado de la consulta</h3>';
    if (!run) return head + '<p class="empty">Todavía no hay ninguna consulta abierta. Lanza una nueva o abre una del histórico.</p></section>';
    if (!run.summary) {
      return head + (cur.status === 'error' ? note('alert--err', 'alert', '<p><b>No se pudo cargar la consulta.</b> ' + esc(Api.describe(cur.error)) + '</p>' + retryBtn('items')) : H.spinner('Cargando la consulta…')) + '</section>';
    }
    var sum = run.summary || {}, f = cur.f, busy = cur.status === 'loading';
    var meta = 'Consulta <code>' + esc(run.run_id) + '</code> · ' + esc(H.fmtDateTime(run.created_at)) + ' · ' + H.plural(run.scanned || 0, 'título leído', 'títulos leídos') + ' de ' + (run.total || 0) +
      (run.duplicates ? ' · ' + H.plural(run.duplicates, 'duplicado', 'duplicados') : '') + ' · ' + H.plural(run.pages || 0, 'página', 'páginas');
    var incomplete = !run.complete
      ? note('alert--warn', 'alert', '<p><b>Lectura incompleta.</b> ' + (run.status === 'failed' ? 'La consulta falló' : 'La consulta se cortó') + ' antes de leer toda la biblioteca. Lo que no se llegó a leer no se puede dar por ausente, así que <b>ninguna fila se marca como posible omisión</b>. ' +
        'Puedes examinar lo leído y, si procede, preparar filas a mano; para una comparación fiable haz una nueva consulta.</p><div class="btn-row"><button type="button" class="btn btn--primary btn--sm" data-fid="recon-new" data-action="recon-new">Nueva consulta</button></div>')
      : '';
    var issues = (run.issues || []).length
      ? '<ul class="issues" aria-label="Avisos de la consulta">' + run.issues.map(function (i) { return '<li class="alert alert--info"><code>' + esc(i.code) + '</code> ' + esc(i.message) + '</li>'; }).join('') + '</ul>' : '';
    var stale = cur.stale
      ? note('alert--info', 'status', '<p><b>Esta consulta es una instantánea anterior a tu envío.</b> Las filas siguen mostrando el estado de entonces, no el actual. Haz una nueva consulta para ver el resultado real; mientras tanto no se pueden preparar más pares desde aquí.</p><div class="btn-row"><button type="button" class="btn btn--primary btn--sm" data-fid="recon-new" data-action="recon-new">Nueva consulta</button></div>')
      : '';
    var tiles = '<ul class="rtiles" aria-label="Resumen por estado">' + STATUS_ORDER.map(function (s) {
      var shown = s === 'possible_omission' && !run.complete ? 0 : (sum[s] || 0);
      return '<li><button type="button" class="rtile s-' + KIND[s] + '" data-fid="tile-' + s + '" data-action="recon-tile" data-id="' + s + '" aria-pressed="' + (f.status === s) + '" title="' + esc(HELP[s]) + '">' +
        H.icon(KIND[s]) + '<b>' + shown + '</b><span>' + esc(LABEL[s]) + '</span></button></li>';
    }).join('') + '</ul>';
    var chatIds = (r.config.data && r.config.data.chat_ids) || [];
    var filters = '<div class="toolbar">' +
      '<label class="field field--grow"><span>Buscar</span><input type="search" data-fid="recon-q" data-action="recon-q" value="' + esc(f.query) + '" placeholder="Título o serie" autocomplete="off"></label>' +
      '<label class="field"><span>Estado</span><select data-fid="recon-status" data-action="recon-status"><option value="">Todos</option>' + STATUS_ORDER.map(function (s) {
        return '<option value="' + s + '"' + (f.status === s ? ' selected' : '') + '>' + esc(LABEL[s]) + '</option>';
      }).join('') + '</select></label>' +
      '<label class="field"><span>Destino</span><select data-fid="recon-chat" data-action="recon-chat"><option value="">Todos</option>' + chatIds.map(function (id) {
        return '<option value="' + esc(id) + '"' + (f.chat === id ? ' selected' : '') + '>' + esc(store.chatLabel(id)) + '</option>';
      }).join('') + '</select></label></div>';
    var body;
    if (cur.status === 'error' && !cur.items.length) body = note('alert--err', 'alert', '<p><b>No se pudieron cargar las filas.</b> ' + esc(Api.describe(cur.error)) + '</p>' + retryBtn('items'));
    else if (cur.status === 'loading' && !cur.items.length) body = H.spinner('Cargando filas…');
    else body = (cur.status === 'error' ? note('alert--err', 'alert', '<p><b>No se pudo actualizar la lista.</b> ' + esc(Api.describe(cur.error)) + '</p>' + retryBtn('items')) : '') +
      (cur.items.length
        ? '<ul class="rlist' + (busy ? ' is-busy' : '') + '" aria-label="Filas de la consulta" aria-busy="' + busy + '">' + cur.items.map(function (row) { return rowItem(row, run, r, store); }).join('') + '</ul>'
        : '<p class="empty">Ninguna fila coincide con los filtros.</p>') + pageNav('recon-page', cur);
    var legend = '<details class="legend-box"><summary>Qué significa cada estado</summary><ul class="legend">' + STATUS_ORDER.map(function (s) {
      return '<li>' + statusBadge(s) + '<span class="legend__help">' + esc(HELP[s]) + '</span></li>';
    }).join('') + '</ul></details>';
    return head + '<p class="small muted">' + meta + '</p>' + scopeText(store, run, r) +
      '<p class="small muted">Es una instantánea: no se actualiza sola cuando cambia el historial.</p>' +
      incomplete + stale + issues + tiles + filters + body + legend + '</section>';
  }

  function selectionBar(store, r) {
    var cur = r.cur;
    if (!cur.run || !cur.run.summary) return '';
    var n = r.order.length, sc = store.state.scope;
    var why = cur.stale ? 'Haz una nueva consulta.' : sc ? 'Ya hay un lote exacto abierto.' : !n ? 'Marca filas para preparar.' : '';
    var list = n
      ? '<details class="selsum" data-action="group-toggle" data-id="recon-sel"' + (store.state.openGroups['recon-sel'] ? ' open' : '') + '><summary data-fid="recon-sel-sum">Ver los ' + n + ' pares seleccionados</summary><ul class="selchips">' + r.order.map(function (k) {
        var x = r.sel[k];
        return '<li class="selchip"><span>' + esc(rowTitle(x)) + ' → <b>' + esc(x.chat_label || x.chat_id) + '</b></span>' +
          '<button type="button" class="iconbtn" data-fid="rm-' + esc(k) + '" data-action="recon-remove" data-id="' + esc(k) + '" aria-label="Quitar ' + esc(x.title) + ' en ' + esc(x.chat_label || x.chat_id) + ' de la selección">' + H.icon('failed') + '</button></li>';
      }).join('') + '</ul></details>' : '';
    var blocked = !n || cur.stale || !!sc;
    return list + '<div class="actionbar" role="region" aria-label="Selección de pares"><p class="actionbar__text"><b>' + n + ' de ' + MAX_PAIRS + '</b> pares título × destino seleccionados' +
      (why ? ' · <span class="warn" id="recon-why">' + esc(why) + '</span>' : '') +
      '<span class="muted small block">«Preparar recuperación» solo arma el lote en Envío: nada se envía hasta que lo revises y lo confirmes allí.</span></p>' +
      '<div class="btn-row"><button type="button" class="btn btn--ghost" data-action="recon-select-page"' + (cur.items.some(function (x) { return x.can_prepare; }) && !cur.stale ? '' : ' disabled') + '>Seleccionar esta página</button>' +
      '<button type="button" class="btn btn--ghost" data-action="recon-clear"' + (n ? '' : ' disabled') + '>Vaciar</button>' +
      '<button type="button" class="btn btn--primary" data-fid="recon-prepare" data-action="recon-prepare"' + (blocked ? ' aria-disabled="true" aria-describedby="recon-why"' : '') + '>Preparar recuperación</button></div></div>';
  }

  function pastRuns(store, r) {
    var rs = r.runs, head = '<section class="panel" aria-labelledby="h-rh"><h3 id="h-rh">Consultas anteriores</h3>';
    var body;
    if (rs.status === 'error' && !rs.items.length) body = note('alert--err', 'alert', '<p><b>No se pudo cargar el histórico.</b> ' + esc(Api.describe(rs.error)) + '</p>' + retryBtn('runs'));
    else if (rs.status !== 'ok' && !rs.items.length) body = H.spinner('Cargando el histórico…');
    else if (!rs.items.length) body = '<p class="empty">Todavía no hay consultas guardadas.</p>';
    else body = '<ul class="hlist" aria-label="Histórico de consultas">' + rs.items.map(function (x) {
      var rsb = RUN_STATUS[x.status] || ['history_unknown', String(x.status || 'Sin dato')], cur = r.cur.run && r.cur.run.run_id === x.run_id;
      return '<li class="hrow rrun"><div class="hrow__main"><strong>' + esc(H.fmtDateTime(x.created_at)) + '</strong><span class="muted small">' + H.plural(x.scanned || 0, 'leído', 'leídos') + ' de ' + (x.total || 0) + ' · <code>' + esc(x.run_id) + '</code></span></div>' +
        H.badge(rsb[0], rsb[1]) +
        '<div class="hrow__more"><button type="button" class="btn btn--ghost btn--sm" data-fid="run-' + esc(x.run_id) + '" data-action="recon-open" data-id="' + esc(x.run_id) + '"' + (cur ? ' aria-current="true"' : '') + '>' + (cur ? 'Volver a abrir' : 'Abrir') + '</button></div></li>';
    }).join('') + '</ul>' + pageNav('recon-runs-page', rs);
    return head + '<p class="muted small">Se conservan tras reiniciar. Abrir una consulta no vuelve a leer la biblioteca.</p>' + body + '</section>';
  }

  function scopeBanner(st) {
    if (!st.scope) return '';
    return note('alert--warn', 'status', '<p><b>Hay un lote exacto abierto en Envío</b> (' + H.plural(st.scope.keys.length, 'par', 'pares') + '). No se puede preparar otro hasta cancelarlo o terminarlo.</p>' +
      '<div class="btn-row"><button type="button" class="btn btn--sm" data-action="view" data-view="send">Ver el lote</button>' +
      '<button type="button" class="btn btn--sm btn--ghost" data-action="cancel-scope">Cancelar el lote exacto</button></div>');
  }

  function view(store) {
    var st = store.state, r = st.recon;
    return '<section aria-labelledby="h-rec"><div class="page-head"><h2 id="h-rec">Conciliación</h2>' +
      '<p class="muted">Compara lo que hay en la biblioteca con el historial de entregas. Consultar es de solo lectura: ni envía nada ni da nada por perdido; una «posible omisión» es solo un aviso para que lo revises tú.</p></div>' +
      scopeBanner(st) + formPanel(store, r) + historyPanel(r) + runPanel(store, r) + selectionBar(store, r) + pastRuns(store, r) + '</section>';
  }

  root.EmbyRecon = { attach: attach, view: view, MAX_PAIRS: MAX_PAIRS, effStatus: effStatus };
})(self);
