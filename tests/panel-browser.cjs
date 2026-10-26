/* Prueba en navegador real del panel (/manager/) contra una instancia local en marcha.
 *   PANEL_URL=http://127.0.0.1:8093 PANEL_PASSWORD=emby-demo-003 \
 *   PLAYWRIGHT_CORE=<ruta a playwright-core> CHROMIUM_PATH=<chrome-headless-shell> \
 *   node tests/panel-browser.cjs [--shots]
 * Recorre login, biblioteca, historial, envío con decisiones, confirmación y resultados, fallos de red y móvil 390px.
 * Cualquier petición fuera del origen del panel hace fallar la prueba.
 */
'use strict';
const path = require('path');
const BASE = (process.env.PANEL_URL || 'http://127.0.0.1:8093').replace(/\/$/, '');
const PASSWORD = process.env.PANEL_PASSWORD || 'emby-demo-003';
const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const CHROMIUM = process.env.CHROMIUM_PATH || chromium.executablePath();
const SHOTS = process.argv.includes('--shots');
const SHOT_DIR = path.join(__dirname, '..', 'screenshots', 'emby003');

const results = [];
function check(name, ok, detail) { results.push({ name, ok: !!ok, detail }); console.log((ok ? 'OK   ' : 'FALLO') + ' ' + name + (ok ? '' : ' → ' + (detail || ''))); }

(async () => {
  const browser = await chromium.launch({ executablePath: CHROMIUM, args: ['--no-sandbox'] });
  const origin = new URL(BASE).origin;
  const external = [], jsErrors = [], consoleErrors = [];

  async function newPage(width, height) {
    const ctx = await browser.newContext({ viewport: { width, height }, locale: 'es-ES' });
    const page = await ctx.newPage();
    page.setDefaultTimeout(7000);
    await page.route("**/*", r => { const u=r.request().url(); return u.startsWith("data:") || new URL(u).origin===origin ? r.continue() : (external.push(u),r.abort()); });
    page.on('request', r => { const u = r.url(); if (!u.startsWith(origin) && !u.startsWith('data:')) external.push(u); });
    page.on('pageerror', e => jsErrors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    return page;
  }
  async function shot(page, name) { if (SHOTS) await page.screenshot({ path: path.join(SHOT_DIR, name + '.png'), fullPage: false }); }
  async function fullShot(page, name) { if (SHOTS) await page.screenshot({ path: path.join(SHOT_DIR, name + '.png'), fullPage: true }); }
  async function overflow(page) { return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth); }
  const text = (page, sel) => page.locator(sel).first().innerText();

  async function login(page, pw) {
    await page.fill('#login-password', pw);
    await page.click('#login-submit');
  }

  async function enableVoluntaryResend(page) {
    await page.check('[data-fid="resend"]', {force:true});
    await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
    await page.locator('[data-action="decide-toggle"]').first().check();
    await page.waitForFunction(() => document.querySelector('[data-action="open-confirm"]').getAttribute('aria-disabled') !== 'true');
  }

  // ===== Escritorio =====
  let page = await newPage(1280, 800);
  await page.goto(BASE + '/manager/');
  await page.waitForSelector('#login-form');
  check('banner de modo visible con texto DEMOSTRACIÓN', /DEMOSTRACI/.test(await text(page, '#mode-banner')));
  check('sin navegación antes de entrar', await page.locator('#nav').isHidden());
  await shot(page, '01-login-escritorio');

  await login(page, 'incorrecta');
  await page.waitForFunction(() => document.getElementById('login-error').textContent.trim().length > 0);
  check('contraseña errónea muestra error y sigue en login', (await page.locator('#login-form').count()) === 1 && (await text(page, '#login-error')).length > 0);
  check('campo contraseña vacío tras intento', (await page.inputValue('#login-password')) === '');
  await shot(page, '02-login-error');

  await login(page, PASSWORD);
  await page.waitForSelector('.grid .card');
  check('login correcto: biblioteca con carátulas', (await page.locator('.grid .card').count()) > 0);
  check('menú y cierre de sesión visibles', await page.locator('#nav').isVisible() && await page.locator('#logout').isVisible());
  await page.waitForFunction(() => Array.from(document.images).every(i => i.complete));
  const imgs = await page.evaluate(() => Array.from(document.querySelectorAll('.cover__img')).map(i => ({ ok: i.naturalWidth > 0, src: i.getAttribute('src') })));
  check('las carátulas usan image_url de la API y cargan', imgs.length > 0 && imgs.every(i => i.ok && i.src.startsWith('/api/')), JSON.stringify(imgs.slice(0, 2)));
  check('sin desbordamiento horizontal (escritorio)', (await overflow(page)) <= 0);
  const storage = await page.evaluate(() => ({ l: localStorage.length, s: sessionStorage.length, c: document.cookie }));
  check('sin localStorage/sessionStorage y cookie de sesión no legible por JS', storage.l === 0 && storage.s === 0 && !/session/.test(storage.c), JSON.stringify(storage));
  await shot(page, '03-biblioteca-escritorio');

  // Búsqueda y filtros
  const total0 = await page.locator('.grid .card').count();
  await page.click('input[name="kind"][value="series"]');
  await page.waitForFunction(n => document.querySelectorAll('.grid .card').length !== n || true, total0);
  await page.waitForTimeout(400);
  const kinds = await page.$$eval('.card .card__kind', els => els.map(e => e.textContent.trim()));
  check('filtro Series solo muestra series', kinds.length > 0 && kinds.every(k => k === 'Serie'), kinds.join(','));
  await page.click('input[name="kind"][value="all"]');
  await page.waitForTimeout(400);
  await page.fill('input[data-fid="q"]', 'zzzz-no-existe');
  await page.waitForSelector('.empty');
  check('búsqueda sin resultados muestra estado vacío', /Ningún título/.test(await text(page, '.empty')));
  await page.fill('input[data-fid="q"]', '');
  await page.waitForSelector('.grid .card');
  check('limpiar búsqueda recupera la biblioteca', (await page.locator('.grid .card').count()) > 0);
  const pg = await page.locator('.pagination__label').count() ? await text(page, '.pagination__label') : '';
  check('paginación de biblioteca visible', /Página 1 de \d+/.test(pg), pg);
  if (/de [2-9]/.test(pg)) {
    await page.click('[data-action="page"][data-id="1"]');
    await page.waitForFunction(() => /Página 2/.test(document.querySelector('.pagination__label').textContent));
    check('siguiente página de la biblioteca', true);
    await page.click('[data-action="page"][data-id="-1"]');
    await page.waitForFunction(() => /Página 1/.test(document.querySelector('.pagination__label').textContent));
  }

  // Selección múltiple por ratón y por teclado
  const cards = page.locator('.grid .card');
  await cards.nth(0).locator('label').click();
  await cards.nth(1).locator('label').click();
  await page.locator('.card__check').nth(2).focus();
  await page.keyboard.press('Space');
  check('multiselección ratón + teclado: 3 seleccionados', /3 seleccionados/.test(await text(page, '.toolbar--actions p')));
  check('bandeja con el lote', /3 títulos/.test(await text(page, '#tray')));
  await shot(page, '04-biblioteca-seleccion');

  // Filtro por estado en un chat
  await page.selectOption('[data-fid="f-chat"]', 'demo-series');
  await page.waitForTimeout(500);
  await page.selectOption('[data-fid="f-status"]', 'history_unknown');
  await page.waitForTimeout(500);
  const refBadges = await page.$$eval('.card__ref .badge', els => els.map(e => e.textContent.trim()));
  check('filtro chat+estado: todas las tarjetas con ese estado', refBadges.length > 0 && refBadges.every(t => /Historial desconocido/.test(t)), refBadges.join('|'));
  await page.selectOption('[data-fid="f-status"]', '');
  await page.selectOption('[data-fid="f-chat"]', '');
  await page.waitForTimeout(500);

  // ===== Envío =====
  await page.click('#nav [data-view="send"]');
  await page.waitForSelector('#h-send');
  await page.waitForSelector('.dests input');
  check('Envío: destinos cargados desde la API', (await page.locator('.dests input').count()) >= 3);
  check('Envío sin destinos: confirmar bloqueado con motivo', (await page.getAttribute('[data-action="open-confirm"]', 'aria-disabled')) === 'true' && /destino/i.test(await text(page, '#why')));
  await page.check('[data-id="demo-cine"]');
  await page.check('[data-id="demo-series"]');
  await page.check('[data-id="demo-private"]');
  await page.waitForSelector('.prow');
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
  check('plan por destino: filas devueltas por el servidor', (await page.locator('.prow').count()) === 9);
  check('vista previa con texto del servidor', (await text(page, '.tg__caption')).length > 0);
  check('lote preparado sin enviar visible', /preparado, sin enviar/.test(await page.locator('.panel[aria-labelledby="h-plan"]').innerText()));
  const pend = await page.locator('.choice--required').count();
  check('incierto/desconocido exigen decisión (requerido)', pend > 0, 'pendientes=' + pend);
  check('confirmar bloqueado mientras hay decisiones', (await page.getAttribute('[data-action="open-confirm"]', 'aria-disabled')) === 'true' && /decisi/i.test(await text(page, '#why')), await text(page, '.actionbar'));
  await fullShot(page, '05-envio-plan-decisiones');
  await shot(page, '05b-envio-plan-viewport');

  // Decidir: omitir todos los dudosos → re-prepara
  await page.click('[data-action="decide-all"][data-value="skip"]');
  await page.waitForFunction(() => !document.querySelector('.choice--required') && !document.querySelector('.panel[aria-busy="true"]'));
  check('omitir dudosos: ya no quedan decisiones pendientes', true);
  check('confirmar coherente tras decidir: habilitado o sin nada que enviar', (await page.getAttribute('[data-action="open-confirm"]', 'aria-disabled')) === null || /No hay nada que enviar/.test(await text(page, '#why')), await text(page, '.actionbar'));
  // Cambiar a enviar los dudosos de un par → riesgo de duplicado
  await page.locator('.choice input[value="send"]').first().check();
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
  check('enviar un dudoso marca "Posible duplicado"', (await page.locator('.risk').count()) > 0);
  // Para tener un resultado reproducible aunque la BD ya tenga datos: demo-private deja siempre "incierto"
  await page.click('[data-action="decide-all"][data-value="send"]');
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));

  // Confirmación
  await page.click('[data-action="open-confirm"]');
  await page.waitForSelector('#confirm-dialog[open]');
  check('diálogo modal abierto con foco en Cancelar', await page.evaluate(() => document.activeElement && document.activeElement.getAttribute('data-fid') === 'cancel-confirm'));
  check('diálogo avisa de demostración', /Demostraci/.test(await text(page, '#dialog-body')));
  check('riesgo de duplicado exige casilla', (await page.getAttribute('#dialog-body [data-action="confirm-send"]', 'aria-disabled')) === 'true');
  await shot(page, '06-confirmacion');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.getElementById('confirm-dialog').open);
  check('Esc cierra el diálogo sin enviar', (await page.locator('#h-res').count()) === 0);
  await page.click('[data-action="open-confirm"]');
  await page.waitForSelector('#confirm-dialog[open]');
  await page.click('#dialog-body [data-action="confirm-send"]', { force: true });   // sin casilla (aria-disabled): no debe enviar
  await page.waitForTimeout(300);
  check('confirmar sin aceptar el riesgo no envía', (await page.locator('#h-res').count()) === 0 && await page.locator('#confirm-dialog[open]').count() === 1);
  await page.check('#dialog-body [data-action="ack-dup"]');
  await page.click('#dialog-body [data-action="confirm-send"]');
  await page.waitForSelector('#h-res', { timeout: 15000 });
  check('resultado por destino mostrado', (await page.locator('.results .group').count()) === 3);
  const resText = await text(page, '.results');
  check('resultado honesto: enviados, fallidos e inciertos coherentes con el servidor', /enviados/.test(resText) && /fallidos/.test(resText), resText.slice(0, 200));
  check('resultado indica que es demostración', /Demostraci/.test(resText));
  await fullShot(page, '07-resultado');

  // Recuperar
  const canRecover = await page.locator('[data-action="recover-result"]').count();
  check('hay acción de recuperar fallidos/inciertos', canRecover === 1);
  await page.click('[data-action="recover-result"]');
  await page.waitForSelector('.prow');
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
  const rows2 = await page.$$eval('.prow', els => els.map(e => e.innerText.replace(/\s+/g, ' ')));
  check('recuperar: los enviados se omiten (no se duplican)', rows2.every(r => !/Enviado/.test(r) || /Omitido/.test(r)), rows2.join(' // '));
  await fullShot(page, '08-recuperar-plan');

  // Reenvío voluntario
  await page.check('[data-fid="resend"]', { force: true });
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
  check('reenvío voluntario activa aviso', /Reenvío voluntario activo/.test(await page.locator('.panel[aria-labelledby="h-plan"]').innerText()));
  await page.uncheck('[data-fid="resend"]', { force: true });

  // ===== Historial =====
  await page.click('#nav [data-view="history"]');
  await page.waitForSelector('.hrow');
  check('historial con filas reales', (await page.locator('.hrow').count()) > 0);
  const hp = await page.locator('.pagination__label').count() ? await text(page, '.pagination__label') : '';
  check('historial paginado', /Página 1 de \d+/.test(hp), hp);
  await page.click('.hrow [data-action="toggle-detail"]');
  await page.waitForSelector('.attempts, .hrow__detail .alert');
  check('detalle de intentos de una entrega', (await page.locator('.attempts li').count()) > 0);
  await shot(page, '09-historial');
  await page.selectOption('[data-fid="h-status"]', 'failed');
  await page.waitForTimeout(500);
  const hs = await page.$$eval('.hrow .badge', els => els.map(e => e.textContent.trim()));
  check('filtro de historial por estado', hs.every(t => /Fallido/.test(t)), hs.join(','));
  await page.selectOption('[data-fid="h-status"]', '');
  await page.selectOption('[data-fid="h-chat"]', 'demo-private');
  await page.waitForTimeout(500);
  await page.click('[data-action="prepare-recovery"]');
  await page.waitForSelector('#h-send');
  await page.waitForSelector('.prow');
  check('preparar recuperación desde historial abre Envío con el lote', (await page.locator('.selchip').count()) > 0);

  // ===== Errores de red =====
  await page.click('#nav [data-view="library"]');
  await page.waitForSelector('.grid .card');
  await page.route('**/api/catalog**', r => r.abort());
  await page.selectOption('[data-fid="f-chat"]', 'demo-cine');
  await page.waitForSelector('[data-action="retry"]');
  check('error de red: mensaje y botón Reintentar consulta', /contactar|conexi/i.test(await text(page, '.alert--err')) && /Reintentar consulta/.test(await text(page, '[data-action="retry"]')));
  await shot(page, '10-error-red');
  await page.unroute('**/api/catalog**');
  await page.click('[data-action="retry"]');
  await page.waitForSelector('.grid .card');
  check('reintentar consulta recupera los datos', true);

  // Sesión caducada (401) → vuelve al login con aviso
  await page.route('**/api/catalog**', r => r.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: 'auth', message: 'Sesión requerida' }) }));
  await page.selectOption('[data-fid="f-chat"]', '');
  await page.waitForSelector('#login-form');
  check('401: vuelve al login con aviso de sesión caducada', /caducado/.test(await text(page, '#login-notice')));
  await page.unroute('**/api/catalog**');

  // Entrar de nuevo y cerrar sesión
  await login(page, PASSWORD);
  await page.waitForSelector('.grid .card');
  await page.click('#logout');
  await page.waitForSelector('#login-form');
  check('cerrar sesión devuelve al login', await page.locator('#nav').isHidden());

  // ===== Fallo de red al confirmar: no se crea otro lote, se consulta el mismo =====
  await login(page, PASSWORD);
  await page.waitForSelector('.grid .card');
  await page.locator('.grid .card').nth(0).locator('label').click();
  await page.click('#nav [data-view="send"]');
  await page.waitForSelector('.dests input');
  await page.check('[data-id="demo-cine"]');
  await page.waitForSelector('.prow');
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
  await enableVoluntaryResend(page);
  const prepares = []; page.on('request', r => { if (/\/api\/prepare$/.test(r.url())) prepares.push(r.url()); });
  await page.route('**/api/batches/*/confirm', r => r.abort());
  await page.route('**/api/batches/*', r => r.request().method() === 'GET' ? r.abort() : r.fallback());
  await page.click('[data-action="open-confirm"]');
  await page.waitForSelector('#confirm-dialog[open]');
  const ack = page.locator('#dialog-body [data-action="ack-dup"]');
  if (await ack.count()) await ack.check();
  await page.click('#dialog-body [data-action="confirm-send"]');
  await page.waitForSelector('[data-action="check-batch"]');
  check('fallo de red al confirmar: "no sabemos si se envió", sin éxito optimista', /No sabemos si se envió/.test(await text(page, '.results')) && !/enviados/.test(await text(page, '.results')));
  check('fallo de red al confirmar: no se creó otro lote', prepares.length === 0);
  await shot(page, '11-confirmar-sin-red');
  await page.unroute('**/api/batches/*/confirm');
  await page.unroute('**/api/batches/*');
  // El servidor aún está ejecutando el lote: no es un estado final
  const bid = await page.locator('.results code').first().innerText();
  const fakeBatch = (status, results, summary) => r => r.request().method() === 'GET'
    ? r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ batch_id: bid, status, results, summary }) }) : r.continue();
  const partial = [{ key: 'x|demo-cine', item_id: 'x', title: 'Título parcial', chat_id: 'demo-cine', chat_label: 'Cine', status: 'sent', delivery_id: 1, message_id: '9', error_type: null }];
  await page.route('**/api/batches/*', fakeBatch('executing', partial, { sent: 1, failed: 0, pending: 0, uncertain: 0, skipped: 0 }));
  await page.click('[data-action="check-batch"]');
  await page.waitForFunction(() => /sigue en curso/.test(document.querySelector('.results').innerText));
  check('lote executing: se muestra en curso, no terminado', /Lote en curso/.test(await text(page, '.results')) && (await page.locator('.stats--big').count()) === 0);
  check('lote executing: no permite lote nuevo ni recuperar', (await page.locator('[data-action="new-batch"], [data-action="recover-result"]').count()) === 0 && (await page.locator('[data-action="check-batch"]').count()) === 1);
  check('lote executing: resultados parciales visibles', /Título parcial/.test(await text(page, '.results')));
  check('lote executing: no se anuncia como terminado', !/Envío terminado/.test(await page.locator('#live').innerText()));
  await shot(page, '11b-lote-en-curso');
  await page.unroute('**/api/batches/*');
  await page.route('**/api/batches/*', fakeBatch('completed', partial, { sent: 1, failed: 0, pending: 0, uncertain: 0, skipped: 0 }));
  await page.click('[data-action="check-batch"]');
  await page.waitForFunction(() => /Resultado por destino/.test(document.querySelector('.results').innerText));
  check('lote completed: ahora sí resultado final con acciones', (await page.locator('[data-action="new-batch"]').count()) === 1);
  await page.unroute('**/api/batches/*');
  await page.evaluate(() => 0);
  await page.click('[data-action="new-batch"]');
  await page.waitForSelector('.grid .card');
  await page.locator('.grid .card').nth(0).locator('label').click();
  await page.click('#nav [data-view="send"]');
  await page.waitForSelector('.dests input');
  await page.check('[data-id="demo-cine"]');
  await page.waitForSelector('.prow');
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
  await enableVoluntaryResend(page);
  await page.click('[data-action="open-confirm"]');
  await page.waitForSelector('#confirm-dialog[open]');
  await page.click('#dialog-body [data-action="cancel-confirm"]');
  await page.click('#nav [data-action="view"][data-view="library"]');
  await page.click('#nav [data-view="send"]');
  await page.waitForSelector('.prow');
  await page.click('[data-action="open-confirm"]', { force: true });
  await page.waitForSelector('#confirm-dialog[open]');
  await page.click('#dialog-body [data-action="cancel-confirm"]');
  await page.waitForTimeout(100);
  // Mismo flujo con respuesta de confirm en estado executing
  await page.route('**/api/batches/*/confirm', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ batch_id: 'b-x', status: 'executing', results: [], summary: {} }) }));
  await page.click('[data-action="open-confirm"]');
  await page.waitForSelector('#confirm-dialog[open]');
  const ack2 = page.locator('#dialog-body [data-action="ack-dup"]');
  if (await ack2.count()) await ack2.check();
  await page.click('#dialog-body [data-action="confirm-send"]');
  await page.waitForFunction(() => /Lote en curso/.test(document.querySelector('.results') ? document.querySelector('.results').innerText : ''));
  check('confirm devuelve executing: tampoco se da por terminado', (await page.locator('[data-action="new-batch"]').count()) === 0);
  await page.unroute('**/api/batches/*/confirm');
  await shot(page, '12-confirmacion-en-curso');
  await page.context().close();

  // ===== Móvil 390 =====
  page = await newPage(390, 844);
  await page.goto(BASE + '/manager/');
  await page.waitForSelector('#login-form');
  check('móvil: login sin desbordamiento', (await overflow(page)) <= 0);
  await shot(page, '20-login-movil');
  await login(page, PASSWORD);
  await page.waitForSelector('.grid .card');
  await page.waitForTimeout(300);
  check('móvil: biblioteca sin desbordamiento', (await overflow(page)) <= 0, 'overflow=' + await overflow(page));
  const cols = await page.evaluate(() => getComputedStyle(document.querySelector('.grid')).gridTemplateColumns.split(' ').length);
  check('móvil: 2 columnas de carátulas', cols === 2, 'cols=' + cols);
  await page.locator('.grid .card').nth(0).locator('label').click();
  await page.locator('.grid .card').nth(3).locator('label').click();
  await shot(page, '21-biblioteca-movil');
  await page.click('#nav [data-view="send"]');
  await page.waitForSelector('.dests input');
  await page.check('[data-id="demo-series"]');
  await page.check('[data-id="demo-private"]');
  await page.waitForSelector('.prow');
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
  check('móvil: envío sin desbordamiento', (await overflow(page)) <= 0, 'overflow=' + await overflow(page));
  await fullShot(page, '22-envio-movil');
  const small = await page.$$eval('button, input, select, summary, label.check, label.radio', els => els.filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.height < 24 || r.width < 24) && !e.classList.contains('card__check') && !e.closest('.seg') && !e.closest('.switch') && e.type !== 'checkbox' && e.type !== 'radio'; }).map(e => e.outerHTML.slice(0, 80)));
  check('móvil: controles con tamaño táctil mínimo 24px', small.length === 0, small.join(' | '));
  await page.click('#nav [data-view="history"]');
  await page.waitForSelector('.hrow');
  check('móvil: historial sin desbordamiento', (await overflow(page)) <= 0, 'overflow=' + await overflow(page));
  await shot(page, '23-historial-movil');
  await page.click('#nav [data-view="send"]');
  await page.waitForSelector('.prow');
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
  await page.click('[data-action="decide-all"][data-value="send"]');
  await page.waitForFunction(() => !document.querySelector('.panel[aria-busy="true"]'));
  await page.waitForFunction(() => document.querySelector('[data-action="open-confirm"]').getAttribute('aria-disabled') !== 'true');
  {
    await page.click('[data-action="open-confirm"]');
    await page.waitForSelector('#confirm-dialog[open]');
    const box = await page.locator('#confirm-dialog').boundingBox();
    check('móvil: diálogo dentro de la pantalla', box.x >= 0 && box.x + box.width <= 390 && box.y >= 0 && box.y + box.height <= 844, JSON.stringify(box));
    await shot(page, '24-confirmacion-movil');
  }

  // ===== Accesibilidad básica y red =====
  const a11y = await page.evaluate(() => {
    const dup = {}; document.querySelectorAll('[id]').forEach(e => dup[e.id] = (dup[e.id] || 0) + 1);
    const unnamed = Array.from(document.querySelectorAll('input:not([type=hidden]), select, button')).filter(e => {
      if (e.closest('dialog:not([open])')) return false;
      const lbl = e.labels && e.labels.length; const aria = e.getAttribute('aria-label') || e.getAttribute('aria-labelledby'); const txt = (e.textContent || '').trim();
      return !(lbl || aria || (e.tagName === 'BUTTON' && txt) || e.closest('fieldset'));
    }).map(e => e.outerHTML.slice(0, 90));
    return { dups: Object.keys(dup).filter(k => dup[k] > 1), unnamed, lang: document.documentElement.lang, h1: document.querySelectorAll('h1').length };
  });
  check('ids únicos', a11y.dups.length === 0, a11y.dups.join(','));
  check('controles con nombre accesible', a11y.unnamed.length === 0, a11y.unnamed.join(' | '));
  check('lang=es y un único h1', a11y.lang === 'es' && a11y.h1 === 1);
  check('ninguna petición fuera del origen del panel', external.length === 0, external.join(','));
  check('sin errores de JavaScript', jsErrors.length === 0, jsErrors.join(' | '));
  const realConsole = consoleErrors.filter(m => !/Failed to load resource|net::ERR_FAILED|status of (401|409)/i.test(m));
  check('sin errores de consola inesperados', realConsole.length === 0, realConsole.join(' | '));

  await browser.close();
  const failed = results.filter(r => !r.ok);
  console.log('\n' + (results.length - failed.length) + '/' + results.length + ' comprobaciones correctas');
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error('ERROR de la prueba:', e); process.exit(2); });
