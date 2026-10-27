"""QA independiente EMBY-004 (Hermes) — conciliación v1, solo contrato.

Alcance (docs/EMBY-004-API.md v1):
  * Solo la demo aislada (`create_demo_app` + `test_client`) y SQLite en tmp_path.
  * Cero red: el `conftest.py` del repo ya bloquea socket.* y falla el test si algo conecta.
  * Cero credenciales reales, cero servicios reales, cero escritura fuera de tmp_path.

Estado: la API de conciliación NO esta implementada todavia (15 rutas, todas de EMBY-003).
Los tests estan escritos contra el contrato y se **saltan** con un marcador propio mientras no
exista, de modo que la suite pasa de `skip` a `fallo` en cuanto aterrice la implementacion.

Ejecutar:
    .venv-hermes-qa/bin/python -m pytest tests/test_reconciliation_hermes.py -v
"""
from __future__ import annotations

import pytest

from emby_telegram_bot.demo import create_demo_app

PASSWORD = "emby-demo-003"
RECON_PATHS = ("/api/reconciliation/config", "/api/reconciliation/runs")
API_READY = "reconciliation_api"


# --------------------------------------------------------------------------- #
# Punto de entrada: si la API no existe, los tests se saltan (no fallan)
# --------------------------------------------------------------------------- #
def recon_ready(client) -> bool:
    """La API de conciliacion existe si responde 401/403 (exige sesion) o 200.

    NO se exige 200 sin autenticar: el contrato declara /api/reconciliation/* como
    endpoints de sesion admin, asi que un 401 anonimo es la respuesta CORRECTA de una
    API ya implementada. Pedir 200 dejaba la suite entera en skip para siempre.
    """
    return client.get("/api/reconciliation/config").status_code in (200, 401, 403)


@pytest.fixture(autouse=True)
def _skip_while_api_missing(request, client):
    """La API de conciliacion no existe todavia: se salta TODO el modulo.

    Sin esto los tests de auth fallarian con 404 (endpoint ausente) en vez de 401/403
    y darian un falso fallo de QA. En cuanto exista `/api/reconciliation/config`,
    el guard desaparece y la suite pasa a evaluar el contrato de verdad.
    """
    if recon_ready(client):
        return
    pytest.skip("EMBY-004: /api/reconciliation/* ausente (ni 401 ni 403: endpoint inexistente)")


@pytest.fixture
def app(tmp_path):
    application = create_demo_app(str(tmp_path / "recon.sqlite3"), secret_key="qa-secret")
    application.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(client):
    sess = client.get("/api/session").get_json()
    body = client.post("/api/login", json={"password": PASSWORD},
                       headers={"X-CSRF-Token": sess["csrf_token"]}).get_json()
    assert body["authenticated"] is True
    return body["csrf_token"], client


@pytest.fixture
def recon(admin):
    """Sesion admin lista solo si la API de conciliacion existe."""
    token, client = admin
    if not recon_ready(client):
        pytest.skip("EMBY-004: /api/reconciliation/* sin implementar (15 rutas = solo EMBY-003)")
    return token, client


def post(client, path, payload, token=None):
    headers = {"X-CSRF-Token": token} if token is not None else {}
    return client.post(path, json=payload, headers=headers)


def run_payload(**overrides):
    """Consulta valida: la demo exige destinos y bibliotecas seleccionados.

    `chat_ids=[]` es deliberadamente invalido segun el contrato; los valores por
    defecto son los que expone la propia demo (`demo-cine`, las dos bibliotecas).
    """
    base = {"chat_ids": ["demo-cine"], "date_from": None, "date_to": None,
            "library_ids": ["demo-movies", "demo-episodes"],
            "item_types": ["Movie", "Episode"], "scenario": "complete"}
    base.update(overrides)
    return base


def run_id_of(resp):
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body.get("run_id"), body
    return body


# =========================================================================== #
# A · config y claves exactas
# =========================================================================== #
class TestConfig:
    def test_config_get_campos_exactos(self, recon):
        token, client = recon
        body = client.get("/api/reconciliation/config").get_json()
        assert set(body) == {"mode", "history_from", "chat_ids", "libraries", "defaults"}, set(body)
        assert body["mode"] in ("demo", "operational")
        assert body["history_from"] is None or isinstance(body["history_from"], str)
        assert isinstance(body["chat_ids"], list)
        assert all(set(lib) >= {"id", "label"} for lib in body["libraries"])
        defaults = body["defaults"]
        assert set(defaults) == {"date_from", "date_to", "item_types"}
        assert defaults["item_types"] == ["Movie", "Episode"]
        assert {lib["id"]: lib["item_types"] for lib in body["libraries"]} == {
            "demo-movies": ["Movie"], "demo-episodes": ["Episode"]
        }

    def test_config_post_history_from_null_valido(self, recon):
        token, client = recon
        resp = post(client, "/api/reconciliation/config", {"history_from": None}, token)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["history_from"] is None

    def test_config_post_fecha_conocida(self, recon):
        token, client = recon
        fecha = "2026-10-01T00:00:00Z"
        assert post(client, "/api/reconciliation/config", {"history_from": fecha}, token).status_code == 200
        assert client.get("/api/reconciliation/config").get_json()["history_from"] == fecha

    def test_config_rechaza_formato_invalido(self, recon):
        token, client = recon
        for bad in ({"history_from": "ayer"}, {"history_from": 12345}, {"otra": "clave"}):
            resp = post(client, "/api/reconciliation/config", bad, token)
            assert resp.status_code in (400, 422), bad

    def test_config_requiere_sesion_admin(self, client):
        assert client.get("/api/reconciliation/config").status_code == 401
        assert client.post("/api/reconciliation/config", json={"history_from": None}).status_code == 403

    def test_config_no_infiere_fecha_del_contenido(self, recon):
        """history_from comienza null en operativo: nunca se infiere del contenido antiguo."""
        token, client = recon
        post(client, "/api/reconciliation/config", {"history_from": None}, token)
        assert client.get("/api/reconciliation/config").get_json()["history_from"] is None


# =========================================================================== #
# B · inicio de consulta y resumen
# =========================================================================== #
class TestRuns:
    def test_run_resumen_campos_exactos(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        assert set(body) >= {"run_id", "status", "complete", "total", "scanned", "duplicates",
                             "pages", "issues", "summary", "scope", "created_at"}
        assert body["status"] in ("complete", "partial", "failed")
        assert isinstance(body["complete"], bool)
        assert set(body["summary"]) == {"delivered", "failed", "pending", "uncertain",
                                        "history_unknown", "possible_omission"}
        assert all(isinstance(v, int) for v in body["summary"].values())

    def test_escenario_complete_marca_complete_true(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(scenario="complete"), token))
        assert body["status"] == "complete" and body["complete"] is True
        assert body["issues"] == []

    def test_escenario_parcial_nunca_etiqueta_omision(self, recon):
        """Una lectura incompleta no puede producir possible_omission."""
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(scenario="partial"), token))
        assert body["status"] == "partial" and body["complete"] is False
        assert body["summary"]["possible_omission"] == 0, "un snapshot incompleto no prueba ausencia"
        assert body["issues"], "una consulta parcial debe declarar issues"

    def test_escenario_timeout_conserva_lo_leido(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(scenario="timeout"), token))
        assert body["status"] in ("partial", "failed")
        assert body["summary"]["possible_omission"] == 0
        assert body["scanned"] >= 0

    def test_escenario_duplicates_los_cuenta(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(scenario="duplicates"), token))
        assert body["duplicates"] >= 1
        assert body["summary"]["delivered"] >= 1

    def test_escenario_invalido_da_400(self, recon):
        token, client = recon
        assert post(client, "/api/reconciliation/runs", run_payload(scenario="inventado"), token).status_code == 400

    def test_run_requiere_sesion_y_csrf(self, client):
        assert client.post("/api/reconciliation/runs", json=run_payload()).status_code == 403
        assert client.get("/api/reconciliation/runs").status_code == 401


# =========================================================================== #
# C · paginación completa
# =========================================================================== #
class TestPaginacion:
    def test_runs_lista_paginado(self, recon):
        token, client = recon
        for _ in range(3):
            post(client, "/api/reconciliation/runs", run_payload(), token)
        body = client.get("/api/reconciliation/runs?page=1").get_json()
        assert set(body) == {"items", "page", "pages", "total"}
        assert body["page"] == 1 and body["total"] >= 3

    def test_run_detalle_veinte_filas_por_pagina(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        page = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        assert set(page) == {"run", "items", "page", "pages", "total"}
        assert len(page["items"]) <= 20, "el contrato fija 20 filas por página"
        assert page["page"] == 1

    def test_paginacion_recorre_todas_las_paginas_sin_duplicar(self, recon):
        """Recorrer pages debe cubrir exactamente `total` filas, sin repetir ni perder claves."""
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        first = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        total, keys = first["total"], []
        for page in range(1, first["pages"] + 1):
            chunk = client.get(f"/api/reconciliation/runs/{body['run_id']}?page={page}").get_json()
            assert chunk["page"] == page
            keys.extend(row["key"] for row in chunk["items"])
        assert len(keys) == total, f"paginacion incompleta: {len(keys)} de {total}"
        assert len(set(keys)) == len(keys), "la paginacion repite claves"

    def test_pagina_fuera_de_rango(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        resp = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=0")
        assert resp.status_code == 400 or resp.get_json()["items"] == []

    def test_filtros_de_detalle(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        base = f"/api/reconciliation/runs/{body['run_id']}"
        assert client.get(base + "?status=delivered").status_code == 200
        # un estado fuera del enumerado se rechaza: no se devuelve una lista vacía
        resp = client.get(base + "?status=bogus")
        assert resp.status_code == 400, resp.status_code
        assert resp.get_json()["error"] == "invalid_request"
        assert client.get(base + "?chat_id=no-existe").get_json()["total"] == 0
        assert client.get(base + "?query=nada-que-exista").get_json()["items"] == []


# =========================================================================== #
# D · filas: claves, estados y motivos
# =========================================================================== #
ROW_KEYS = {"key", "item_id", "title", "item_type", "series_name", "season", "episode",
            "added_at", "library_id", "chat_id", "chat_label", "status", "reason",
            "eligible", "delivery_id", "attempt_count", "event", "can_prepare"}

STATUSES = {"delivered", "failed", "pending", "uncertain", "history_unknown", "possible_omission"}


class TestFilas:
    def _rows(self, recon):
        """Todas las filas del run con el ambito completo de la demo.

        Recorre las páginas (20 por página) y usa TODOS los destinos y bibliotecas
        que expone la config: con un solo destino no aparecen failed/uncertain.
        """
        token, client = recon
        cfg = client.get("/api/reconciliation/config").get_json()
        payload = run_payload(chat_ids=cfg["chat_ids"],
                              library_ids=[lib["id"] for lib in cfg["libraries"]])
        body = run_id_of(post(client, "/api/reconciliation/runs", payload, token))
        rows = []
        first = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        for page in range(1, first["pages"] + 1):
            chunk = client.get(f"/api/reconciliation/runs/{body['run_id']}?page={page}").get_json()
            rows.extend(chunk["items"])
        assert len(rows) == first["total"], (len(rows), first["total"])
        return body, rows

    def test_claves_exactas_de_fila(self, recon):
        _, rows = self._rows(recon)
        assert rows, "la demo debe producir filas"
        for row in rows:
            assert set(row) == ROW_KEYS, (set(row) ^ ROW_KEYS)
            assert row["status"] in STATUSES
            assert row["item_type"] in ("Movie", "Episode")
            assert row["event"] == "library"
            assert isinstance(row["eligible"], bool)
            assert isinstance(row["can_prepare"], bool)
            assert row["reason"], "cada estado necesita un motivo explicito"

    def test_episodio_trae_serie_temporada_y_episodio(self, recon):
        _, rows = self._rows(recon)
        episodios = [r for r in rows if r["item_type"] == "Episode"]
        if episodios:
            assert all(r["series_name"] for r in episodios)
            assert all(isinstance(r["season"], int) or r["season"] is None for r in episodios)

    def test_estados_cubiertos_en_la_demo(self, recon):
        """La demo declara antiguo/sin fecha, enviado, fallido, uncertain y pendiente."""
        _, rows = self._rows(recon)
        presentes = {r["status"] for r in rows}
        assert presentes <= STATUSES
        assert "delivered" in presentes, "la demo debe incluir evidencia sent"
        assert "failed" in presentes
        assert "uncertain" in presentes or "pending" in presentes

    def test_delivered_exige_evidencia_real(self, recon):
        _, rows = self._rows(recon)
        for row in rows:
            if row["status"] == "delivered":
                assert row["delivery_id"] is not None, "delivered sin delivery_id no es evidencia"
                assert row["attempt_count"] >= 1

    def test_posible_omission_nunca_en_consulta_incompleta(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(scenario="partial"), token))
        assert body["summary"]["possible_omission"] == 0
        page = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        for row in page["items"]:
            assert row["status"] != "possible_omission", "lectura incompleta no puede sentenciar omision"

    def test_history_unknown_con_motivo_explicito(self, recon):
        """Toda fila sin evidencia declara POR QUE no se puede concluir nada."""
        _, rows = self._rows(recon)
        motivos = set()
        for row in rows:
            if row["status"] == "history_unknown":
                assert row["reason"].strip(), row
                motivos.add(row["reason"])
        assert motivos, "la demo no produjo ningun history_unknown"

    def test_hay_filas_preparables(self, recon):
        """La demo debe ofrecer recuperacion real, no solo diagnosis."""
        _, rows = self._rows(recon)
        preparables = [r for r in rows if r["can_prepare"]]
        assert preparables, "ninguna fila es preparable"
        assert any(r["status"] in ("history_unknown", "failed", "pending", "uncertain")
                   for r in preparables)

    def test_fecha_nula_es_history_unknown_no_omision(self, recon):
        """added_at nulo no es una ausencia demostrable."""
        _, rows = self._rows(recon)
        sin_fecha = [r for r in rows if r["added_at"] is None]
        for row in sin_fecha:
            assert row["status"] in ("history_unknown", "failed", "pending", "uncertain")

    def test_antes_de_history_from_es_history_unknown(self, recon):
        token, client = recon
        post(client, "/api/reconciliation/config", {"history_from": "2026-10-01T00:00:00Z"}, token)
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        page = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        for row in page["items"]:
            if row["status"] == "possible_omission":
                assert row["added_at"] and row["added_at"] >= "2026-10-01T00:00:00Z"

    def test_duplicados_mismo_item_y_destino(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(scenario="duplicates"), token))
        assert body["duplicates"] >= 1
        page = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        claves = [(r["item_id"], r["chat_id"]) for r in page["items"]]
        assert len(claves) == len(set(claves)), "las filas deben venir deduplicadas por par"


# =========================================================================== #
# E2 · semilla pending (F2) y ausencia de herencia cruzada
# =========================================================================== #
class TestSemillaPending:
    def test_pending_unico_y_con_motivo(self, recon):
        """F2: la demo debe poder producir el estado `pending`, no solo declararlo."""
        token, client = recon
        cfg = client.get("/api/reconciliation/config").get_json()
        payload = run_payload(chat_ids=cfg["chat_ids"],
                              library_ids=[lib["id"] for lib in cfg["libraries"]])
        body = run_id_of(post(client, "/api/reconciliation/runs", payload, token))
        assert body["summary"]["pending"] >= 1, "la demo no produjo ningun pending"

        rows = []
        for page in range(1, body["pages"] + 1):
            chunk = client.get(f"/api/reconciliation/runs/{body['run_id']}?page={page}").get_json()
            rows.extend(chunk["items"])
        pendientes = [r for r in rows if r["status"] == "pending"]
        assert len(pendientes) == 1, f"pending debe ser una semilla unica: {len(pendientes)}"
        row = pendientes[0]
        assert row["key"] == "e3|demo-cine", row["key"]
        assert row["reason"].strip()
        assert row["attempt_count"] == 0, "una intencion en cola aun no tiene intento"
        assert row["delivery_id"] is not None, "pending sin delivery_id no es recuperable"
        assert row["can_prepare"] is True
        assert row["eligible"] is True

    def test_semilla_pending_es_idempotente(self, recon):
        """Reiniciar la app no multiplica la semilla: sigue existiendo exactamente una."""
        token, client = recon
        cfg = client.get("/api/reconciliation/config").get_json()
        payload = run_payload(chat_ids=cfg["chat_ids"],
                              library_ids=[lib["id"] for lib in cfg["libraries"]])
        totales = []
        for _ in range(3):
            body = run_id_of(post(client, "/api/reconciliation/runs", payload, token))
            totales.append(body["summary"]["pending"])
        assert set(totales) == {1}, totales

    def test_sin_herencia_cruzada_serie_episodio(self, recon):
        """Un mismo id no puede clasificarse como Movie en un destino y Episode en otro."""
        token, client = recon
        cfg = client.get("/api/reconciliation/config").get_json()
        payload = run_payload(chat_ids=cfg["chat_ids"],
                              library_ids=[lib["id"] for lib in cfg["libraries"]])
        body = run_id_of(post(client, "/api/reconciliation/runs", payload, token))
        rows = []
        for page in range(1, body["pages"] + 1):
            chunk = client.get(f"/api/reconciliation/runs/{body['run_id']}?page={page}").get_json()
            rows.extend(chunk["items"])

        tipos = {}
        for row in rows:
            tipos.setdefault(row["item_id"], set()).add(row["item_type"])
        cruzados = {k: v for k, v in tipos.items() if len(v) > 1}
        assert not cruzados, f"herencia cruzada Serie/Episodio: {cruzados}"

        e3 = next((r for r in rows if r["item_id"] == "e3"), None)
        assert e3 is not None, "la semilla e3 no aparece en la conciliacion"
        assert e3["item_type"] == "Episode", e3
        assert e3["series_name"], "un episodio debe traer su serie"
        assert isinstance(e3["season"], int) and isinstance(e3["episode"], int)

        # los ids de pelicula no deben aparecer como episodios
        for row in rows:
            if row["item_type"] == "Movie":
                assert row["series_name"] is None, row


# =========================================================================== #
# E · preparación de recuperación
# =========================================================================== #
class TestPrepare:
    def test_prepare_devuelve_lote_del_motor003(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        page = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        keys = [r["key"] for r in page["items"] if r["can_prepare"]][:5]
        assert keys, "la demo debe ofrecer filas preparables"
        resp = post(client, f"/api/reconciliation/runs/{body['run_id']}/prepare",
                    {"keys": keys}, token)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        batch = resp.get_json()
        for campo in ("batch_id", "status", "rows", "summary", "can_confirm"):
            assert campo in batch, campo
        assert batch["status"] == "prepared"

    def test_prepare_respeta_maximo_veinte_pares(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        page = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        keys = [r["key"] for r in page["items"] if r["can_prepare"]]
        if len(keys) > 20:
            resp = post(client, f"/api/reconciliation/runs/{body['run_id']}/prepare",
                        {"keys": keys}, token)
            assert resp.status_code == 400, "el contrato limita a 20 pares"

    def test_prepare_rechaza_claves_ajenas(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        resp = post(client, f"/api/reconciliation/runs/{body['run_id']}/prepare",
                    {"keys": ["inventado|chat"]}, token)
        assert resp.status_code == 400

    def test_prepare_no_envia(self, recon, app):
        """La preparacion no puede crear publicaciones: solo planifica."""
        token, client = recon
        store = app.extensions["delivery_store"]
        before = store.history(page_size=20)[1]
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        page = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        keys = [r["key"] for r in page["items"] if r["can_prepare"]][:3]
        post(client, f"/api/reconciliation/runs/{body['run_id']}/prepare", {"keys": keys}, token)
        assert store.history(page_size=20)[1] == before, "prepare creo entregas"

    def test_prepare_incluye_recovery_items_de_episodios(self, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))
        page = client.get(f"/api/reconciliation/runs/{body['run_id']}?page=1").get_json()
        episodios = [r["key"] for r in page["items"] if r["item_type"] == "Episode" and r["can_prepare"]]
        if not episodios:
            pytest.skip("la demo no expone episodios preparables en esta consulta")
        batch = post(client, f"/api/reconciliation/runs/{body['run_id']}/prepare",
                     {"keys": episodios}, token).get_json()
        if "recovery_items" in batch:
            for item in batch["recovery_items"]:
                assert set(item) == {"id", "title", "kind", "year", "overview", "image_url"}
                assert item["kind"] == "episode"

    def test_confirmacion_no_esta_en_el_scope_de_conciliacion(self, recon):
        """Ninguna accion de reconciliacion envia: la confirmacion es del motor003."""
        token, client = recon
        resp = post(client, "/api/reconciliation/runs/falso/confirm",
                    {"confirm": True}, token)
        assert resp.status_code == 404


# =========================================================================== #
# F · persistencia tras reinicio
# =========================================================================== #
class TestPersistencia:
    def test_historico_de_runs_sobrevive_al_reinicio(self, app, recon):
        token, client = recon
        for _ in range(3):
            post(client, "/api/reconciliation/runs", run_payload(), token)
        total_antes = client.get("/api/reconciliation/runs").get_json()["total"]

        reopened = create_demo_app(app.extensions["delivery_store"].path, secret_key="qa-secret")
        reopened.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        c2 = reopened.test_client()
        sess = c2.get("/api/session").get_json()
        c2.post("/api/login", json={"password": PASSWORD},
                headers={"X-CSRF-Token": sess["csrf_token"]})
        total_despues = c2.get("/api/reconciliation/runs").get_json()["total"]
        assert total_despues == total_antes, "el historial de conciliaciones no sobrevivio"

    def test_run_concreto_sobrevive_al_reinicio(self, app, recon):
        token, client = recon
        body = run_id_of(post(client, "/api/reconciliation/runs", run_payload(), token))

        reopened = create_demo_app(app.extensions["delivery_store"].path, secret_key="qa-secret")
        reopened.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        c2 = reopened.test_client()
        sess = c2.get("/api/session").get_json()
        c2.post("/api/login", json={"password": PASSWORD},
                headers={"X-CSRF-Token": sess["csrf_token"]})
        assert c2.get(f"/api/reconciliation/runs/{body['run_id']}").status_code == 200

    def test_config_history_from_sobrevive_al_reinicio(self, app, recon):
        token, client = recon
        fecha = "2026-10-05T00:00:00Z"
        post(client, "/api/reconciliation/config", {"history_from": fecha}, token)

        reopened = create_demo_app(app.extensions["delivery_store"].path, secret_key="qa-secret")
        reopened.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        c2 = reopened.test_client()
        sess = c2.get("/api/session").get_json()
        c2.post("/api/login", json={"password": PASSWORD},
                headers={"X-CSRF-Token": sess["csrf_token"]})
        assert c2.get("/api/reconciliation/config").get_json()["history_from"] == fecha

    def test_reinicio_no_duplica_runs(self, app, recon):
        token, client = recon
        post(client, "/api/reconciliation/runs", run_payload(), token)
        total = client.get("/api/reconciliation/runs").get_json()["total"]
        for _ in range(3):
            create_demo_app(app.extensions["delivery_store"].path, secret_key="qa-secret")
        assert client.get("/api/reconciliation/runs").get_json()["total"] == total


# =========================================================================== #
# G · auth/CSRF exactos
# =========================================================================== #
class TestAuth:
    @pytest.mark.parametrize("method,path", [
        ("get", "/api/reconciliation/config"),
        ("post", "/api/reconciliation/config"),
        ("post", "/api/reconciliation/runs"),
        ("get", "/api/reconciliation/runs"),
    ])
    def test_endpoints_exigen_sesion(self, client, method, path):
        resp = client.get(path) if method == "get" else client.post(path, json={})
        assert resp.status_code in (401, 403), (path, resp.status_code)

    def test_mutacion_sin_csrf_no_se_ejecuta(self, admin):
        token, client = admin
        sess = client.get("/api/session").get_json()
        client.post("/api/logout", json={}, headers={"X-CSRF-Token": sess["csrf_token"]})
        resp = client.post("/api/reconciliation/runs", json=run_payload())
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "csrf"

    def test_csrf_se_rota_tras_login(self, client):
        antes = client.get("/api/session").get_json()["csrf_token"]
        despues = client.post("/api/login", json={"password": PASSWORD},
                              headers={"X-CSRF-Token": antes}).get_json()["csrf_token"]
        assert antes != despues

    def test_errores_no_exponen_excepciones(self, recon):
        token, client = recon
        resp = post(client, "/api/reconciliation/runs", run_payload(scenario="inventado"), token)
        body = resp.get_json()
        assert set(body) == {"error", "message"}, body
        assert "Traceback" not in body["message"]
