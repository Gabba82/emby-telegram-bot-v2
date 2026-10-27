/* Enlace con el DOM: render, foco, diálogo y eventos por delegación. Sin lógica de negocio. */
(function () {
  'use strict';

  var store = EmbyStore.createStore();
  EmbyRecon.attach(store);
  EmbyIndividual.attach(store);
  var V = EmbyViews;
  var $view = document.getElementById('view');
  var $tray = document.getElementById('tray');
  var $dialog = document.getElementById('confirm-dialog');
  var $dialogBody = document.getElementById('dialog-body');
  var $live = document.getElementById('live');
  var $nav = document.getElementById('nav');
  var $logout = document.getElementById('logout');
  var $banner = document.getElementById('mode-banner');
  var lastKey = null;

  /** Sustituye el HTML de un contenedor conservando el foco (y el cursor en campos de texto). */
  function patch(el, html) {
    var active = document.activeElement, fid = null, selStart = null, selEnd = null;
    if (active && el.contains(active) && active.getAttribute) {
      fid = active.getAttribute('data-fid');
      try { selStart = active.selectionStart; selEnd = active.selectionEnd; } catch (e) { /* no aplica */ }
    }
    el.innerHTML = html;
    if (fid) {
      var next = el.querySelector('[data-fid="' + fid.replace(/"/g, '\\"') + '"]');
      if (next) {
        next.focus({ preventScroll: true });
        if (selStart !== null && next.setSelectionRange) { try { next.setSelectionRange(selStart, selEnd); } catch (e) { /* no aplica */ } }
      }
    }
  }

  function renderLogin(state) {
    // El formulario no se vuelve a pintar mientras se escribe: así no se pierde lo tecleado ni el foco.
    var form = document.getElementById('login-form');
    if (!form) { patch($view, V.main(store)); return; }
    document.getElementById('login-error').textContent = state.loginError;
    document.getElementById('login-notice').textContent = state.notice;
    var btn = document.getElementById('login-submit');
    btn.disabled = state.loginBusy;
    btn.textContent = state.loginBusy ? 'Entrando…' : 'Entrar';
  }

  function render(state) {
    var authed = state.boot === 'ready' && state.session.authenticated;
    var b = V.banner(store);
    if (b) { $banner.hidden = false; $banner.className = b.cls; $banner.innerHTML = b.html; } else $banner.hidden = true;
    $nav.hidden = !authed; $logout.hidden = !authed;

    var key = state.boot !== 'ready' ? 'boot-' + state.boot : authed ? 'app' : 'login-' + state.session.mode;
    if (authed || state.boot !== 'ready') patch($view, V.main(store));
    else if (lastKey !== key) patch($view, V.main(store));
    else renderLogin(state);

    patch($tray, V.tray(store));
    Array.prototype.forEach.call($nav.querySelectorAll('button'), function (btn) {
      if (btn.getAttribute('data-view') === state.view) btn.setAttribute('aria-current', 'page'); else btn.removeAttribute('aria-current');
    });

    if (authed && state.confirm.open) {
      patch($dialogBody, V.confirmBody(store));
      if (!$dialog.open) {
        if ($dialog.showModal) $dialog.showModal(); else $dialog.setAttribute('open', '');
        var first = $dialogBody.querySelector('[data-fid="cancel-confirm"]');
        if (first) first.focus();
      }
    } else if ($dialog.open) {
      $dialog.close();
    }
    if (state.announce) { $live.textContent = state.announce; state.announce = ''; }

    // al cambiar de pantalla, arriba y foco en el encabezado
    var screen = key + '|' + state.view + '|' + state.phase;
    if (lastKey !== null && lastScreen !== screen) {
      window.scrollTo(0, 0);
      var h = $view.querySelector('h2');
      if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
    }
    lastKey = key; lastScreen = screen;
  }
  var lastScreen = null;

  store.subscribe(render);

  // ----- Eventos (delegación) -----

  function act(el) { return el.closest ? el.closest('[data-action]') : null; }

  document.addEventListener('click', function (ev) {
    var el = act(ev.target);
    if (!el || el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'DETAILS') return;
    var a = el.getAttribute('data-action'), id = el.getAttribute('data-id');
    switch (a) {
      case 'view': store.setView(el.getAttribute('data-view')); break;
      case 'logout': store.logout(); break;
      case 'retry': store.retry(id); break;
      case 'page': store.setPage(el.getAttribute('data-target'), parseInt(id, 10)); break;
      case 'select-visible': store.selectVisible(); break;
      case 'clear-items': store.clearItems(); break;
      case 'toggle-item': store.toggleItem(id, el.getAttribute('data-on') === 'true'); break;
      case 'all-chats': store.setAllChats(true); break;
      case 'no-chats': store.setAllChats(false); break;
      case 'save-chat-alias':
        var aliasInput = el.closest('.dest').querySelector('[data-chat-alias]');
        store.saveChatAlias(id, aliasInput ? aliasInput.value : '');
        break;
      case 'toggle-detail': store.toggleDetail(id); break;
      case 'prepare-recovery': store.prepareRecovery(store.state.history.f.chat); break;
      case 'preview-step': store.setPreviewIndex(store.state.previewIndex + parseInt(id, 10)); break;
      case 'decide-all': store.decideAllPending(el.getAttribute('data-value')); break;
      case 'clear-decisions': store.clearDecisions(); break;
      case 'open-confirm':
        if (el.getAttribute('aria-disabled') === 'true') {
          $live.textContent = 'No se puede confirmar todavía: ' + (document.getElementById('why') ? document.getElementById('why').textContent : 'revisa el plan.');
        } else store.openConfirm();
        break;
      case 'cancel-confirm': store.closeConfirm(); break;
      case 'confirm-send':
        if (el.getAttribute('aria-disabled') === 'true') $live.textContent = 'Marca la casilla de aceptación del riesgo de duplicados para continuar.';
        else store.confirmSend();
        break;
      case 'reprepare': store.closeConfirm(); store.retry('plan'); break;
      case 'check-batch': store.checkBatch(); break;
      case 'back-compose': store.backToCompose(); break;
      case 'recover-result': store.recoverFromResult(); break;
      case 'result-history': store.viewHistoryAfterResult(); break;
      case 'new-batch': store.newBatch(); break;
      // Recuperación individual
      case 'individual-prepare': store.individual.prepare(); break;
      case 'individual-decision': store.individual.decide(el.getAttribute('data-value')); break;
      case 'individual-confirm': store.individual.confirm(); break;
      case 'individual-check': store.individual.check(); break;
      case 'individual-reset': store.individual.reset(); break;
      // Conciliación
      case 'cancel-scope': store.cancelScope(); break;
      case 'recon-retry': store.recon.retry(id); break;
      case 'recon-open': store.recon.openRun(id); break;
      case 'recon-tile': store.recon.setFilter('status', store.state.recon.cur.f.status === id ? '' : id); break;
      case 'recon-page': store.recon.setPage(parseInt(id, 10)); break;
      case 'recon-runs-page': store.recon.setRunsPage(parseInt(id, 10)); break;
      case 'recon-detail': store.recon.toggleDetail(id); break;
      case 'recon-remove': store.recon.toggleRow(id, false); break;
      case 'recon-select-page': store.recon.selectPage(); break;
      case 'recon-clear': store.recon.clearSelection(); break;
      case 'recon-hf-clear': store.recon.saveHistory(true); break;
      case 'recon-new':
        var first = document.querySelector('[data-fid="rf-first"]') || document.querySelector('[data-fid="rf-submit"]');
        if (first) { first.scrollIntoView({ block: 'center' }); first.focus(); }
        break;
      case 'recon-prepare':
        if (el.getAttribute('aria-disabled') === 'true') {
          $live.textContent = 'No se puede preparar todavía: ' + (document.getElementById('recon-why') ? document.getElementById('recon-why').textContent : 'revisa la selección.');
        } else store.recon.prepare();
        break;
    }
  });

  document.addEventListener('change', function (ev) {
    var el = act(ev.target);
    if (!el) return;
    var a = el.getAttribute('data-action'), id = el.getAttribute('data-id'), key = el.getAttribute('data-key');
    switch (a) {
      case 'toggle-item': store.toggleItem(id, el.checked); break;
      case 'toggle-chat': store.toggleChat(id, el.checked); break;
      case 'filter-kind': store.setLibraryFilter('kind', el.value); break;
      case 'filter-chat': store.setLibraryFilter('chat', el.value); break;
      case 'filter-status': store.setLibraryFilter('status', el.value); break;
      case 'hist-chat': store.setHistoryFilter('chat', el.value); break;
      case 'hist-status': store.setHistoryFilter('status', el.value); break;
      case 'resend': store.setMode(el.checked ? 'resend' : 'recover'); break;
      case 'decide-toggle': store.setDecision(key, el.checked ? 'send' : 'skip'); break;
      case 'decide-choice': store.setDecision(key, el.value); break;
      case 'ack-dup': store.setAck(el.checked); break;
      // Conciliación
      case 'recon-field':
        if (el.type === 'checkbox') store.recon.setField(el.getAttribute('data-field'), el.getAttribute('data-value'), el.checked);
        else store.recon.setField(el.getAttribute('data-field'), el.value);
        break;
      case 'recon-hf-date': store.recon.setHistoryValue(el.value); break;
      case 'recon-hf-ack': store.recon.setHistoryAck(el.checked); break;
      case 'recon-status': store.recon.setFilter('status', el.value); break;
      case 'recon-chat': store.recon.setFilter('chat', el.value); break;
      case 'recon-toggle': store.recon.toggleRow(key, el.checked); break;
      case 'individual-item': store.individual.selectItem(el.value); break;
      case 'individual-chat': store.individual.selectChat(el.value); break;
      case 'individual-ack': store.individual.setAck(el.checked); break;
    }
  });

  document.addEventListener('input', function (ev) {
    var el = act(ev.target);
    if (!el) return;
    var a = el.getAttribute('data-action');
    if (a === 'filter-q') store.setLibraryFilter('query', el.value);
    else if (a === 'recon-q') store.recon.setFilter('query', el.value);
    else if (a === 'individual-q') store.individual.search(el.value);
  });

  document.addEventListener('submit', function (ev) {
    ev.preventDefault();
    if (ev.target.id === 'individual-form') { store.individual.prepare(); return; }
    if (ev.target.id === 'recon-form') { store.recon.startRun(); return; }
    if (ev.target.id === 'recon-hf-form') { store.recon.saveHistory(false); return; }
    if (ev.target.id !== 'login-form') return;
    var input = document.getElementById('login-password');
    var pw = input.value;
    if (!pw) { document.getElementById('login-error').textContent = 'Escribe la contraseña.'; input.focus(); return; }
    input.value = '';
    store.login(pw);
  });

  // <details> no propaga "toggle": se escucha en captura
  document.addEventListener('toggle', function (ev) {
    var el = ev.target;
    if (el && el.getAttribute && el.getAttribute('data-action') === 'group-toggle') store.state.openGroups[el.getAttribute('data-id')] = el.open;
  }, true);

  // Carátula que no carga: se retira la imagen y queda el marcador con el título
  document.addEventListener('error', function (ev) {
    var t = ev.target;
    if (t && t.tagName === 'IMG' && t.classList.contains('cover__img') && t.parentNode) t.parentNode.removeChild(t);
  }, true);

  // Esc o cierre nativo del diálogo (no mientras se envía)
  $dialog.addEventListener('cancel', function (ev) { ev.preventDefault(); store.closeConfirm(); });

  // Protección: no cerrar la pestaña a mitad de un envío
  window.addEventListener('beforeunload', function (ev) {
    if (store.state.confirm.busy || (store.state.individual && store.state.individual.busy)) { ev.preventDefault(); ev.returnValue = ''; }
  });

  store.init();
})();
