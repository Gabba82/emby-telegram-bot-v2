/* Vistas: funciones puras estado → cadena HTML. Todo texto que viene de la API pasa por esc().
 * Los eventos se enlazan en app.js por delegación con atributos data-action.
 */
(function (root) {
  'use strict';

  var Api = root.EmbyApi, S = root.EmbyStore;
  var LABEL = S.STATUS_LABEL;

  function esc(s) {
    return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, function (ch) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]; });
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }
  function hash(str) {
    var h = 2166136261;
    for (var i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function fmtDateTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString('es-ES', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  function fmtTime(iso) {
    var d = new Date(iso);
    return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  }
  function kindLabel(k) { return k === 'movie' ? 'Película' : k === 'series' ? 'Serie' : ''; }
  function chatKind(k) { return k === 'channel' ? 'Canal' : k === 'group' ? 'Grupo' : k === 'private' ? 'Privado' : ''; }
  function statusLabel(s) { return LABEL[s] || String(s || 'Sin dato'); }
  function normStatus(s) { return LABEL[s] ? s : 'history_unknown'; }

  var ICON_PATHS = {
    sent: '<path d="M3.5 8.6l3 3L12.5 5"/>',
    failed: '<path d="M4.2 4.2l7.6 7.6M11.8 4.2l-7.6 7.6"/>',
    pending: '<circle cx="8" cy="8" r="5.6"/><path d="M8 4.8V8l2.2 1.4"/>',
    uncertain: '<path d="M6 6.2a2.1 2.1 0 1 1 3.2 1.8c-.8.5-1.2.9-1.2 1.8"/><circle cx="8" cy="12.2" r=".7" fill="currentColor"/>',
    history_unknown: '<circle cx="8" cy="8" r="5.6" stroke-dasharray="2 2.4"/><path d="M5.6 8h4.8"/>',
    skipped: '<path d="M4 8h8"/>',
    possible_omission: '<circle cx="7" cy="7" r="3.8"/><path d="M9.9 9.9l3.3 3.3"/>'
  };
  function icon(kind) {
    return '<svg class="ico" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + (ICON_PATHS[kind] || '') + '</svg>';
  }
  function badge(kind, label) {
    return '<span class="badge s-' + kind + '">' + icon(kind) + '<span>' + esc(label) + '</span></span>';
  }
  function statusBadge(s) { s = LABEL[s] ? s : 'history_unknown'; return badge(s, LABEL[s]); }

  /** Carátula: marcador con el título debajo y, encima, la imagen de la API (si falla se retira, ver app.js). */
  function cover(it, size) {
    var id = it && it.id ? String(it.id) : '', title = it && it.title ? it.title : '';
    return '<span class="cover cover--' + size + ' ph-' + (hash(id) % 8) + '"><span class="cover__ph" aria-hidden="true">' + esc(title) + '</span>' +
      (it && it.image_url ? '<img class="cover__img" src="' + esc(it.image_url) + '" alt="" loading="lazy" decoding="async">' : '') + '</span>';
  }

  // ---------- Bloques comunes ----------

  function spinner(text) {
    return '<p class="loading" role="status"><span class="spin" aria-hidden="true"></span><span>' + esc(text) + '</span></p>';
  }
  function errorBlock(err, what, title) {
    return '<div class="alert alert--err" role="alert"><p><b>' + esc(title) + '</b> ' + esc(Api.describe(err)) + '</p>' +
      '<div class="btn-row"><button type="button" class="btn btn--sm" data-fid="retry-' + what + '" data-action="retry" data-id="' + what + '">Reintentar consulta</button></div></div>';
  }
  function pager(target, p) {
    if (p.pages <= 1 && p.total <= 0) return '';
    return '<nav class="pagination" aria-label="Paginación"><button type="button" class="btn btn--ghost btn--sm" data-fid="pg-' + target + '-prev" data-action="page" data-target="' + target + '" data-id="-1"' + (p.page <= 1 ? ' disabled' : '') + '>‹ Anterior</button>' +
      '<span class="pagination__label" role="status">Página ' + p.page + ' de ' + p.pages + ' · ' + plural(p.total, 'resultado', 'resultados') + '</span>' +
      '<button type="button" class="btn btn--ghost btn--sm" data-fid="pg-' + target + '-next" data-action="page" data-target="' + target + '" data-id="1"' + (p.page >= p.pages ? ' disabled' : '') + '>Siguiente ›</button></nav>';
  }

  // ---------- Banner de modo ----------

  function banner(store) {
    var s = store.state.session;
    if (store.state.boot !== 'ready') return null;
    if (s.mode === 'operational') {
      return { cls: 'mode-banner mode-banner--op', html: '<span class="mode-banner__tag">OPERATIVO</span><span>Modo operativo · los envíos publican mensajes reales en Telegram' + (s.sends ? '' : ' · <b>envíos deshabilitados en este servidor</b>') + '</span>' };
    }
    return { cls: 'mode-banner mode-banner--demo', html: '<span class="mode-banner__tag">DEMOSTRACIÓN</span><span>Modo demostración · datos ficticios · los envíos son sintéticos y no salen a Telegram' + (s.sends ? '' : ' · <b>envíos deshabilitados</b>') + '</span>' };
  }

  // ---------- Arranque e inicio de sesión ----------

  function boot(store) {
    var st = store.state;
    if (st.boot === 'error') {
      return '<section class="login" aria-labelledby="h-boot"><h2 id="h-boot">No se pudo abrir el panel</h2>' + errorBlock(st.bootError, 'boot', 'No hay respuesta.') + '</section>';
    }
    return '<section class="login" aria-labelledby="h-boot"><h2 id="h-boot">Panel de publicación</h2>' + spinner('Comprobando la sesión…') + '</section>';
  }

  function login(store) {
    var st = store.state;
    var demoHint = st.session.mode === 'demo'
      ? '<p class="muted small">Instancia de demostración: la contraseña de pruebas es pública, <code>emby-demo-003</code>. No es una credencial real.</p>' : '';
    return '<section class="login" aria-labelledby="h-login"><h2 id="h-login">Entrar al panel</h2>' +
      '<p class="muted">Introduce la contraseña de administración.</p>' +
      '<p id="login-notice" class="login__notice" role="status">' + esc(st.notice) + '</p>' +
      '<form id="login-form" class="login__form" method="post" action="/manager/" novalidate>' +
      '<label class="field"><span>Contraseña</span><input id="login-password" type="password" name="password" autocomplete="current-password" required></label>' +
      '<p id="login-error" class="login__error" role="alert">' + esc(st.loginError) + '</p>' +
      '<button id="login-submit" type="submit" class="btn btn--primary"' + (st.loginBusy ? ' disabled' : '') + '>' + (st.loginBusy ? 'Entrando…' : 'Entrar') + '</button>' +
      '</form>' + demoHint + '</section>';
  }

  // ---------- Biblioteca ----------

  function pips(item, chats) {
    return '<ul class="pips" aria-label="Estado por chat">' + chats.map(function (c) {
      var st = normStatus(item.states && item.states[c.id]), txt = c.label + ': ' + statusLabel(st);
      return '<li class="pip s-' + st + '" title="' + esc(txt) + '">' + icon(st) + '<span class="sr-only">' + esc(txt) + '</span></li>';
    }).join('') + '</ul>';
  }

  function card(item, store) {
    var st = store.state, sel = st.selected.indexOf(item.id) >= 0, f = st.library.f;
    var refBadge = f.chat ? '<span class="card__ref">' + statusBadge(normStatus(item.states && item.states[f.chat])) + '</span>' : '';
    var full = (!sel && st.selected.length >= store.MAX_ITEMS) || !!st.scope;
    return '<li class="card' + (sel ? ' is-selected' : '') + '">' +
      '<label class="card__pick">' +
      '<input type="checkbox" class="card__check" data-fid="item-' + esc(item.id) + '" data-action="toggle-item" data-id="' + esc(item.id) + '"' + (sel ? ' checked' : '') + (full ? ' disabled' : '') + '>' +
      '<span class="card__art">' + cover(item, 'card') + '<span class="card__kind">' + esc(kindLabel(item.kind)) + '</span>' +
      '<span class="card__tick" aria-hidden="true">' + icon('sent') + '</span></span>' +
      '<span class="card__body"><span class="card__title">' + esc(item.title) + '</span>' +
      '<span class="card__meta">' + esc(item.year || '') + '</span></span></label>' +
      refBadge + pips(item, st.chats.list) + '</li>';
  }

  function legend() {
    return '<ul class="legend" aria-label="Leyenda de estados">' + S.STATUSES.map(function (s) {
      return '<li>' + statusBadge(s) + '<span class="legend__help">' + esc(S.STATUS_HELP[s]) + '</span></li>';
    }).join('') + '</ul>';
  }

  function chatOptions(store, current, allLabel) {
    return '<option value="">' + esc(allLabel) + '</option>' + store.state.chats.list.map(function (c) {
      return '<option value="' + esc(c.id) + '"' + (current === c.id ? ' selected' : '') + '>' + esc(store.chatOptionLabel(c.id)) + '</option>';
    }).join('');
  }
  function statusOptions(current, allLabel) {
    return '<option value="">' + esc(allLabel) + '</option>' + S.STATUSES.map(function (s) {
      return '<option value="' + s + '"' + (current === s ? ' selected' : '') + '>' + esc(LABEL[s]) + '</option>';
    }).join('');
  }

  /** Aviso cuando hay un lote exacto de conciliación: la selección manual queda bloqueada hasta cancelarlo. */
  function scopeNotice(st) {
    if (!st.scope) return '';
    return '<div class="alert alert--warn" role="status"><p><b>Hay un lote exacto de conciliación en curso</b> (' + plural(st.scope.keys.length, 'par', 'pares') + '). La selección manual está bloqueada para no ampliar esos pares.</p>' +
      '<div class="btn-row"><button type="button" class="btn btn--sm" data-action="view" data-view="send">Ver el lote</button>' +
      '<button type="button" class="btn btn--sm btn--ghost" data-action="cancel-scope">Cancelar el lote exacto</button></div></div>';
  }

  function library(store) {
    var st = store.state, L = st.library, f = L.f;
    var kinds = [['all', 'Todo'], ['movie', 'Películas'], ['series', 'Series']];
    var body;
    if (L.status === 'error' && !L.items.length) body = errorBlock(L.error, 'library', 'No se pudo cargar la biblioteca.');
    else if (L.status === 'loading' && !L.items.length) body = spinner('Cargando la biblioteca…');
    else {
      body = (L.status === 'error' ? errorBlock(L.error, 'library', 'No se pudo actualizar la biblioteca.') : '') +
        (L.items.length
          ? '<ul class="grid' + (L.status === 'loading' ? ' is-busy' : '') + '" aria-label="Títulos de la biblioteca" aria-busy="' + (L.status === 'loading') + '">' + L.items.map(function (i) { return card(i, store); }).join('') + '</ul>'
          : '<p class="empty">Ningún título coincide con los filtros.</p>') + pager('library', L);
    }
    var chatsNote = st.chats.status === 'error' ? errorBlock(st.chats.error, 'chats', 'No se pudieron cargar los chats.') : '';
    var order = st.chats.list.length ? '<p class="muted small">Los puntos de cada carátula siguen este orden de chats: ' + st.chats.list.map(function (c, i) { return (i + 1) + '. ' + esc(c.label); }).join(' · ') + '.</p>' : '';
    return '<section aria-labelledby="h-lib">' +
      '<div class="page-head"><h2 id="h-lib">Biblioteca</h2><p class="muted">Marca los títulos que quieras enviar como lote (máximo ' + store.MAX_ITEMS + ').</p></div>' +
      chatsNote + scopeNotice(st) +
      '<div class="toolbar">' +
      '<label class="field field--grow"><span>Buscar</span><input type="search" data-fid="q" data-action="filter-q" value="' + esc(f.query) + '" placeholder="Título" autocomplete="off"></label>' +
      '<fieldset class="seg"><legend>Tipo</legend>' + kinds.map(function (k) {
        return '<label><input type="radio" name="kind" data-action="filter-kind" value="' + k[0] + '"' + (f.kind === k[0] ? ' checked' : '') + '><span>' + k[1] + '</span></label>';
      }).join('') + '</fieldset>' +
      '<label class="field"><span>Chat</span><select data-fid="f-chat" data-action="filter-chat">' + chatOptions(store, f.chat, 'Todos (ver puntos)') + '</select></label>' +
      '<label class="field"><span>' + (f.chat ? 'Estado en el chat' : 'Estado en algún chat') + '</span><select data-fid="f-status" data-action="filter-status">' + statusOptions(f.status, 'Cualquiera') + '</select></label>' +
      '</div>' +
      '<div class="toolbar toolbar--actions">' +
      '<p class="muted" role="status">' + (L.status === 'ok' ? plural(L.total, 'título', 'títulos') + ' · ' : '') + plural(st.selected.length, 'seleccionado', 'seleccionados') + '</p>' +
      '<div class="btn-row"><button type="button" class="btn" data-action="select-visible"' + (L.items.length && !st.scope ? '' : ' disabled') + '>Seleccionar esta página</button>' +
      '<button type="button" class="btn btn--ghost" data-action="clear-items"' + (st.selected.length && !st.scope ? '' : ' disabled') + '>Vaciar selección</button></div></div>' +
      order + body +
      '<details class="legend-box"><summary>Qué significa cada estado</summary>' + legend() + '</details></section>';
  }

  // ---------- Historial ----------

  function attempts(d) {
    if (!d) return '';
    if (d.status === 'loading') return spinner('Cargando intentos…');
    if (d.status === 'error') return '<div class="alert alert--err" role="alert"><p>' + esc(Api.describe(d.error)) + '</p></div>';
    var list = d.data.attempts;
    if (!list.length) return '<p class="muted small">Sin intentos registrados.</p>';
    return '<ol class="attempts">' + list.map(function (a) {
      return '<li><div class="attempts__head">' + statusBadge(a.status) + '<span class="small muted">' + esc(fmtDateTime(a.finished_at || a.created_at)) + '</span></div>' +
        '<p class="small">' + (a.message_id ? 'Mensaje ' + esc(a.message_id) + '. ' : '') + (a.error_type ? 'Error: ' + esc(a.error_type) + '. ' : '') + (a.explicit_uncertain ? 'Marcado incierto de forma explícita.' : '') + '</p>' +
        (a.caption ? '<pre class="caption">' + esc(a.caption) + '</pre>' : '') + '</li>';
    }).join('') + '</ol>';
  }

  function historyView(store) {
    var st = store.state, H = st.history, f = H.f;
    var body;
    if (H.status === 'error' && !H.items.length) body = errorBlock(H.error, 'history', 'No se pudo cargar el historial.');
    else if (H.status === 'loading' && !H.items.length) body = spinner('Cargando el historial…');
    else if (H.status === 'idle') body = '';
    else {
      var rows = H.items.map(function (r) {
        var item = st.known[r.item_id] || { id: r.item_id, title: r.title }, open = !!H.open[r.id];
        var meta = [fmtDateTime(r.updated_at || r.created_at), r.attempt_count ? plural(r.attempt_count, 'intento', 'intentos') : '', r.source ? 'origen: ' + r.source : '', r.actor ? 'por ' + r.actor : ''].filter(Boolean).join(' · ');
        return '<li class="hrow">' + cover(item, 'xs') +
          '<div class="hrow__main"><strong>' + esc(r.title) + '</strong><span class="muted small">' + esc(r.chat_label) + '</span>' +
          '<span class="small">' + esc(meta) + (r.error_type ? ' · error: ' + esc(r.error_type) : '') + (r.message_id ? ' · mensaje ' + esc(r.message_id) : '') + '</span></div>' +
          statusBadge(r.status) +
          '<div class="hrow__more"><button type="button" class="btn btn--ghost btn--sm" data-fid="det-' + esc(r.id) + '" data-action="toggle-detail" data-id="' + esc(r.id) + '" aria-expanded="' + open + '">' + (open ? 'Ocultar intentos' : 'Ver intentos') + '</button>' +
          (open ? '<div class="hrow__detail">' + attempts(H.detail[r.id]) + '</div>' : '') + '</div></li>';
      }).join('');
      body = (H.status === 'error' ? errorBlock(H.error, 'history', 'No se pudo actualizar el historial.') : '') +
        (H.items.length ? '<ul class="hlist' + (H.status === 'loading' ? ' is-busy' : '') + '" aria-label="Entregas registradas" aria-busy="' + (H.status === 'loading') + '">' + rows + '</ul>' : '<p class="empty">No hay entregas registradas con esos filtros.</p>') + pager('history', H);
    }
    return '<section aria-labelledby="h-hist">' +
      '<div class="page-head"><h2 id="h-hist">Historial de entregas</h2><p class="muted">Qué se envió, qué falló y qué quedó sin confirmar, chat por chat.</p></div>' +
      '<div class="toolbar">' +
      '<label class="field"><span>Chat</span><select data-fid="h-chat" data-action="hist-chat">' + chatOptions(store, f.chat, 'Todos los chats') + '</select></label>' +
      '<label class="field"><span>Estado</span><select data-fid="h-status" data-action="hist-status">' + statusOptions(f.status, 'Todos').replace(/<option value="history_unknown"[^>]*>[^<]*<\/option>/, '') + '</select></label>' +
      '<button type="button" class="btn btn--primary" data-fid="recover" data-action="prepare-recovery"' + (f.chat && !st.recovering && !st.scope ? '' : ' disabled') + '>' + (st.recovering ? 'Buscando…' : 'Preparar recuperación del chat') + '</button></div>' + scopeNotice(st) +
      '<p class="muted small">' + (f.chat ? 'Reúne los títulos de este chat con envíos fallidos, pendientes, inciertos o sin historial (máximo ' + store.MAX_ITEMS + '). Lo ya enviado nunca se incluye.' : 'Elige un chat para preparar su recuperación.') + '</p>' +
      (H.recoverMsg ? '<p class="alert alert--warn" role="status">' + esc(H.recoverMsg) + '</p>' : '') + body + '</section>';
  }

  // ---------- Envío ----------

  function selectionPanel(store) {
    var items = store.selectedItems(), sc = store.state.scope;
    if (sc) {
      return '<section class="panel" aria-labelledby="h-sel"><h3 id="h-sel"><span class="step">1</span> Lote exacto de conciliación</h3>' +
        '<p class="small">' + plural(sc.keys.length, 'par título × destino', 'pares título × destino') + ' elegidos en Conciliación (' + plural(items.length, 'título', 'títulos') + '). ' +
        'Solo se prepara, y solo se enviaría tras confirmar, exactamente esta lista: no se añade ningún otro destino ni título.</p>' +
        '<ul class="selchips">' + items.map(function (i) { return '<li class="selchip">' + cover(i, 'xs') + '<span>' + esc(i.title) + '</span></li>'; }).join('') + '</ul>' +
        '<div class="btn-row"><button type="button" class="btn" data-fid="back-recon" data-action="cancel-scope">Cancelar y volver a Conciliación</button></div></section>';
    }
    var chips = items.map(function (i) {
      return '<li class="selchip">' + cover(i, 'xs') + '<span>' + esc(i.title) + '</span>' +
        '<button type="button" class="iconbtn" data-fid="rm-' + esc(i.id) + '" data-action="toggle-item" data-id="' + esc(i.id) + '" data-on="false" aria-label="Quitar ' + esc(i.title) + ' del lote">' + icon('failed') + '</button></li>';
    }).join('');
    return '<section class="panel" aria-labelledby="h-sel"><h3 id="h-sel"><span class="step">1</span> Lote (' + items.length + '/' + store.MAX_ITEMS + ')</h3>' +
      (items.length ? '<ul class="selchips">' + chips + '</ul>' : '<p class="empty">No hay títulos seleccionados.</p>') +
      '<div class="btn-row"><button type="button" class="btn" data-action="view" data-view="library">' + (items.length ? 'Editar selección' : 'Ir a la biblioteca') + '</button></div></section>';
  }

  function previewPanel(store) {
    var st = store.state, items = store.selectedItems(), p = st.plan;
    var head = '<section class="panel" aria-labelledby="h-prev"><h3 id="h-prev"><span class="step">2</span> Vista previa</h3>';
    if (!items.length) return head + '<p class="empty">Selecciona algún título para ver cómo quedaría el mensaje.</p></section>';
    var idx = Math.min(st.previewIndex, items.length - 1), item = items[idx];
    var row = p.batch ? p.batch.rows.filter(function (r) { return r.item_id === item.id; })[0] : null;
    var pager_ = '<div class="pager"><button type="button" class="btn btn--ghost" data-fid="prev-prev" data-action="preview-step" data-id="-1"' + (items.length > 1 ? '' : ' disabled') + ' aria-label="Título anterior">‹</button>' +
      '<span class="pager__label" role="status">' + (idx + 1) + ' de ' + items.length + ': ' + esc(item.title) + '</span>' +
      '<button type="button" class="btn btn--ghost" data-fid="prev-next" data-action="preview-step" data-id="1"' + (items.length > 1 ? '' : ' disabled') + ' aria-label="Título siguiente">›</button></div>';
    var body;
    if (!st.selChats.length) body = '<p class="empty">Elige un destino: el texto exacto se fija al preparar el lote.</p>';
    else if (p.status === 'error' && !row) body = errorBlock(p.error, 'plan', 'No se pudo preparar el lote.');
    else if (!row) body = spinner('Preparando la vista previa…');
    else {
      body = '<div class="tg" role="group" aria-label="Vista previa del mensaje"><div class="tg__bubble"><div class="tg__cover">' + cover(item, 'lg') + '</div>' +
        '<p class="tg__caption">' + esc(row.preview).replace(/\n/g, '<br>') + '</p><span class="tg__time">vista previa · no enviado</span></div></div>' +
        '<p class="small ' + (row.caption_valid ? 'muted' : 'warn') + '">' + row.caption_length + ' caracteres' + (row.caption_valid ? ' · texto válido' : ' · el texto no es válido para Telegram: este envío no se puede confirmar') + '</p>';
    }
    return head + pager_ + body + '</section>';
  }

  function destinationsPanel(store) {
    var st = store.state, C = st.chats;
    var inner;
    if (C.status === 'error') inner = errorBlock(C.error, 'chats', 'No se pudieron cargar los chats. Se mantienen intactos los destinos configurados; vuelve a intentarlo.');
    else if (C.status !== 'ok') inner = spinner('Cargando destinos…');
    else if (!C.list.length) inner = '<p class="empty">No hay destinos configurados para el panel. Revisa <code>LIBRARY_CHAT_IDS</code> o <code>CHAT_IDS</code>.</p>';
    else {
      var rows = st.plan.batch ? st.plan.batch.rows : [];
      var locked = !!st.scope;
      var listed = locked ? C.list.filter(function (c) { return st.selChats.indexOf(c.id) >= 0; }) : C.list;
      inner = '<fieldset class="dests"><legend class="sr-only">Destinos de envío</legend><ul>' + listed.map(function (c) {
        var on = st.selChats.indexOf(c.id) >= 0, full = locked || (!on && st.selChats.length >= store.MAX_CHATS);
        var secondary = [c.telegram_name && c.telegram_name !== c.label ? c.telegram_name : '', c.id, chatKind(c.kind)].filter(Boolean).join(' · ');
        var counts = {};
        rows.forEach(function (r) { if (r.chat_id === c.id) counts[normStatus(r.state)] = (counts[normStatus(r.state)] || 0) + 1; });
        var chips = Object.keys(counts).map(function (s) {
          return '<li class="count s-' + s + '" title="' + esc(statusLabel(s)) + '">' + icon(s) + '<span aria-hidden="true">' + counts[s] + '</span><span class="sr-only">' + counts[s] + ' ' + esc(statusLabel(s)) + '</span></li>';
        }).join('');
        return '<li class="dest' + (on ? ' is-selected' : '') + '"><label class="dest__pick"><input type="checkbox" data-fid="chat-' + esc(c.id) + '" data-action="toggle-chat" data-id="' + esc(c.id) + '"' + (on ? ' checked' : '') + (full ? ' disabled' : '') + '>' +
          '<span class="dest__main"><span class="dest__name">' + esc(c.label) + '</span><span class="muted small">' + esc(secondary) + '</span></span></label>' +
          '<div class="dest__alias"><label class="field field--grow"><span>Alias opcional</span><input type="text" maxlength="80" data-chat-alias value="' + esc(c.alias || '') + '" placeholder="Usar nombre de Telegram"></label>' +
          '<button type="button" class="btn btn--ghost btn--sm" data-action="save-chat-alias" data-id="' + esc(c.id) + '">Guardar alias</button></div>' +
          (on && chips ? '<ul class="counts" aria-label="Estado actual del lote en este chat">' + chips + '</ul>' : '') + '</li>';
      }).join('') + '</ul></fieldset>' +
        (locked ? '' : '<div class="btn-row"><button type="button" class="btn btn--ghost" data-action="all-chats">Todos</button><button type="button" class="btn btn--ghost" data-action="no-chats">Ninguno</button></div>');
    }
    return '<section class="panel" aria-labelledby="h-dest"><h3 id="h-dest"><span class="step">3</span> Destinos</h3>' +
      (st.scope
        ? '<p class="muted small">Destinos del lote exacto de conciliación (solo lectura). Cada título solo va a los destinos con los que lo emparejaste. Los números son el estado actual en cada chat.</p>'
        : '<p class="muted small">Elige cada destino por separado (máximo ' + store.MAX_CHATS + '). Los números son el estado actual del lote en cada chat.</p>') + inner + '</section>';
  }

  /** Control por fila. La acción mostrada es siempre la que devuelve el servidor tras preparar. */
  function actionCell(r, mode) {
    var who = esc(r.title) + ' en ' + esc(r.chat_label), st = normStatus(r.state), key = esc(r.key);
    var dec = r.action === 'decision';
    if (st === 'uncertain' || st === 'history_unknown') {
      var cur = r.action === 'send' || r.action === 'retry' ? 'send' : r.action === 'skip' ? 'skip' : '';
      var legend = dec ? 'Decide: ' + (st === 'uncertain' ? 'puede que ya haya llegado' : 'no hay evidencia de envío') : (cur === 'send' ? 'Se enviará aunque pueda duplicarse' : 'Se omitirá');
      return '<fieldset class="choice' + (dec ? ' choice--required' : '') + '"><legend>' + esc(legend) + '<span class="sr-only">. ' + who + '</span></legend>' +
        ['send', 'skip'].map(function (v) {
          return '<label class="radio"><input type="radio" name="dec-' + key + '" data-fid="dec-' + key + '-' + v + '" data-action="decide-choice" data-key="' + key + '" value="' + v + '"' + (cur === v ? ' checked' : '') + '><span>' + (v === 'send' ? 'Enviar igualmente' : 'Omitir') + '</span></label>';
        }).join('') + '</fieldset>';
    }
    if (st === 'sent') {
      if (mode !== 'resend') return '<span class="act act--locked">' + icon('skipped') + '<span>Omitido · ya enviado, no se duplica</span></span>';
      return '<label class="check check--warn"><input type="checkbox" data-fid="act-' + key + '" data-action="decide-toggle" data-key="' + key + '"' + (r.action === 'send' ? ' checked' : '') + ' aria-label="Reenviar: ' + who + '"><span>Reenviar (duplicado voluntario)</span></label>';
    }
    var label = mode === 'resend' ? 'Enviar copia nueva' : r.action === 'retry' || st === 'failed' || st === 'pending' ? 'Reintentar envío' : 'Enviar';
    return '<label class="check"><input type="checkbox" data-fid="act-' + key + '" data-action="decide-toggle" data-key="' + key + '"' + (r.action !== 'skip' ? ' checked' : '') + ' aria-label="' + label + ': ' + who + '"><span>' + label + '</span></label>';
  }

  function planPanel(store) {
    var st = store.state, p = st.plan, b = p.batch;
    var head = '<h3 id="h-plan"><span class="step">4</span> Plan por destino</h3>';
    if (!st.selected.length || !st.selChats.length) {
      return '<section class="panel" aria-labelledby="h-plan">' + head + '<p class="empty">' + (!st.selected.length ? 'Selecciona títulos' : 'Elige al menos un destino') + ' para calcular qué se enviaría y qué se omitiría.</p></section>';
    }
    if (!b) {
      return '<section class="panel" aria-labelledby="h-plan">' + head + (p.status === 'error' ? errorBlock(p.error, 'plan', 'No se pudo preparar el lote.') : spinner('Preparando el lote…')) + '</section>';
    }
    var sum = b.summary || {}, busy = p.status === 'loading';
    var controls = st.scope ? '<div class="plan-controls"><p class="small"><b>Solo recuperación.</b> Lo ya enviado se omite y el reenvío voluntario no está disponible en un lote de conciliación. Los dudosos (inciertos, sin historial o posibles omisiones) necesitan tu decisión.</p></div>' : '<div class="plan-controls"><label class="switch"><input type="checkbox" data-fid="resend" data-action="resend"' + (st.mode === 'resend' ? ' checked' : '') + '><span class="switch__track" aria-hidden="true"></span><span><b>Reenvío voluntario</b><span class="muted small block">Por defecto lo ya enviado se omite. Actívalo solo si quieres duplicar a propósito.</span></span></label></div>';
    var stats = '<ul class="stats" aria-label="Resumen del plan"><li><b>' + (sum.send || 0) + '</b> a enviar</li><li><b>' + (sum.skip || 0) + '</b> omitidos</li>' +
      '<li class="' + (sum.decision ? 'warn' : '') + '"><b>' + (sum.decision || 0) + '</b> por decidir</li>' +
      (sum.duplicates ? '<li class="warn"><b>' + sum.duplicates + '</b> con riesgo de duplicado</li>' : '') + '</ul>';
    var pendingN = sum.decision || 0, anyDoubt = b.rows.some(function (r) { return r.state === 'uncertain' || r.state === 'history_unknown'; });
    var alert = '';
    if (anyDoubt) {
      alert += '<div class="alert ' + (pendingN ? 'alert--warn' : 'alert--ok') + '" role="group" aria-label="Decisiones sobre envíos dudosos"><p>' + (pendingN
        ? '<b>' + plural(pendingN, 'envío dudoso necesita', 'envíos dudosos necesitan') + ' tu decisión.</b> Los estados incierto y desconocido nunca se resuelven solos.'
        : 'Todas las decisiones sobre envíos dudosos están tomadas.') + '</p>' +
        '<div class="btn-row"><button type="button" class="btn btn--sm" data-action="decide-all" data-value="skip">Omitir todos los dudosos</button>' +
        '<button type="button" class="btn btn--sm" data-action="decide-all" data-value="send">Enviar todos los dudosos</button>' +
        '<button type="button" class="btn btn--sm btn--ghost" data-action="clear-decisions">Borrar decisiones</button></div></div>';
    }
    if (st.mode === 'resend') alert += '<div class="alert alert--info"><p>Reenvío voluntario activo: marca uno a uno lo ya enviado que quieras duplicar. Se pedirá confirmación expresa.</p></div>';
    var chatIds = st.selChats.filter(function (id) { return b.rows.some(function (r) { return r.chat_id === id; }); });
    var groups = chatIds.map(function (cid) {
      var rows = b.rows.filter(function (r) { return r.chat_id === cid; });
      var send = rows.filter(function (r) { return r.action === 'send' || r.action === 'retry'; }).length;
      var dec = rows.filter(function (r) { return r.action === 'decision'; }).length;
      var skip = rows.length - send - dec;
      var body = rows.map(function (r) {
        var item = st.known[r.item_id] || { id: r.item_id, title: r.title };
        var eff = r.action === 'decision' ? 'blocked' : r.action === 'skip' ? 'skip' : 'send';
        return '<li class="prow prow--' + eff + '">' + cover(item, 'xs') + '<div class="prow__main"><strong>' + esc(r.title) + '</strong><span class="prow__state">' + statusBadge(r.state) +
          (r.duplicate_risk && eff === 'send' ? '<span class="risk">Posible duplicado</span>' : '') +
          (r.caption_valid ? '' : '<span class="risk risk--bad">Texto no válido (' + esc(r.caption_length) + ' caracteres)</span>') + '</span></div>' +
          '<div class="prow__act">' + actionCell(r, st.mode) + '</div></li>';
      }).join('');
      var open = st.openGroups ? st.openGroups[cid] !== false : true;
      return '<details class="group" data-action="group-toggle" data-id="' + esc(cid) + '"' + (open ? ' open' : '') + '><summary data-fid="grp-' + esc(cid) + '"><span class="group__name">' + esc(store.chatLabel(cid)) + '</span>' +
        '<span class="group__stats">' + send + ' a enviar · ' + skip + ' omitidos' + (dec ? ' · <span class="warn">' + dec + ' por decidir</span>' : '') + '</span></summary><ul class="plist">' + body + '</ul></details>';
    }).join('');
    var errNote = p.status === 'error' ? errorBlock(p.error, 'plan', 'No se pudo actualizar el plan; lo que ves puede estar desfasado.') : '';
    var exp = b.expires_at ? '<p class="muted small">Lote ' + esc(b.batch_id) + ' preparado, sin enviar · válido hasta las ' + esc(fmtTime(b.expires_at)) + '.</p>' : '';
    return '<section class="panel' + (busy ? ' is-busy' : '') + '" aria-labelledby="h-plan" aria-busy="' + busy + '">' + head + (busy ? spinner('Actualizando el plan…') : '') + controls + stats + exp + errNote + alert + groups + '</section>';
  }

  function actionBar(store) {
    var st = store.state, p = st.plan, b = p.batch, sum = b ? b.summary || {} : {};
    var ready = store.canConfirm();
    var why = '';
    if (!st.selected.length) why = 'Selecciona títulos.';
    else if (!st.selChats.length) why = 'Elige destinos.';
    else if (p.status === 'loading' || !b) why = p.status === 'error' ? 'No se pudo preparar el lote.' : 'Preparando el lote…';
    else if (p.status === 'error') why = 'El plan no está actualizado.';
    else if (!st.session.sends) why = 'Los envíos están deshabilitados en este servidor.';
    else if (sum.decision) why = 'Faltan ' + plural(sum.decision, 'decisión', 'decisiones') + '.';
    else if (b.rows.some(function (r) { return !r.caption_valid && (r.action === 'send' || r.action === 'retry'); })) why = 'Hay textos no válidos.';
    else if (!b.can_confirm) why = (sum.send ? '' : 'No hay nada que enviar: todo se omite.');
    var verb = st.session.mode === 'operational' ? 'a Telegram' : 'de demostración';
    return '<div class="actionbar" role="region" aria-label="Resumen del envío"><p class="actionbar__text"><b>' + plural(sum.send || 0, 'envío', 'envíos') + '</b> ' + verb + ' · ' + (sum.skip || 0) + ' omitidos' +
      (why ? ' · <span class="warn" id="why">' + esc(why) + '</span>' : '') + '</p>' +
      '<button type="button" class="btn btn--primary" data-fid="open-confirm" data-action="open-confirm"' + (ready ? '' : ' aria-disabled="true" aria-describedby="why"') + '>Revisar y confirmar</button></div>';
  }

  // ---------- Resultados ----------

  /** Filas de resultado agrupadas por chat (finales o parciales). */
  function resultGroups(st, results) {
    var chatIds = [];
    results.forEach(function (r) { if (chatIds.indexOf(r.chat_id) < 0) chatIds.push(r.chat_id); });
    return chatIds.map(function (cid) {
      var rows = results.filter(function (r) { return r.chat_id === cid; });
      var c = { sent: 0, failed: 0, pending: 0, uncertain: 0, skipped: 0 };
      rows.forEach(function (r) { if (c[r.status] !== undefined) c[r.status]++; });
      var list = rows.map(function (r) {
        var item = st.known[r.item_id] || { id: r.item_id, title: r.title };
        var note = [r.error_type ? 'Error: ' + r.error_type : '', r.message_id ? 'Mensaje ' + r.message_id : ''].filter(Boolean).join(' · ');
        return '<li class="prow prow--' + esc(r.status) + '">' + cover(item, 'xs') + '<div class="prow__main"><strong>' + esc(r.title) + '</strong>' + (note ? '<span class="muted small">' + esc(note) + '</span>' : '') + '</div><div class="prow__act">' + statusBadge(r.status) + '</div></li>';
      }).join('');
      return '<details class="group" open><summary data-fid="rgrp-' + esc(cid) + '"><span class="group__name">' + esc(rows[0].chat_label) + '</span><span class="group__stats">' +
        plural(c.sent, 'enviado', 'enviados') + ' · ' + plural(c.failed, 'fallido', 'fallidos') + ' · ' + plural(c.pending, 'pendiente', 'pendientes') + ' · ' + plural(c.uncertain, 'incierto', 'inciertos') + ' · ' + plural(c.skipped, 'omitido', 'omitidos') + '</span></summary><ul class="plist">' + list + '</ul></details>';
    }).join('');
  }

  function resultsView(store) {
    var st = store.state, res = st.result, demo = st.session.mode !== 'operational';
    if (res.unknown) {
      var body;
      if (res.checking) body = spinner('Consultando el estado del lote ' + res.batchId + '…');
      else if (res.inProgress) body = '<div class="alert alert--warn" role="status"><p><b>El lote sigue en curso en el servidor.</b> Todavía no hay resultado final (estado: <code>' + esc(res.status) + '</code>); lo que ves abajo es parcial y puede cambiar. No lances un lote nuevo hasta que termine.</p>' +
        '<div class="btn-row"><button type="button" class="btn btn--primary" data-fid="check-batch" data-action="check-batch">Consultar de nuevo</button><button type="button" class="btn" data-action="result-history">Ver historial</button></div></div>' +
        (res.partial && res.partial.length ? resultGroups(st, res.partial) : '');
      else if (res.notExecuted) body = '<div class="alert alert--info" role="status"><p><b>El lote no llegó a ejecutarse: no se envió nada.</b> Puedes volver al plan y confirmarlo de nuevo; es el mismo lote y no se duplicará.</p></div>' +
        '<div class="btn-row"><button type="button" class="btn btn--primary" data-fid="res-back" data-action="back-compose">Volver al plan</button></div>';
      else body = '<div class="alert alert--err" role="alert"><p><b>No sabemos si se envió.</b> ' + esc(Api.describe(res.error)) + ' El lote <code>' + esc(res.batchId) + '</code> puede haberse ejecutado entera, en parte o nada. No se ha creado ningún lote nuevo ni se ha vuelto a enviar.' +
        (res.checkError ? ' Tampoco se pudo consultar su estado: ' + esc(Api.describe(res.checkError)) : '') + '</p>' +
        '<div class="btn-row"><button type="button" class="btn btn--primary" data-fid="check-batch" data-action="check-batch">Reintentar consulta del lote</button>' +
        '<button type="button" class="btn" data-action="result-history">Ver historial</button></div></div>';
      return '<section class="panel results" aria-labelledby="h-res"><h3 id="h-res">' + (res.inProgress ? 'Lote en curso' : 'Resultado sin confirmar') + '</h3>' + body + '</section>';
    }
    var sum = res.summary || {};
    var groups = resultGroups(st, res.results);
    var redo = (sum.failed || 0) + (sum.pending || 0) + (sum.uncertain || 0);
    return '<section class="panel results" aria-labelledby="h-res"><h3 id="h-res">Resultado por destino</h3>' +
      (res.status === 'interrupted' ? '<div class="alert alert--err" role="alert"><p><b>Ejecución interrumpida.</b> Algunos envíos pueden no haberse intentado y el lote no se reanuda solo. Revisa cada fila antes de volver a enviar.</p></div>' : '') +
      '<p class="demo-note">' + (demo ? '<b>Demostración.</b> Mensajes sintéticos guardados en la base de datos de la demo; nada salió a Telegram.' : '<b>Operativo.</b> Estos son los resultados que devolvió el servidor para el lote.') + ' Lote <code>' + esc(res.batchId) + '</code>, ' + esc(fmtDateTime(res.at)) + '.</p>' +
      '<ul class="stats stats--big" aria-label="Resumen del resultado">' +
      ['sent', 'failed', 'pending', 'uncertain', 'skipped'].map(function (k) {
        var lbl = { sent: 'enviados', failed: 'fallidos', pending: 'pendientes', uncertain: 'inciertos', skipped: 'omitidos' }[k];
        return '<li class="s-' + k + '">' + icon(k) + '<b>' + (sum[k] || 0) + '</b> ' + lbl + '</li>';
      }).join('') + '</ul>' + groups +
      '<div class="btn-row">' + (redo ? '<button type="button" class="btn btn--primary" data-fid="res-recover" data-action="recover-result">Recuperar fallidos, pendientes e inciertos</button>' : '') +
      '<button type="button" class="btn" data-action="result-history">Ver historial</button>' +
      '<button type="button" class="btn btn--ghost" data-fid="res-new" data-action="new-batch">Nuevo lote</button></div>' +
      (redo ? '<p class="muted small">Recuperar prepara un lote nuevo: los enviados se omiten solos y los inciertos vuelven a pedirte decisión.</p>' : '') + '</section>';
  }

  function send(store) {
    var st = store.state;
    var inner = st.phase === 'results' && st.result ? resultsView(store)
      : '<div class="send-grid"><div class="send-col">' + selectionPanel(store) + previewPanel(store) + '</div><div class="send-col">' + destinationsPanel(store) + planPanel(store) + '</div></div>' + actionBar(store);
    return '<section aria-labelledby="h-send"><div class="page-head"><h2 id="h-send">Preparar envío</h2><p class="muted">Recuperar no duplica lo ya enviado; reenviar es siempre voluntario y se confirma.</p></div>' + inner + '</section>';
  }

  // ---------- Bandeja y diálogo ----------

  function tray(store) {
    var st = store.state;
    if (!st.session.authenticated || st.view === 'send' || st.view === 'reconciliation') return '';
    if (st.scope) {
      return '<div class="tray" role="region" aria-label="Lote exacto de conciliación"><p><b>Lote exacto de conciliación</b> · ' + plural(st.scope.keys.length, 'par', 'pares') + '</p>' +
        '<button type="button" class="btn btn--primary" data-action="view" data-view="send">Ver el lote</button></div>';
    }
    return '<div class="tray" role="region" aria-label="Lote seleccionado"><p><b>' + plural(st.selected.length, 'título', 'títulos') + '</b> · ' + plural(st.selChats.length, 'destino', 'destinos') + '</p>' +
      '<button type="button" class="btn btn--primary" data-action="view" data-view="send">Preparar envío</button></div>';
  }

  function confirmBody(store) {
    var st = store.state, c = st.confirm, b = st.plan.batch;
    if (!b) return '<h2 id="confirm-title">Confirmar envío</h2><p>No hay lote preparado.</p>';
    var demo = st.session.mode !== 'operational', sum = b.summary || {};
    var act = b.rows.filter(function (r) { return r.action === 'send' || r.action === 'retry'; });
    var perChat = st.selChats.map(function (cid) {
      var n = act.filter(function (r) { return r.chat_id === cid; }).length;
      return '<li><b>' + esc(store.chatLabel(cid)) + '</b>: ' + plural(n, 'envío', 'envíos') + '</li>';
    }).join('');
    var risky = act.filter(function (r) { return r.duplicate_risk; }).length;
    var dup = risky
      ? '<div class="alert alert--warn"><p><b>Riesgo de duplicado:</b> ' + plural(risky, 'mensaje', 'mensajes') + ' pueden ya estar en el chat (ya enviados, inciertos o sin historial). Los destinatarios podrían ver duplicados.</p>' +
        '<label class="check"><input type="checkbox" data-fid="ack-dup" data-action="ack-dup"' + (c.ack ? ' checked' : '') + (c.busy ? ' disabled' : '') + '><span>Entiendo el riesgo y quiero enviarlos igualmente</span></label></div>' : '';
    var ok = !risky || c.ack;
    var err = '';
    if (c.error) {
      err = '<div class="alert alert--err" role="alert"><p><b>No se envió nada.</b> ' + esc(Api.describe(c.error)) + '</p>' +
        (c.error.kind === 'conflict' || c.error.kind === 'request' ? '<div class="btn-row"><button type="button" class="btn btn--sm" data-action="reprepare">Volver a preparar el lote</button></div>' : '') + '</div>';
    }
    return '<h2 id="confirm-title">Confirmar envío' + (demo ? ' de demostración' : '') + '</h2>' +
      '<p class="demo-note">' + (demo ? '<b>Demostración.</b> Se guardarán mensajes sintéticos; no sale nada a Telegram.' : '<b>Operativo.</b> Se publicarán mensajes reales en Telegram.') + '</p>' +
      '<p>Se enviarán <b>' + plural(sum.send || 0, 'mensaje', 'mensajes') + '</b> en ' + plural(st.selChats.length, 'destino', 'destinos') + ' (' + (sum.skip || 0) + ' omitidos, incluidos los éxitos ya conocidos).</p>' +
      '<ul class="confirm-list">' + perChat + '</ul>' + dup + err +
      (c.busy ? spinner('Enviando… no cierres ni recargues esta página.') : '') +
      '<div class="dialog__actions"><button type="button" class="btn" data-fid="cancel-confirm" data-action="cancel-confirm"' + (c.busy ? ' disabled' : '') + '>Cancelar</button>' +
      '<button type="button" class="btn btn--primary" data-fid="confirm-send" data-action="confirm-send"' + (c.busy ? ' disabled' : ok ? '' : ' aria-disabled="true"') + '>' + (demo ? 'Enviar (demostración)' : 'Enviar a Telegram') + '</button></div>';
  }

  function main(store) {
    var st = store.state;
    if (st.boot !== 'ready') return boot(store);
    if (!st.session.authenticated) return login(store);
    if (st.view === 'reconciliation' && root.EmbyRecon) return root.EmbyRecon.view(store);
    if (st.view === 'individual' && root.EmbyIndividual) return root.EmbyIndividual.view(store);
    return st.view === 'history' ? historyView(store) : st.view === 'send' ? send(store) : library(store);
  }

  root.EmbyViews = {
    esc: esc, main: main, tray: tray, confirmBody: confirmBody, banner: banner,
    // piezas comunes para módulos de vista (reconciliation.js)
    h: { plural: plural, fmtDateTime: fmtDateTime, icon: icon, badge: badge, statusBadge: statusBadge, spinner: spinner, errorBlock: errorBlock, chatKind: chatKind }
  };
})(self);
