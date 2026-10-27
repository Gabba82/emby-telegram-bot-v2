/* Prueba en navegador real de la pestaña «Conciliación» (/manager/) contra una instancia DEMO local en marcha.
 *   PANEL_URL=http://127.0.0.1:33004 PANEL_PASSWORD=emby-demo-003 \
 *   PLAYWRIGHT_CORE=<ruta a playwright-core> CHROMIUM_PATH=<chrome-headless-shell> \
 *   node tests/reconciliation-browser.cjs [--shots]
 * Solo datos y destinos ficticios de la demo. Cualquier petición fuera del origen del panel hace fallar la prueba.
 * Comprueba sobre todo la garantía de pares exactos: el lote preparado contiene exactamente los pares marcados
 * y nunca se llama a /api/prepare (item_ids×chat_ids) para un lote de conciliación.
 */
'use strict';
const path = require('path');
const BASE = (process.env.PANEL_URL || 'http://127.0.0.1:8093').replace(/\/$/, '');
const PASSWORD = process.env.PANEL_PASSWORD || 'emby-demo-003';
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const CHROMIUM = process.env.CHROMIUM_PATH || chromium.executablePath();
const SHOTS = process.argv.includes('--shots');
const SHOT_DIR = path.join(__dirname, '..', 'screenshots', 'emby004');

const results = [];
function check(name, ok, detail) { results.push({ name, ok: !!ok, detail }); console.log((ok ? 'OK   ' : 'FALLO') + ' ' + name + (ok ? '' : ' → ' + (detail || ''))); }

(async () => {
  const browser = await chromium.launch({ executablePath: CHROMIUM, args: ['--no-sandbox'] });
  const origin = new URL(BASE).origin;
  const external = [], jsErrors = [], consoleErrors = [];
  const reconPrepares = [], plainPrepares = [], confirms = [];

  async function newPage(width, height) {
    const ctx = await browser.newContext({ viewport: { width, height }, locale: 'es-ES' });
    const page = await ctx.newPage();
    page.setDefaultTimeout(8000);
    await page.route('**/*', r => { const u = r.request().url(); return u.startsWith('data:') || new URL(u).origin === origin ? r.continue() : (external.push(u), r.abort()); });
    page.on('request', r => {
      const u = r.url();
      if (!u.startsWith(origin) && !u.startsWith('data:')) external.push(u);
      if (r.method() === 'POST') {
        if (/\/api\/reconciliation\/runs\/[^/]+\/prepare$/.test(u)) reconPrepares.push(JSON.parse(r.postData() || '{}'));
        else if (/\/api\/prepare$/.test(u)) plainPrepares.push(JSON.parse(r.postData() || '{}'));
        else if (/\/api\/batches\/[^/]+\/confirm$/.test(u)) confirms.push(u);
      }
    });
    page.on('pageerror', e => jsErrors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    return page;
  }
  async function shot(page, name) { if (SHOTS) await page.screenshot({ path: path.join(SHOT_DIR, name + '.png'), fullPage: false }); }
  async function fullShot(page, name) { if (SHOTS) await page.screenshot({ path: path.join(SHOT_DIR, name + '.png'), fullPage: true }); }
  async function overflow(page) { return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth); }
  const text = (page, sel) => page.locator(sel).first().innerText();
  const idle = page => page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"], .rlist[aria-busy="true"]') && !document.querySelector('main .spin'));

  async function login(page) {
    await page.goto(BASE + '/manager/');
    await page.waitForSelector('#login-form');
    await page.fill('#login-password', PASSWORD);
    await page.click('#login-submit');
    await page.waitForSelector('#nav:not([hidden])');
  }
  async function openRecon(page) {
    await page.click('#nav [data-view="reconciliation"]');
    await page.waitForSelector('#h-rec');
    await page.waitForSelector('#recon-form');
  }
  async function runQuery(page, scenario) {
    if (scenario && await page.locator('[data-fid="rf-scenario"]').count()) await page.selectOption('[data-fid="rf-scenario"]', scenario);
    await page.click('[data-fid="rf-submit"]');
    await page.waitForSelector('#h-rr');
    await page.waitForSelector('.rrow, #recon-form .alert, .panel .empty', { timeout: 20000 });
    await idle(page);
  }
  const statuses = page => page.$$eval('.rrow .badge', els => els.map(e => e.textContent.trim()));

  // ===== Escritorio =====
  let page = await newPage(1280, 900);
  await login(page);
  check('Conciliación aparece en la navegación', await page.locator('#nav [data-view="reconciliation"]').isVisible());
  await openRecon(page);
  check('banner de modo DEMOSTRACIÓN sigue visible', /DEMOSTRACI/.test(await text(page, '#mode-banner')));
  check('la pantalla dice que consultar no envía', /no env[ií]a/i.test(await text(page, '#h-rec + p')) || /solo lectura/i.test(await text(page, '[aria-labelledby="h-rec"]')));
  check('formulario: destinos, tipos, fechas y botón «Consultar biblioteca»', (await page.locator('#recon-form input[type=checkbox]').count()) >= 3 && (await page.locator('[data-fid="rf-date_from"]').count()) === 1 && /Consultar biblioteca/.test(await text(page, '[data-fid="rf-submit"]')));
  check('escenario de prueba visible solo en demostración', await page.locator('[data-fid="rf-scenario"]').count() === 1);
  check('inicio del historial: explica que debe ser fecha conocida, no conjetura', /conocida/.test(await text(page, '[aria-labelledby="h-hf"]')) && /conjetura/.test(await text(page, '[aria-labelledby="h-hf"]')));
  check('la consulta no se lanza sola al abrir la pestaña', (await page.locator('.rrow').count()) === 0);
  await shot(page, '30-conciliacion-vacia');

  // Fecha de inicio del historial: exige confirmar. La prueba la cambia, así que se restaura SIEMPRE al terminar (también si aborta).
  const hfOriginalIso = await page.evaluate(async () => (await (await fetch('/api/reconciliation/config')).json()).history_from);
  const restoreHf = async () => {
    const ctx = await browser.newContext();
    try {
      const pg = await ctx.newPage();
      await pg.goto(BASE + '/manager/');
      await pg.evaluate(async ([pw, iso]) => {
        const j = (u, o) => fetch(u, o).then(r => r.json());
        const hdr = t => ({ 'Content-Type': 'application/json', 'X-CSRF-Token': t });
        const s0 = await j('/api/session');
        const s1 = await j('/api/login', { method: 'POST', headers: hdr(s0.csrf_token), body: JSON.stringify({ password: pw }) });
        await j('/api/reconciliation/config', { method: 'POST', headers: hdr(s1.csrf_token), body: JSON.stringify({ history_from: iso }) });
      }, [PASSWORD, hfOriginalIso]);
    } finally { await ctx.close(); }
  };
  const hfOriginal = await page.inputValue('[data-fid="hf-date"]');
  try {
  await page.fill('[data-fid="hf-date"]', '2026-10-05');
  await page.click('[data-fid="hf-save"]');
  await page.waitForSelector('#recon-hf-form .login__error');
  check('guardar inicio sin confirmar que es fecha conocida → rechazado en el cliente', /fecha conocida/.test(await text(page, '#recon-hf-form .login__error')));
  await page.check('[data-fid="hf-ack"]');
  await page.click('[data-fid="hf-save"]');
  await page.waitForSelector('#recon-hf-form .alert--ok');
  check('guardar inicio con confirmación: aviso y valor guardado', /guardado/i.test(await text(page, '#recon-hf-form .alert--ok')) && (await page.inputValue('[data-fid="hf-date"]')) === '2026-10-05');
  await page.click('[data-fid="hf-clear"]');
  await page.waitForSelector('#recon-hf-form .alert--ok:has-text("eliminada")');
  check('quitar fecha → «Sin fecha conocida» y ninguna omisión posible', /Sin fecha conocida/.test(await text(page, '[aria-labelledby="h-hf"]')));
  await runQuery(page, 'complete');
  check('sin inicio de historial conocido no hay ninguna «Posible omisión»', !(await statuses(page)).some(s => /Posible omisión/.test(s)) && (await text(page, '.rtile.s-possible_omission')).trim().startsWith('0'));
  if (hfOriginal) {
    await page.fill('[data-fid="hf-date"]', hfOriginal);
    await page.check('[data-fid="hf-ack"]');
    await page.click('[data-fid="hf-save"]');
    await page.waitForSelector('#recon-hf-form .alert--ok');
  }

  // Consulta completa
  await runQuery(page, 'complete');
  const rows0 = await page.locator('.rrow').count();
  check('consulta completa: filas y resumen por estado', rows0 > 0 && (await page.locator('.rtile').count()) === 6);
  check('consulta completa: sin banner de lectura incompleta', (await page.locator('.alert:has-text("Lectura incompleta")').count()) === 0);
  check('estados con icono + texto (no solo color)', (await page.$$eval('.rrow .badge', els => els.every(e => e.querySelector('svg') && e.textContent.trim().length > 3))));
  check('instantánea explicada', /instant[aá]nea/.test(await text(page, '[aria-labelledby="h-rr"]')));
  const pg = await page.locator('.pagination__label').first().innerText();
  check('paginación visible', /Página 1 de \d+/.test(pg), pg);
  await fullShot(page, '31-conciliacion-resultado');
  await shot(page, '31b-conciliacion-viewport');

  // Filtros
  const firstTile = page.locator('.rtile:not(.s-possible_omission)').first();
  const failedCount = parseInt((await text(page, '.rtile.s-failed b')).trim(), 10);
  if (failedCount > 0) {
    await page.click('.rtile.s-failed');
    await page.waitForFunction(() => document.querySelector('.rtile.s-failed').getAttribute('aria-pressed') === 'true');
    await idle(page);
    const sts = await statuses(page);
    check('filtro por estado (tarjeta): solo filas Fallido', sts.length > 0 && sts.every(s => /Fallido/.test(s)), sts.join('|'));
    check('la tarjeta activa se anuncia con aria-pressed', (await page.getAttribute('.rtile.s-failed', 'aria-pressed')) === 'true' && (await page.inputValue('[data-fid="recon-status"]')) === 'failed');
    await page.click('.rtile.s-failed');
    await idle(page);
  }
  await page.selectOption('[data-fid="recon-status"]', 'delivered');
  await idle(page);
  const stsD = await statuses(page);
  check('filtro por estado (select): solo Enviado', stsD.every(s => /Enviado/.test(s)), stsD.join('|'));
  check('filas enviadas no se pueden seleccionar', (await page.locator('.rrow input[type=checkbox]:not([disabled])').count()) === 0 && (await page.locator('.rrow:has-text("ya consta como enviado")').count()) > 0);
  await page.selectOption('[data-fid="recon-status"]', '');
  await idle(page);
  const chatOpts = await page.$$eval('[data-fid="recon-chat"] option', os => os.map(o => o.value).filter(Boolean));
  await page.selectOption('[data-fid="recon-chat"]', chatOpts[0]);
  await idle(page);
  const labels = await page.$$eval('.rrow .rrow__main .small.muted:first-of-type', els => els.length);
  check('filtro por destino aplica y deja filas', labels > 0 || (await page.locator('.empty').count()) > 0);
  await page.selectOption('[data-fid="recon-chat"]', '');
  await idle(page);
  await page.fill('[data-fid="recon-q"]', 'zzzz-no-existe');
  await page.waitForSelector('.rlist ~ .empty, .empty:has-text("Ninguna fila")');
  check('búsqueda sin resultados → estado vacío', /Ninguna fila/.test(await text(page, '.empty')));
  await page.fill('[data-fid="recon-q"]', '');
  await page.waitForSelector('.rrow');
  await idle(page);

  // Detalle
  await page.click('.rrow [data-action="recon-detail"]');
  await page.waitForSelector('.rdetail');
  const det = await text(page, '.rdetail');
  check('detalle: motivo, Id, evento, destino y entrega', /motivo/i.test(det) && /id del título/i.test(det) && /evento/i.test(det) && /destino/i.test(det) && /entrega registrada/i.test(det));
  check('detalle: aria-expanded', (await page.getAttribute('.rrow [data-action="recon-detail"]', 'aria-expanded')) === 'true');
  await shot(page, '32-detalle-fila');
  await page.click('.rrow [data-action="recon-detail"]');

  // Selección manual entre páginas
  const pageInfo = await text(page, '.pagination__label');
  const pages = parseInt((pageInfo.match(/de (\d+)/) || [0, 1])[1], 10);
  const enabled = page.locator('.rrow input[type=checkbox]:not([disabled])');
  const nEnabled = await enabled.count();
  check('hay filas preparables para seleccionar', nEnabled >= 1, 'n=' + nEnabled);
  const pickedKeys = [];
  async function pick(n) {
    for (let i = 0; i < n; i++) {
      const cb = page.locator('.rrow input[type=checkbox]:not([disabled]):not(:checked)').first();
      if (!(await cb.count())) return;
      const key = await cb.getAttribute('data-key');
      pickedKeys.push(key);
      await page.locator('.rrow input[data-key="' + key + '"]').click();   // la lista se repinta: se verifica por clave, no por el nodo
      await page.waitForSelector('.rrow input[data-key="' + key + '"]:checked');
    }
  }
  await pick(2);
  if (pages > 1) {
    await page.click('[data-action="recon-page"][data-id="1"]');
    await page.waitForFunction(() => /Página 2/.test(document.querySelector('.pagination__label').textContent));
    await idle(page);
    check('siguiente página de la conciliación', true);
    await pick(1);
  }
  const nSel = pickedKeys.length;
  check('selección múltiple conserva los pares entre páginas', new RegExp('^' + nSel + ' de 20').test(await text(page, '.actionbar__text')), await text(page, '.actionbar__text'));
  await page.click('.selsum summary');
  check('lista de pares seleccionados (título → destino)', (await page.locator('.selsum .selchip').count()) === nSel && /→/.test(await text(page, '.selsum .selchip')));
  await shot(page, '33-seleccion');
  check('«Preparar recuperación» explica que no envía', /nada se env[ií]a/i.test(await text(page, '.actionbar__text')));

  // Preparar: lote exacto en Envío
  const confirmsBefore = confirms.length;
  await page.click('[data-fid="recon-prepare"]');
  await page.waitForSelector('#h-send');
  await page.waitForSelector('.prow');
  await idle(page);
  const lastPrep = reconPrepares[reconPrepares.length - 1];
  check('prepare llamó al endpoint de conciliación con EXACTAMENTE las keys marcadas', lastPrep && lastPrep.keys.length === nSel && pickedKeys.every(k => lastPrep.keys.includes(k)), JSON.stringify(lastPrep));
  check('no se usó /api/prepare (item_ids×chat_ids)', plainPrepares.length === 0, JSON.stringify(plainPrepares));
  check('el plan tiene exactamente un renglón por par marcado (no producto cartesiano)', (await page.locator('.prow').count()) === nSel, 'prow=' + await page.locator('.prow').count() + ' esperado=' + nSel);
  check('Envío indica lote exacto y que nada se ha enviado', /Lote exacto de conciliación/.test(await text(page, '#h-sel')) && /preparado, sin enviar/.test(await text(page, '[aria-labelledby="h-plan"]')));
  check('Envío: sin reenvío voluntario ni cambio de títulos/destinos', (await page.locator('[data-fid="resend"], [data-action="toggle-item"], [data-action="all-chats"]').count()) === 0 && (await page.locator('.dests input:not([disabled])').count()) === 0);
  check('nada se confirmó solo', confirms.length === confirmsBefore);
  await fullShot(page, '34-envio-lote-exacto');
  // Biblioteca bloqueada mientras hay lote exacto
  await page.click('#nav [data-view="library"]');
  await page.waitForSelector('.grid .card');
  check('Biblioteca: aviso y selección manual bloqueada con lote exacto abierto', (await page.locator('.alert:has-text("lote exacto")').count()) > 0 && (await page.locator('.card__check:not([disabled])').count()) === 0);
  check('la bandeja ofrece ver el lote exacto', /Lote exacto/.test(await text(page, '#tray')));
  await page.click('#nav [data-view="send"]');
  await page.waitForSelector('.prow');
  // Decisiones: cambiar una decisión reprepara con las MISMAS keys
  const prepsBefore = reconPrepares.length;
  if (await page.locator('[data-action="decide-all"][data-value="send"]').count()) {
    await page.click('[data-action="decide-all"][data-value="send"]');
    await page.waitForFunction(n => true, 0);
    await page.waitForTimeout(700);
    await idle(page);
    const again = reconPrepares[reconPrepares.length - 1];
    check('decidir reprepara con las mismas keys y las decisiones', reconPrepares.length > prepsBefore && JSON.stringify(again.keys) === JSON.stringify(lastPrep.keys) && Object.keys(again.decisions || {}).length > 0, JSON.stringify(again));
    check('seguimos sin /api/prepare tras decidir', plainPrepares.length === 0);
  }
  // Cancelar: vuelve a Conciliación y conserva la selección
  await page.click('[data-action="cancel-scope"]');
  await page.waitForSelector('#h-rec');
  await page.waitForSelector('.rrow');
  check('cancelar el lote exacto vuelve a Conciliación sin enviar', (await page.locator('#h-res').count()) === 0 && confirms.length === confirmsBefore);
  check('la selección sobrevive a cancelar', new RegExp('^' + nSel + ' de 20').test(await text(page, '.actionbar__text')));

  // Prepararlo otra vez, decidir todo "enviar" y ejecutar en DEMO (mensajes sintéticos)
  await page.click('[data-fid="recon-prepare"]');
  await page.waitForSelector('.prow');
  await idle(page);
  if (await page.locator('[data-action="decide-all"][data-value="send"]').count()) {
    await page.click('[data-action="decide-all"][data-value="send"]');
    await page.waitForTimeout(700);
    await idle(page);
  }
  const canConfirm = (await page.getAttribute('[data-action="open-confirm"]', 'aria-disabled')) !== 'true';
  if (canConfirm) {
    await page.click('[data-action="open-confirm"]');
    await page.waitForSelector('#confirm-dialog[open]');
    check('confirmación avisa de demostración', /Demostraci/.test(await text(page, '#dialog-body')));
    const ack = page.locator('#dialog-body [data-action="ack-dup"]');
    if (await ack.count()) await ack.check();
    await page.click('#dialog-body [data-action="confirm-send"]');
    await page.waitForSelector('#h-res', { timeout: 20000 });
    const nRes = await page.locator('.results .prow').count();
    check('el resultado cubre solo los pares del lote (no más)', nRes <= nSel && nRes > 0, 'filas=' + nRes + ' pares=' + nSel);
    check('confirmación única', confirms.length === confirmsBefore + 1);
    await fullShot(page, '35-resultado-conciliacion');
    if (await page.locator('[data-action="recover-result"]').count()) {
      const pBefore = reconPrepares.length;
      await page.click('[data-action="recover-result"]');
      await page.waitForSelector('.prow');
      await idle(page);
      const rec = reconPrepares[reconPrepares.length - 1];
      check('recuperar tras el resultado reprepara solo pares ya elegidos y sin /api/prepare', reconPrepares.length > pBefore && rec.keys.every(k => lastPrep.keys.includes(k)) && plainPrepares.length === 0, JSON.stringify(rec));
      await page.click('[data-action="cancel-scope"]');
      await page.waitForSelector('#h-rec');
    } else {
      await page.click('#nav [data-view="reconciliation"]');
      await page.waitForSelector('#h-rec');
    }
    await page.waitForSelector('.alert:has-text("instantánea anterior a tu envío")');
    check('tras enviar, la consulta se declara instantánea anterior y pide nueva consulta', true);
    check('con consulta obsoleta no se puede preparar más', (await page.getAttribute('[data-fid="recon-prepare"]', 'aria-disabled')) === 'true' && (await page.locator('.rrow input[type=checkbox]:not([disabled])').count()) === 0);
    await shot(page, '36-consulta-obsoleta');
    await page.click('.alert [data-action="recon-new"]');
    check('«Nueva consulta» lleva el foco al formulario', await page.evaluate(() => document.activeElement && /^rf-/.test(document.activeElement.getAttribute('data-fid') || '')));
  } else {
    check('lote exacto con decisiones tomadas es confirmable (o no queda nada que enviar)', /No hay nada que enviar|Faltan/.test(await text(page, '#why')), await text(page, '.actionbar'));
    await page.click('[data-action="cancel-scope"]');
    await page.waitForSelector('#h-rec');
  }

  // Lectura incompleta
  for (const sc of ['timeout', 'partial']) {
    await runQuery(page, sc);
    const banner = await page.locator('.alert--warn:has-text("Lectura incompleta")').count();
    check('escenario ' + sc + ': banner claro de lectura incompleta con «Nueva consulta»', banner === 1 && (await page.locator('.alert--warn [data-action="recon-new"]').count()) === 1);
    check('escenario ' + sc + ': ninguna fila ni contador de «Posible omisión»', !(await statuses(page)).some(s => /Posible omisión/.test(s)) && (await text(page, '.rtile.s-possible_omission')).trim().startsWith('0'));
    check('escenario ' + sc + ': se pueden examinar las filas leídas', (await page.locator('.rrow').count()) > 0);
    if (sc === 'timeout') await shot(page, '37-lectura-incompleta');
  }
  await runQuery(page, 'duplicates');
  check('escenario duplicates: avisos de la consulta visibles', (await page.locator('.issues li').count()) > 0);

  // Histórico persistente
  const runsListed = await page.locator('.rrun').count();
  check('histórico de consultas con varias entradas', runsListed >= 3, 'n=' + runsListed);
  await page.reload();
  await page.waitForSelector('#nav:not([hidden])');
  await openRecon(page);
  await page.waitForSelector('.rrun');
  check('el histórico persiste tras recargar', (await page.locator('.rrun').count()) >= 3);
  await page.locator('.rrun [data-action="recon-open"]').first().click();
  await page.waitForSelector('.rrow');
  check('abrir una consulta anterior muestra sus filas sin volver a leer', (await page.locator('.rrow').count()) > 0 && /Consulta/.test(await text(page, '[aria-labelledby="h-rr"] .small')));
  await shot(page, '38-historico');

  // Errores de red
  await page.route('**/api/reconciliation/runs', r => r.request().method() === 'POST' ? r.abort() : r.continue());
  await page.click('[data-fid="rf-submit"]');
  await page.waitForSelector('#recon-form .alert--warn');
  check('fallo de red al consultar: «no sabemos si terminó» y es seguro repetir', /No sabemos si la consulta termin/.test(await text(page, '#recon-form .alert--warn')) && /solo lectura/.test(await text(page, '#recon-form .alert--warn')));
  await shot(page, '39-consulta-sin-red');
  await page.unroute('**/api/reconciliation/runs');
  await page.route('**/api/reconciliation/runs/*?*', r => r.abort());
  await page.locator('.rrun [data-action="recon-open"]').first().click();
  await page.waitForSelector('[data-action="recon-retry"][data-id="items"]');
  check('error al cargar filas: mensaje y botón Reintentar consulta', /Reintentar consulta/.test(await text(page, '[data-action="recon-retry"][data-id="items"]')));
  await page.unroute('**/api/reconciliation/runs/*?*');
  await page.click('[data-action="recon-retry"][data-id="items"]');
  await page.waitForSelector('.rrow');
  check('reintentar recupera las filas', true);
  // El servidor devuelve un par de más → el cliente lo bloquea
  await page.locator('.rrow input[type=checkbox]:not([disabled])').first().check();
  await page.route('**/api/reconciliation/runs/*/prepare', async r => {
    const res = await r.fetch();
    const body = await res.json();
    const extra = Object.assign({}, body.rows[0], { key: 'ajeno|ajeno', item_id: 'ajeno', chat_id: 'ajeno' });
    await r.fulfill({ response: res, body: JSON.stringify(Object.assign({}, body, { rows: body.rows.concat([extra]) })) });
  });
  await page.click('[data-fid="recon-prepare"]');
  await page.waitForSelector('[data-action="retry"][data-id="plan"]');
  check('si el servidor añade un par no pedido, el lote se descarta y no se puede confirmar', /no estaban en tu selección/.test(await text(page, '.alert--err')) && (await page.getAttribute('[data-action="open-confirm"]', 'aria-disabled')) === 'true');
  await shot(page, '40-par-ajeno-bloqueado');
  await page.unroute('**/api/reconciliation/runs/*/prepare');
  await page.click('[data-action="cancel-scope"]');
  await page.waitForSelector('#h-rec');

  // 401 → login con aviso de sesión caducada
  await page.route('**/api/reconciliation/runs/*?*', r => r.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: 'auth', message: 'Sesión requerida' }) }));
  await page.locator('.rrun [data-action="recon-open"]').first().click();
  await page.waitForSelector('#login-form');
  check('401 en Conciliación: vuelve al login con aviso de sesión caducada', /caducado/.test(await text(page, '#login-notice')));
  await page.unroute('**/api/reconciliation/runs/*?*');
  await page.context().close();

  // ===== Móvil 390 =====
  page = await newPage(390, 844);
  await login(page);
  check('móvil: navegación con 4 secciones sin desbordar', (await overflow(page)) <= 0 && (await page.locator('#nav button').count()) === 4);
  await openRecon(page);
  check('móvil: formulario sin desbordamiento', (await overflow(page)) <= 0, 'overflow=' + await overflow(page));
  await shot(page, '50-conciliacion-movil');
  await runQuery(page, 'complete');
  check('móvil: resultado sin desbordamiento', (await overflow(page)) <= 0, 'overflow=' + await overflow(page));
  const cols = await page.evaluate(() => getComputedStyle(document.querySelector('.rtiles')).gridTemplateColumns.split(' ').length);
  check('móvil: tarjetas de resumen en 2 columnas', cols === 2, 'cols=' + cols);
  await page.click('.rrow [data-action="recon-detail"]');
  await page.waitForSelector('.rdetail');
  check('móvil: detalle sin desbordamiento', (await overflow(page)) <= 0, 'overflow=' + await overflow(page));
  await fullShot(page, '51-resultado-movil');
  if (await page.locator('.rrow input[type=checkbox]:not([disabled])').count()) {
    await page.locator('.rrow input[type=checkbox]:not([disabled])').first().check();
    await page.click('.selsum summary');
    check('móvil: selección y barra de acciones sin desbordamiento', (await overflow(page)) <= 0, 'overflow=' + await overflow(page));
    await shot(page, '52-seleccion-movil');
    await page.click('[data-fid="recon-prepare"]');
    await page.waitForSelector('.prow');
    await idle(page);
    check('móvil: lote exacto en Envío sin desbordamiento', (await overflow(page)) <= 0, 'overflow=' + await overflow(page));
    await fullShot(page, '53-envio-lote-exacto-movil');
    await page.click('[data-action="cancel-scope"]');
    await page.waitForSelector('#h-rec');
  }
  const small = await page.$$eval('button, select, summary, input[type=search], input[type=date]', els => els.filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.height < 24 || r.width < 24); }).map(e => e.outerHTML.slice(0, 80)));
  check('móvil: controles con tamaño táctil mínimo 24px', small.length === 0, small.join(' | '));

  // ===== Accesibilidad básica y red =====
  const a11y = await page.evaluate(() => {
    const dup = {}; document.querySelectorAll('[id]').forEach(e => dup[e.id] = (dup[e.id] || 0) + 1);
    const unnamed = Array.from(document.querySelectorAll('input:not([type=hidden]), select, button')).filter(e => {
      if (e.closest('dialog:not([open])')) return false;
      const lbl = e.labels && e.labels.length; const aria = e.getAttribute('aria-label') || e.getAttribute('aria-labelledby'); const txt = (e.textContent || '').trim();
      return !(lbl || aria || (e.tagName === 'BUTTON' && txt) || e.closest('fieldset'));
    }).map(e => e.outerHTML.slice(0, 90));
    const dupFid = {}; document.querySelectorAll('[data-fid]').forEach(e => dupFid[e.getAttribute('data-fid')] = (dupFid[e.getAttribute('data-fid')] || 0) + 1);
    return { dups: Object.keys(dup).filter(k => dup[k] > 1), dupFid: Object.keys(dupFid).filter(k => dupFid[k] > 1), unnamed, lang: document.documentElement.lang, h1: document.querySelectorAll('h1').length };
  });
  check('ids únicos', a11y.dups.length === 0, a11y.dups.join(','));
  check('data-fid únicos (el foco se conserva al repintar)', a11y.dupFid.length === 0, a11y.dupFid.join(','));
  check('controles con nombre accesible', a11y.unnamed.length === 0, a11y.unnamed.join(' | '));
  check('lang=es y un único h1', a11y.lang === 'es' && a11y.h1 === 1);
  check('ninguna petición fuera del origen del panel', external.length === 0, external.join(','));
  check('sin errores de JavaScript', jsErrors.length === 0, jsErrors.join(' | '));
  const realConsole = consoleErrors.filter(m => !/Failed to load resource|net::ERR_FAILED|status of (400|401|409)/i.test(m));
  check('sin errores de consola inesperados', realConsole.length === 0, realConsole.join(' | '));
  check('en toda la prueba ningún lote de conciliación usó /api/prepare', plainPrepares.length === 0, JSON.stringify(plainPrepares));

  } finally { await restoreHf().catch(e => console.log('AVISO: no se pudo restaurar el inicio del historial:', String(e))); }

  await browser.close();
  const failed = results.filter(r => !r.ok);
  console.log('\n' + (results.length - failed.length) + '/' + results.length + ' comprobaciones correctas');
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error('ERROR de la prueba:', e); process.exit(2); });
