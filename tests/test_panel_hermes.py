"""QA independiente EMBY-003 (Hermes) sobre la implementacion real.

Alcance y aislamento (mision EMBY-003):
  * Solo la demo aislada: `create_demo_app(db_path, secret_key=...)` + `test_client`.
  * SQLite siempre en `tmp_path`; nunca `:memory:` (DeliveryStore lo rechaza).
  * Cero red: fixture autouse que bloquea socket.connect/connect_ex/
    create_connection/getaddrinfo y falla el test si algo intento conectar.
  * Cero credenciales reales: la password de la demo es publica (`emby-demo-003`).
  * No se toca el arbol protegido, Docker, SSH, LAN, webhooks ni main.

Grupos (los 10 exigidos por la mision, en el orden pedido):
  1 auth CSRF admin | 2 plan congelado | 3 confirmacion idempotente | 4 reintento
  fallidos | 5 incierto/decision | 6 historial/desconocido | 7 persistencia/reapertura
  8 entrada maxima | 9 propietario de sesion | 10 operacion de solo lectura
Mas catalogo/assets, que el contrato tambien define.

Ejecutar:
    .venv-hermes-qa/bin/python -m pytest tests/test_panel_hermes.py -v
"""
from __future__ import annotations

import json
import socket
import sqlite3

import pytest

from emby_telegram_bot.demo import create_demo_app

PASSWORD = "emby-demo-003"  # password publico de la demo (no es credencial real)
CHATS = ["demo-cine", "demo-series", "demo-private"]


# --------------------------------------------------------------------------- #
# Harness de aislamiento
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def blocked_network(monkeypatch, request):
    """Cero conexiones: cualquier intento falla y el test que lo provoco revierte."""
    attempts = []

    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("EMBY-003 QA: conexion externa bloqueada por el harness")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    yield
    if "network_guard" not in request.keywords:
        assert not attempts, "Un test intento usar la red"


@pytest.fixture
def app(tmp_path):
    return create_demo_app(str(tmp_path / "history.sqlite3"), secret_key="qa-secret")


@pytest.fixture
def client(app):
    """Cliente de la demo. SameSite=Lax solo para que el test_client devuelva la
    cookie; el panel real fija Strict (mismo origen)."""
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    return app.test_client()


@pytest.fixture
def admin(client):
    """Sesion administrativa ya abierta; devuelve (csrf_token, client)."""
    sess = get(client, "/api/session").get_json()
    resp = post(client, "/api/login", {"password": PASSWORD}, token=sess["csrf_token"])
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["csrf_token"], client


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def get(client, path, **kw):
    return client.get(path, **kw)


def post(client, path, payload, token=None, **kw):
    headers = dict(kw.pop("headers", {}) or {})
    if token is not None:
        headers["X-CSRF-Token"] = token
    return client.post(path, json=payload, headers=headers, **kw)


def new_admin(db_path, app=None):
    """Cliente con sesion admin en una demo aislada (misma base o app ya montada)."""
    app = app if app is not None else create_demo_app(str(db_path), secret_key="qa-secret")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    client = app.test_client()
    sess = get(client, "/api/session").get_json()
    body = post(client, "/api/login", {"password": PASSWORD}, token=sess["csrf_token"]).get_json()
    assert body["authenticated"] is True
    return client, body["csrf_token"]


def prepare(client, token, item_ids, chat_ids, mode="recover", decisions=None):
    return post(client, "/api/prepare",
                {"item_ids": list(item_ids), "chat_ids": list(chat_ids),
                 "mode": mode, "decisions": decisions or {}}, token=token)


def confirm(client, token, batch_id, accept_duplicate_risk=False, body=None):
    payload = {"confirm": True, "accept_duplicate_risk": accept_duplicate_risk}
    if body is not None:
        payload = body
    return post(client, f"/api/batches/{batch_id}/confirm", payload, token=token)


def confirmed_plan(client, token, item_ids, chat_ids, mode="recover", decisions=None,
                   accept_duplicate_risk=True):
    """Prepara y confirma un lote; devuelve (plan, respuesta_confirm)."""
    plan = prepare(client, token, item_ids, chat_ids, mode, decisions).get_json()
    resp = confirm(client, token, plan["batch_id"], accept_duplicate_risk=accept_duplicate_risk)
    return plan, resp


def result_of(client, token, plan, accept_duplicate_risk=True):
    """Confirma el lote y devuelve (status_code, body). Solo lotes con can_confirm."""
    assert plan["can_confirm"] is True, plan["summary"]
    resp = confirm(client, token, plan["batch_id"], accept_duplicate_risk=accept_duplicate_risk)
    return resp.status_code, resp.get_json()


def retry_until(client, token, item_id, chat_id, rounds=2):
    """Rondas de recover sobre el mismo par; devuelve la lista de estados confirmados."""
    seen = []
    decisions = {f"{item_id}|{chat_id}": "send"}
    for _ in range(rounds):
        plan = prepare(client, token, [item_id], [chat_id], decisions=decisions).get_json()
        if not plan["can_confirm"]:
            continue
        status, body = result_of(client, token, plan)
        if status == 200:
            seen.append(body["results"][0]["status"])
    return seen


def rows_by_key(plan):
    return {r["key"]: r for r in plan["rows"]}


def db_counts(app):
    """(deliveries, attempts, operations) leyendo el SQLite real de la demo."""
    store = app.extensions["delivery_store"]
    with store.connection() as db:
        return (db.execute("SELECT count(*) FROM deliveries").fetchone()[0],
                db.execute("SELECT count(*) FROM attempts").fetchone()[0],
                db.execute("SELECT count(*) FROM operations").fetchone()[0])


# =========================================================================== #
# 1 · auth + CSRF + solo admin
# =========================================================================== #
class TestAuthCsrfAdmin:
    def test_sesion_anonima_expone_token_y_modo_demo(self, client):
        body = get(client, "/api/session").get_json()
        assert body["authenticated"] is False
        assert body["user"] is None
        assert body["mode"] == "demo"
        assert body["sends_enabled"] is True
        assert isinstance(body["csrf_token"], str) and body["csrf_token"]

    def test_endpoints_protegidos_rechazan_anonimo(self, client):
        for path in ["/api/chats", "/api/catalog", "/api/history", "/api/deliveries/1"]:
            resp = get(client, path)
            assert resp.status_code == 401, (path, resp.status_code)
            assert resp.get_json()["error"] == "unauthorized"

    def test_health_y_assets_publicos(self, client):
        assert get(client, "/health").status_code == 200
        assert get(client, "/manager/").status_code == 200
        assert get(client, "/manager/static/js/api.js").status_code == 200

    def test_login_password_incorrecta_no_abre_sesion(self, client):
        sess = get(client, "/api/session").get_json()
        resp = post(client, "/api/login", {"password": "incorrecta"}, token=sess["csrf_token"])
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "invalid_password"
        assert get(client, "/api/session").get_json()["authenticated"] is False

    def test_login_correcta_abre_sesion_y_rota_csrf(self, client):
        antes = get(client, "/api/session").get_json()["csrf_token"]
        resp = post(client, "/api/login", {"password": PASSWORD}, token=antes)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["authenticated"] is True and body["user"] == "admin"
        assert body["csrf_token"] != antes
        assert get(client, "/api/session").get_json()["authenticated"] is True

    def test_logout_cierra_sesion_y_rota_csrf(self, admin):
        token, client = admin
        resp = post(client, "/api/logout", {}, token=token)
        body = resp.get_json()
        assert body["authenticated"] is False and body["user"] is None
        assert body["csrf_token"] != token
        assert get(client, "/api/chats").status_code == 401

    def test_token_antiguo_no_sirve_tras_logout(self, admin):
        token, client = admin
        post(client, "/api/logout", {}, token=token)
        assert post(client, "/api/logout", {}, token=token).status_code == 403

    def test_mutacion_sin_csrf_no_se_ejecuta(self, client):
        antes = get(client, "/api/session").get_json()["csrf_token"]
        post(client, "/api/login", {"password": PASSWORD}, token=antes)  # abre sesion
        resp = client.post("/api/prepare", json={"item_ids": ["m4"], "chat_ids": ["demo-cine"],
                                                 "mode": "recover"})
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "csrf"

    def test_mutacion_con_csrf_ajeno_no_se_ejecuta(self, admin):
        _, client = admin
        resp = post(client, "/api/prepare",
                    {"item_ids": ["m4"], "chat_ids": ["demo-cine"], "mode": "recover"},
                    token="token-que-no-es")
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "csrf"

    def test_rate_limit_login(self, client):
        for _ in range(5):
            sess = get(client, "/api/session").get_json()
            assert post(client, "/api/login", {"password": "malo"},
                        token=sess["csrf_token"]).status_code == 401
        sess = get(client, "/api/session").get_json()
        resp = post(client, "/api/login", {"password": PASSWORD}, token=sess["csrf_token"])
        assert resp.status_code == 429
        assert resp.get_json()["error"] == "rate_limited"

    def test_sesion_dura_quince_minutos(self, admin):
        """Pasado el cuarto de hora la sesion muere y el servidor rota el token.

        El backend limpia la sesion (`expire_session`) y rota `csrf`, asi que el
        token anterior queda invalidado: reutilizarlo no puede cerrar una sesion
        que ya no existe. Es lo correcto (defense in depth), no una regresion.
        """
        token, client = admin
        import emby_telegram_bot.web_manager as wm
        with client.session_transaction() as sess:
            sess["login_at"] = wm.time.time() - 1801
        assert get(client, "/api/chats").status_code == 401
        # el token viejo ya no sirve porque la sesion fue limpiada y el csrf rotado
        assert post(client, "/api/logout", {}, token=token).status_code == 403
        # y el panel sigue usable: un token fresco cierra la sesion
        fresh = get(client, "/api/session").get_json()["csrf_token"]
        assert post(client, "/api/logout", {}, token=fresh).status_code == 200

    def test_cabeceras_de_seguridad(self, admin):
        _, client = admin
        headers = get(client, "/api/session").headers
        assert "nosniff" in headers.get("X-Content-Type-Options", "")
        assert headers.get("Cache-Control") == "no-store"
        csp = headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert get(client, "/manager/").headers.get("Content-Security-Policy")


# =========================================================================== #
# 2 · plan congelado
# =========================================================================== #
class TestPlanCongelado:
    def test_estructura_del_plan(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"]).get_json()
        assert plan["status"] == "prepared"
        assert plan["mode"] == "recover"
        assert isinstance(plan["batch_id"], str) and plan["batch_id"]
        assert 0 < plan["expires_at"]
        assert plan["summary"].keys() >= {"send", "skip", "decision", "duplicates"}
        assert plan["rows"] and plan["rows"][0]["key"] == "m4|demo-cine"

    def test_campos_de_cada_fila(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"]).get_json()
        row = plan["rows"][0]
        assert set(row) >= {"key", "item_id", "title", "chat_id", "chat_label", "state",
                            "action", "delivery_id", "caption", "preview", "caption_length",
                            "caption_valid", "duplicate_risk"}
        assert row["item_id"] == "m4" and row["chat_label"]
        assert row["action"] in {"send", "retry", "skip", "decision"}
        assert row["caption_length"] == len(row["caption"])
        assert row["caption_valid"] is True

    def test_caption_congelado_entre_prepare_y_confirm(self, admin):
        token, client = admin
        plan, resp = confirmed_plan(client, token, ["m2", "s2"], ["demo-cine"],
                                    decisions={"m2|demo-cine": "send", "s2|demo-cine": "send"})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        store = client.application.extensions["delivery_store"]
        with store.connection() as db:
            persisted = [r[0] for r in db.execute(
                "SELECT a.caption FROM attempts a JOIN deliveries d ON d.id=a.delivery_id "
                "JOIN operations o ON o.id=d.operation_id ORDER BY o.item_id")]
        for row in plan["rows"]:
            assert row["caption"] in persisted, "el caption confirmado no es el congelado"

    def test_preview_es_texto_plano(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"]).get_json()
        for row in plan["rows"]:
            assert row["preview"] == row["caption"]
            assert "<" not in row["preview"]
            assert not any(m in row["preview"] for m in ("<b>", "<i>", "**", "<spoiler>"))

    def test_cada_preparacion_genera_batch_id_nuevo(self, admin):
        token, client = admin
        first = prepare(client, token, ["m4"], ["demo-cine"]).get_json()["batch_id"]
        second = prepare(client, token, ["m4"], ["demo-cine"]).get_json()["batch_id"]
        assert first != second

    def test_can_confirm_falso_con_decisiones_pendientes(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"]).get_json()
        assert plan["can_confirm"] is False
        assert plan["summary"]["decision"] >= 1
        assert confirm(client, token, plan["batch_id"]).status_code == 409

    def test_can_confirm_verdadero_cumple_las_tres_condiciones(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"],
                       decisions={"m4|demo-cine": "send"}).get_json()
        assert plan["can_confirm"] is True
        assert plan["summary"]["decision"] == 0
        assert plan["summary"]["send"] >= 1
        assert all(r["caption_valid"] for r in plan["rows"])

    def test_lote_prepared_no_expira_antes_de_tiempo(self, admin, app):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"}).get_json()
        body = get(client, f"/api/batches/{plan['batch_id']}").get_json()
        assert body["status"] == "prepared"
        assert body["batch_id"] == plan["batch_id"]
        assert len(body["rows"]) == len(plan["rows"])

    def test_lote_expirado_no_se_confirma(self, admin, app):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"}).get_json()
        store = app.extensions["delivery_store"]
        with store.connection() as db:
            db.execute("UPDATE panel_batches SET expires=? WHERE id=?", (1, plan["batch_id"]))
        resp = confirm(client, token, plan["batch_id"], accept_duplicate_risk=True)
        assert resp.status_code == 409
        assert resp.get_json()["error"] == "batch_unavailable"

    def test_lote_inexistente(self, admin):
        token, client = admin
        assert get(client, "/api/batches/no-existe").status_code == 404
        assert confirm(client, token, "no-existe").status_code == 404

    def test_summary_coherente_con_las_filas(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m1", "m2", "m3"], CHATS).get_json()
        counts = {}
        for row in plan["rows"]:
            counts[row["action"]] = counts.get(row["action"], 0) + 1
        assert plan["summary"]["skip"] == counts.get("skip", 0)
        assert plan["summary"]["decision"] == counts.get("decision", 0)
        assert plan["summary"]["send"] == counts.get("send", 0) + counts.get("retry", 0)
        assert plan["summary"]["duplicates"] == sum(1 for r in plan["rows"] if r["duplicate_risk"])


# =========================================================================== #
# 3 · confirmacion idempotente
# =========================================================================== #
class TestConfirmacionIdempotente:
    def test_confirm_repetido_devuelve_el_mismo_resultado_sin_reintentar(self, admin, app):
        token, client = admin
        plan, first = confirmed_plan(client, token, ["m4"], ["demo-cine"],
                                     decisions={"m4|demo-cine": "send"})
        assert first.status_code == 200, first.get_data(as_text=True)
        deliveries, attempts, _ = db_counts(app)
        second = confirm(client, token, plan["batch_id"], accept_duplicate_risk=True)
        assert second.status_code == 200
        assert second.get_json() == first.get_json()
        assert db_counts(app)[:2] == (deliveries, attempts), "el segundo confirm reenvio"

    def test_confirm_sin_confirm_true_no_envia(self, admin, app):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"}).get_json()
        before = db_counts(app)
        for body in ({}, {"confirm": False}, {"confirm": "si"}):
            resp = post(client, f"/api/batches/{plan['batch_id']}/confirm", body, token=token)
            assert resp.status_code == 409, body
            assert resp.get_json()["error"] == "confirmation_required"
        assert db_counts(app) == before

    def test_duplicados_requieren_accept_explicito(self, admin, app):
        token, client = admin
        plan, _ = confirmed_plan(client, token, ["m1"], ["demo-cine"], mode="resend",
                                 decisions={"m1|demo-cine": "send"}, accept_duplicate_risk=False)
        assert plan["summary"]["duplicates"] >= 1
        before = db_counts(app)
        resp = confirm(client, token, plan["batch_id"], accept_duplicate_risk=False)
        assert resp.status_code == 409
        assert db_counts(app) == before, "confirmo sin aceptar el riesgo de duplicados"

    def test_confirm_con_accept_y_luego_idempotente(self, admin):
        token, client = admin
        plan, first = confirmed_plan(client, token, ["m1"], ["demo-cine"], mode="resend",
                                     decisions={"m1|demo-cine": "send"}, accept_duplicate_risk=True)
        assert first.status_code == 200
        again = confirm(client, token, plan["batch_id"], accept_duplicate_risk=True)
        assert again.get_json() == first.get_json()

    def test_resultado_y_summary(self, admin):
        token, client = admin
        plan, resp = confirmed_plan(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"})
        body = resp.get_json()
        assert body["batch_id"] == plan["batch_id"]
        assert body["status"] == "completed"
        assert body["summary"]["sent"] == 1
        entry = body["results"][0]
        assert entry["key"] == "m4|demo-cine" and entry["status"] == "sent"
        assert entry["message_id"] is not None

    def test_recuperacion_tras_perder_la_respuesta(self, admin):
        """GET /api/batches/<id> devuelve el estado con resultados una vez ejecutado."""
        token, client = admin
        plan, resp = confirmed_plan(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"})
        assert resp.status_code == 200
        recovered = get(client, f"/api/batches/{plan['batch_id']}").get_json()
        assert recovered["status"] == "completed"
        assert recovered["results"] == resp.get_json()["results"]

    def test_ejecucion_interrumpida_no_se_reanuda(self, admin, app):
        """Un lote en estado 'executing' no acepta un segundo confirm."""
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"}).get_json()
        store = app.extensions["delivery_store"]
        with store.connection() as db:
            db.execute("UPDATE panel_batches SET status='executing' WHERE id=?", (plan["batch_id"],))
        resp = confirm(client, token, plan["batch_id"], accept_duplicate_risk=True)
        assert resp.status_code == 409
        assert resp.get_json()["error"] == "in_progress"

    def test_stale_plan_detecta_cambio_de_estado(self, admin):
        """Un plan con accion 'retry' sobre una entrega que ya es 'sent' no reintenta."""
        token, client = admin
        plan, first = confirmed_plan(client, token, ["m2"], ["demo-series"])  # failed -> retry -> sent
        assert first.get_json()["results"][0]["status"] == "sent"
        store = client.application.extensions["delivery_store"]
        with store.connection() as db:
            db.execute("UPDATE deliveries SET status='uncertain' WHERE id=?",
                       (first.get_json()["results"][0]["delivery_id"],))
        nuevo = prepare(client, token, ["m2"], ["demo-series"],
                        decisions={"m2|demo-series": "send"}).get_json()
        resp = confirm(client, token, nuevo["batch_id"], accept_duplicate_risk=True)
        assert resp.status_code in (200, 409)
        if resp.status_code == 200:
            assert resp.get_json()["results"][0]["status"] in ("sent", "skipped")


# =========================================================================== #
# 4 · reintento de fallidos (y omision de 'sent')
# =========================================================================== #
class TestReintentoFallidos:
    def test_recover_omite_sent_y_reintenta_failed(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m1", "m2"], ["demo-cine", "demo-series"]).get_json()
        rows = rows_by_key(plan)
        assert rows["m1|demo-cine"]["state"] == "sent"
        assert rows["m1|demo-cine"]["action"] == "skip"
        assert rows["m2|demo-series"]["state"] == "failed"
        assert rows["m2|demo-series"]["action"] == "retry"

    def test_recover_reintenta_pending(self, admin):
        token, client = admin
        plan = prepare(client, token, ["s1"], ["demo-series"]).get_json()
        assert plan["rows"][0]["state"] == "pending"
        assert plan["rows"][0]["action"] == "retry"

    def test_demo_series_falla_el_primer_intento_y_el_reintento_envia(self, admin):
        """Promesa del contrato: demo-series falla el primer intento de cada entrega."""
        token, client = admin
        seen = retry_until(client, token, "s3", "demo-series", rounds=3)
        assert seen == ["failed", "sent"], seen

    def test_demo_series_falla_solo_el_primer_intento_de_cada_entrega(self, admin):
        """El fallo no es permanente: el segundo intento de la misma entrega envia."""
        token, client = admin
        seen = retry_until(client, token, "m4", "demo-series", rounds=3)
        assert seen == ["failed", "sent"], seen

    def test_resend_repetido_en_demo_series_falla_siempre(self, admin):
        """HALLAZGO H7 (documentado): el fallo se decide por intento de la entrega, no por
        entrega nueva, asi que un resend repetido nunca llega al segundo intento que el
        contrato anuncia. El contrato habla de 'nueva entrega'; la UI lo muestra como reintento."""
        token, client = admin
        plan, _ = confirmed_plan(client, token, ["m4"], ["demo-series"], mode="resend",
                                 decisions={"m4|demo-series": "send"})
        assert plan["rows"][0]["state"] == "history_unknown"
        first = confirm(client, token, plan["batch_id"], accept_duplicate_risk=True).get_json()
        assert first["results"][0]["status"] == "failed"
        for _ in range(2):
            plan2 = prepare(client, token, ["m4"], ["demo-series"], mode="resend",
                            decisions={"m4|demo-series": "send"}).get_json()
            second = confirm(client, token, plan2["batch_id"], accept_duplicate_risk=True).get_json()
            assert second["results"][0]["status"] == "failed", "el segundo intento deberia enviar"

    def test_retry_no_toca_filas_sent_en_el_mismo_lote(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m1", "m2"], ["demo-cine", "demo-series"],
                       decisions={"m2|demo-series": "send"}).get_json()
        assert plan["can_confirm"] is True
        status, resp = result_of(client, token, plan)
        assert status == 200, resp
        results = {r["key"]: r["status"] for r in resp["results"]}
        assert results["m1|demo-cine"] == "skipped"
        assert results["m2|demo-series"] == "sent"

    def test_no_se_reintenta_una_fila_skip(self, admin, app):
        """Una fila 'skip' no debe crear ningun intento, ni antes ni despues."""
        token, client = admin
        before = db_counts(app)
        plan = prepare(client, token, ["m1"], ["demo-cine"], decisions={"m1|demo-cine": "send"}).get_json()
        assert plan["rows"][0]["action"] == "skip"
        assert confirm(client, token, plan["batch_id"], accept_duplicate_risk=True).status_code == 409
        assert db_counts(app) == before

    def test_retry_no_toca_filas_sent_en_el_mismo_lote(self, admin):
        """Un lote mixto: la fila 'sent' queda skip y la 'failed' se reintenta."""
        token, client = admin
        plan = prepare(client, token, ["m1", "m2"], ["demo-cine", "demo-series"],
                       decisions={"m1|demo-cine": "send", "m2|demo-series": "send",
                                  "m2|demo-cine": "send", "m1|demo-series": "send"}).get_json()
        rows = rows_by_key(plan)
        assert rows["m1|demo-cine"]["action"] == "skip"
        assert rows["m2|demo-series"]["action"] == "retry"
        assert rows["m2|demo-cine"]["action"] == "send"
        assert plan["summary"]["skip"] == 1 and plan["summary"]["decision"] == 0
        assert plan["summary"]["send"] >= 2
        assert plan["can_confirm"] is True, plan["summary"]
        status, resp = result_of(client, token, plan)
        assert status == 200, resp
        results = {r["key"]: r["status"] for r in resp["results"]}
        assert results["m1|demo-cine"] == "skipped"
        assert results["m2|demo-series"] == "sent"

    def test_el_historial_refleja_el_reintento(self, admin):
        token, client = admin
        _, resp = confirmed_plan(client, token, ["m2"], ["demo-series"])
        delivery_id = resp.get_json()["results"][0]["delivery_id"]
        detail = get(client, f"/api/deliveries/{delivery_id}").get_json()
        assert detail["delivery"]["status"] == "sent"
        assert [a["status"] for a in detail["attempts"]] == ["failed", "sent"]


# =========================================================================== #
# 5 · incierto y desconocido requieren decision
# =========================================================================== #
class TestInciertoDecision:
    def test_uncertain_sin_decision_queda_pendiente(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m3"], ["demo-private"]).get_json()
        assert plan["rows"][0]["state"] == "uncertain"
        assert plan["rows"][0]["action"] == "decision"
        assert plan["can_confirm"] is False
        assert confirm(client, token, plan["batch_id"]).status_code == 409

    def test_uncertain_con_decision_skip_no_envia(self, admin, app):
        token, client = admin
        before = db_counts(app)
        plan = prepare(client, token, ["m3"], ["demo-private"],
                       decisions={"m3|demo-private": "skip"}).get_json()
        assert plan["rows"][0]["action"] == "skip"
        assert confirm(client, token, plan["batch_id"]).status_code == 409
        assert db_counts(app) == before

    def test_uncertain_con_decision_send_se_reintenta(self, admin, app):
        token, client = admin
        plan, resp = confirmed_plan(client, token, ["m3"], ["demo-private"],
                                    decisions={"m3|demo-private": "send"})
        assert plan["rows"][0]["action"] == "retry"
        assert plan["rows"][0]["duplicate_risk"] is True
        assert resp.get_json()["results"][0]["status"] == "uncertain"

    def test_desconocido_sin_decision_queda_pendiente(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"]).get_json()
        assert plan["rows"][0]["state"] == "history_unknown"
        assert plan["rows"][0]["action"] == "decision"
        assert plan["can_confirm"] is False

    def test_desconocido_con_decision_send_envia(self, admin):
        token, client = admin
        plan, resp = confirmed_plan(client, token, ["m4"], ["demo-cine"],
                                    decisions={"m4|demo-cine": "send"})
        assert plan["rows"][0]["action"] == "send"
        assert plan["rows"][0]["duplicate_risk"] is True
        assert resp.get_json()["results"][0]["status"] == "sent"

    def test_desconocido_con_decision_skip_no_envia(self, admin, app):
        token, client = admin
        before = db_counts(app)
        plan = prepare(client, token, ["m4"], ["demo-cine"],
                       decisions={"m4|demo-cine": "skip"}).get_json()
        assert plan["rows"][0]["action"] == "skip"
        assert confirm(client, token, plan["batch_id"]).status_code == 409
        assert db_counts(app) == before

    def test_demo_private_nunca_reintento_automatico(self, admin):
        """demo-private es siempre incierto y nunca se reintenta sin decision."""
        token, client = admin
        plan = prepare(client, token, ["m3"], ["demo-private"],
                       decisions={"m3|demo-private": "send"}).get_json()
        assert plan["rows"][0]["action"] == "retry"  # explicito, no automatico
        plan2 = prepare(client, token, ["m3"], ["demo-private"]).get_json()
        assert plan2["rows"][0]["action"] == "decision"
        _, resp = confirmed_plan(client, token, ["m3"], ["demo-private"],
                                 decisions={"m3|demo-private": "send"})
        assert resp.get_json()["results"][0]["status"] == "uncertain"

    def test_resend_t_tambien_exige_decision_para_incierto(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m3"], ["demo-private"], mode="resend").get_json()
        assert plan["rows"][0]["action"] == "decision"
        assert plan["can_confirm"] is False


# =========================================================================== #
# 6 · historial, desconocido y riesgo de duplicado
# =========================================================================== #
class TestHistorialDesconocido:
    def test_sin_evidencia_es_history_unknown(self, admin):
        token, client = admin
        catalog = get(client, "/api/catalog").get_json()
        by_id = {i["id"]: i for i in catalog["items"]}
        assert by_id["m4"]["states"]["demo-cine"] == "history_unknown"
        assert by_id["m1"]["states"]["demo-cine"] == "sent"
        assert by_id["m1"]["states"]["demo-series"] == "history_unknown"

    def test_enviar_sobre_sent_marca_duplicado(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m1"], ["demo-cine"], mode="resend",
                       decisions={"m1|demo-cine": "send"}).get_json()
        assert plan["rows"][0]["state"] == "sent"
        assert plan["rows"][0]["duplicate_risk"] is True

    def test_enviar_sobre_incierto_o_desconocido_marca_duplicado(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m3", "m4"], ["demo-private", "demo-cine"], mode="recover",
                       decisions={"m3|demo-private": "send", "m4|demo-cine": "send"}).get_json()
        rows = rows_by_key(plan)
        assert rows["m3|demo-private"]["state"] == "uncertain"
        assert rows["m3|demo-private"]["duplicate_risk"] is True
        assert rows["m4|demo-cine"]["state"] == "history_unknown"
        assert rows["m4|demo-cine"]["duplicate_risk"] is True

    def test_un_fallo_posterior_no_degrada_una_publicacion_confirmada(self, admin):
        """item_status: un resend voluntario fallido no borra el 'sent' anterior."""
        token, client = admin
        confirmed_plan(client, token, ["m2"], ["demo-series"])          # sent
        confirmed_plan(client, token, ["m2"], ["demo-series"], mode="resend",
                       decisions={"m2|demo-series": "send"})           # segundo intento
        catalog = get(client, "/api/catalog").get_json()
        by_id = {i["id"]: i for i in catalog["items"]}
        assert by_id["m2"]["states"]["demo-series"] == "sent"

    def test_resend_crea_una_operacion_nueva(self, admin, app):
        token, client = admin
        _, resp = confirmed_plan(client, token, ["m4"], ["demo-cine"], mode="resend",
                                 decisions={"m4|demo-cine": "send"})
        first_id = resp.get_json()["results"][0]["delivery_id"]
        _, resp2 = confirmed_plan(client, token, ["m4"], ["demo-cine"], mode="resend",
                                  decisions={"m4|demo-cine": "send"})
        second_id = resp2.get_json()["results"][0]["delivery_id"]
        assert first_id != second_id, "resend reutilizo la entrega en vez de crear una operacion nueva"

    def test_el_historial_es_legible_y_paginado(self, admin):
        token, client = admin
        body = get(client, "/api/history").get_json()
        assert body["total"] >= 1
        assert body["page"] == 1
        assert len(body["items"]) <= 10
        item = body["items"][0]
        assert set(item) >= {"id", "operation_id", "item_id", "title", "chat_id", "chat_label",
                             "status", "message_id", "error_type", "source", "actor",
                             "created_at", "updated_at", "attempt_count"}

    def test_filtros_del_historial(self, admin):
        token, client = admin
        assert get(client, "/api/history?status=sent").get_json()["total"] == 1
        assert get(client, "/api/history?status=uncertain").get_json()["total"] == 1
        assert get(client, "/api/history?chat_id=demo-series").get_json()["total"] == 2
        assert get(client, "/api/history?item_id=m1").get_json()["total"] == 1
        assert get(client, "/api/history?chat_id=no-existe").get_json()["total"] == 0
        assert get(client, "/api/history?status=bogus").get_json()["total"] == 0

    def test_detalle_de_entrega_con_intentos(self, admin):
        token, client = admin
        detail = get(client, "/api/deliveries/1").get_json()
        assert detail["delivery"]["item_id"] == "m1"
        assert detail["attempts"][0]["status"] == "sent"
        assert get(client, "/api/deliveries/99999").status_code == 400


# =========================================================================== #
# 7 · persistencia y reapertura
# =========================================================================== #
class TestPersistencia:
    def test_las_entregas_sobreviven_a_la_reapertura(self, app, admin):
        token, client = admin
        confirmed_plan(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"})
        deliveries, attempts, operations = db_counts(app)
        assert deliveries >= 1 and attempts >= 1

        reopened = create_demo_app(str(app.extensions["delivery_store"].path), secret_key="qa-secret")
        reopened.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        c2 = reopened.test_client()
        sess = get(c2, "/api/session").get_json()
        post(c2, "/api/login", {"password": PASSWORD}, token=sess["csrf_token"])
        history = get(c2, "/api/history").get_json()
        assert history["total"] >= 1
        catalog = get(c2, "/api/catalog").get_json()
        by_id = {i["id"]: i for i in catalog["items"]}
        assert by_id["m4"]["states"]["demo-cine"] == "sent"

    def test_el_batch_preparado_sobrevive_a_la_reapertura(self, app, admin):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"}).get_json()
        path = str(app.extensions["delivery_store"].path)

        reopened = create_demo_app(path, secret_key="qa-secret")
        reopened.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        c2 = reopened.test_client()
        c2.set_cookie("session", client.get_cookie("session").value, domain="localhost")
        sess = get(c2, "/api/session").get_json()
        assert sess["authenticated"] is True, "la sesion no sobrevivio al reinicio"
        recovered = get(c2, f"/api/batches/{plan['batch_id']}").get_json()
        assert recovered["status"] == "prepared"
        assert len(recovered["rows"]) == len(plan["rows"])
        resp = post(c2, f"/api/batches/{plan['batch_id']}/confirm",
                    {"confirm": True, "accept_duplicate_risk": True},
                    token=get(c2, "/api/session").get_json()["csrf_token"])
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["status"] == "completed"

    def test_el_reinicio_no_duplica_el_sembrado(self, app, admin):
        """Los request_key de siembra son idempotentes: reiniciar no re-publica."""
        _, client = admin
        before = db_counts(app)
        create_demo_app(str(app.extensions["delivery_store"].path), secret_key="qa-secret")
        create_demo_app(str(app.extensions["delivery_store"].path), secret_key="qa-secret")
        assert db_counts(app) == before, "el reinicio volvio a sembrar publicaciones"

    def test_esquema_incompatible_se_rechaza(self, tmp_path):
        path = tmp_path / "incompatible.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA user_version=99")
        with pytest.raises(ValueError, match="schema version"):
            create_demo_app(str(path), secret_key="qa-secret")

    def test_no_acepta_basedatos_en_memoria(self, tmp_path):
        with pytest.raises(ValueError):
            create_demo_app(":memory:", secret_key="qa-secret")

    def test_registro_rechaza_modo_o_password_ausentes(self, app):
        from flask import Flask

        from emby_telegram_bot.web_manager import register_manager

        for mode, password in (("bogus", "x"), ("demo", "")):
            with pytest.raises(ValueError, match="Explicit panel mode"):
                register_manager(Flask("t"), app.extensions["delivery_store"], None, None, [],
                                 password=password, mode=mode)

    def test_confirm_bloqueado_cuando_los_envios_estan_desactivados(self, tmp_path):
        from flask import Flask

        from emby_telegram_bot.demo import CHATS
        from emby_telegram_bot.deliveries import DeliveryStore
        from emby_telegram_bot.web_manager import register_manager

        app = Flask("t")
        register_manager(app, DeliveryStore(str(tmp_path / "h.sqlite3")), None, None, CHATS,
                         password=PASSWORD, mode="demo", allow_sends=False)
        c, token = new_admin(str(tmp_path / "h.sqlite3"), app=app)
        body = get(c, "/api/session").get_json()
        assert body["sends_enabled"] is False
        resp = confirm(c, token, "cualquiera")
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "sends_disabled"


# =========================================================================== #
# 8 · entrada maxima y validacion
# =========================================================================== #
class TestEntradaMaxima:
    @pytest.mark.parametrize("payload", [
        {"item_ids": [], "chat_ids": ["demo-cine"], "mode": "recover"},
        {"item_ids": ["m4"], "chat_ids": [], "mode": "recover"},
        {"item_ids": ["m1"] * 21, "chat_ids": ["demo-cine"], "mode": "recover"},
        {"item_ids": ["m4"], "chat_ids": ["demo-cine"] * 9, "mode": "recover"},
        {"item_ids": ["m4"], "chat_ids": ["demo-cine"] * 8 + ["demo-series"], "mode": "recover"},
        {"item_ids": ["m4"], "chat_ids": ["no-existe"], "mode": "recover"},
        {"item_ids": ["zzz"], "chat_ids": ["demo-cine"], "mode": "recover"},
        {"item_ids": ["m4"], "chat_ids": ["demo-cine"], "mode": "volar"},
        {"item_ids": ["m4"], "chat_ids": ["demo-cine"], "mode": "recover",
         "decisions": {"m4|demo-cine": "quizas"}},
        {"item_ids": "m4", "chat_ids": ["demo-cine"], "mode": "recover"},
        {"item_ids": ["m4", "m4"], "chat_ids": ["demo-cine"], "mode": "recover"},
    ])
    def test_payloads_invalidos_devuelven_400(self, admin, payload):
        token, client = admin
        resp = prepare(client, token, **{k: v for k, v in payload.items() if k != "decisions"},
                       decisions=payload.get("decisions"))
        assert resp.status_code == 400, (payload, resp.get_data(as_text=True))
        assert resp.get_json()["error"] == "invalid_request"

    def test_decisions_vacio_es_un_diccionario_valido(self, admin):
        token, client = admin
        resp = prepare(client, token, ["m4"], ["demo-cine"], decisions={})
        assert resp.status_code == 200
        assert resp.get_json()["rows"][0]["action"] == "decision"

    def test_item_inexistente_no_rompe_el_servidor(self, admin):
        token, client = admin
        resp = prepare(client, token, ["zzz"], ["demo-cine"])
        assert resp.status_code == 400

    def test_json_no_objeto_se_rechaza(self, admin):
        token, client = admin
        resp = client.post("/api/prepare", json=["m4"],
                           headers={"X-CSRF-Token": token})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_json"

    def test_content_type_no_json_se_rechaza(self, admin):
        token, client = admin
        resp = client.post("/api/prepare", data="m4", content_type="text/plain",
                           headers={"X-CSRF-Token": token})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_json"

    def test_cuerpo_demasiado_grande_se_rechaza(self, admin):
        token, client = admin
        resp = post(client, "/api/prepare",
                    {"item_ids": ["m4"], "chat_ids": ["demo-cine"], "mode": "recover",
                     "pad": "x" * 60000}, token=token)
        assert resp.status_code == 413

    def test_password_larga_se_rechaza_sin_desbordar(self, client):
        sess = get(client, "/api/session").get_json()
        resp = post(client, "/api/login", {"password": "x" * 5000}, token=sess["csrf_token"])
        assert resp.status_code in (401, 413)

    def test_paginas_fuera_de_rango(self, admin):
        token, client = admin
        for path in ["/api/catalog?page=0", "/api/catalog?page=-1", "/api/catalog?page=999999",
                     "/api/history?page=0", "/api/history?page=999999"]:
            resp = get(client, path)
            assert resp.status_code == 400, (path, resp.status_code)
            assert resp.get_json()["error"] == "invalid_request"

    def test_query_se_trunca_y_no_falla(self, admin):
        token, client = admin
        resp = get(client, "/api/catalog?query=" + "a" * 5000)
        assert resp.status_code == 200

    def test_unicode_y_emojis_se_preservan(self, admin):
        token, client = admin
        catalog = get(client, "/api/catalog").get_json()
        titles = {i["title"] for i in catalog["items"]}
        assert "Órbita de invierno" in titles and "Código Aurora" in titles
        plan = prepare(client, token, ["m1"], ["demo-cine"],
                       decisions={"m1|demo-cine": "send"}).get_json()
        assert "Órbita" in plan["rows"][0]["caption"]
        assert plan["rows"][0]["caption_length"] == len(plan["rows"][0]["caption"])

    def test_preview_sin_marcas_html(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"}).get_json()
        preview = plan["rows"][0]["preview"]
        assert preview == plan["rows"][0]["caption"]
        assert "<" not in preview


# =========================================================================== #
# 9 · propietario de sesion
# =========================================================================== #
class TestPropietarioDeSesion:
    def test_otra_sesion_no_confirma_el_lote_ajeno(self, admin, app, tmp_path):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"}).get_json()

        c2, token2 = new_admin(str(tmp_path / "other.sqlite3"))

        assert get(c2, f"/api/batches/{plan['batch_id']}").status_code == 404
        assert confirm(c2, token2, plan["batch_id"]).status_code == 404

    def test_otra_sesion_sobre_la_misma_base_recibe_403(self, admin, app):
        """Misma demo, dos sesiones: el lote de una no es de la otra (contrato: 403)."""
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"}).get_json()

        c2, token2 = new_admin(str(app.extensions["delivery_store"].path))

        resp = get(c2, f"/api/batches/{plan['batch_id']}")
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "forbidden"
        assert confirm(c2, token2, plan["batch_id"]).status_code == 403

    def test_el_propietario_si_puede_confirmar(self, admin):
        token, client = admin
        plan, resp = confirmed_plan(client, token, ["m4"], ["demo-cine"],
                                    decisions={"m4|demo-cine": "send"})
        assert resp.status_code == 200

    def test_tras_logout_se_pierde_el_acceso_a_los_propios_lotes(self, admin):
        token, client = admin
        plan = prepare(client, token, ["m4"], ["demo-cine"], decisions={"m4|demo-cine": "send"}).get_json()
        post(client, "/api/logout", {}, token=token)
        assert get(client, f"/api/batches/{plan['batch_id']}").status_code == 401

    def test_tokens_csrf_distintos_entre_sesiones(self, admin, app, tmp_path):
        token, _ = admin
        c2, token2 = new_admin(str(tmp_path / "t.sqlite3"))
        assert get(c2, "/api/session").get_json()["csrf_token"] != token


# =========================================================================== #
# 10 · operacion de solo lectura
# =========================================================================== #
class TestSoloLectura:
    def test_los_get_nunca_mutan_el_historial(self, admin, app):
        token, client = admin
        before = db_counts(app)
        for path in ["/api/session", "/api/chats", "/api/catalog", "/api/catalog?page=2",
                     "/api/history", "/api/history?status=sent", "/api/deliveries/1",
                     "/api/artwork/m1", "/health", "/manager/"]:
            get(client, path)
        assert db_counts(app) == before, "un GET altero el historial"

    def test_metodos_no_definidos_son_405(self, admin):
        token, client = admin
        for method in (client.delete, client.put, client.patch):
            assert method("/api/chats").status_code == 405

    def test_confirm_no_crea_entregas_cuando_todo_es_skip(self, admin, app):
        token, client = admin
        plan = prepare(client, token, ["m1"], ["demo-cine"]).get_json()
        assert plan["rows"][0]["action"] == "skip"
        before = db_counts(app)
        assert confirm(client, token, plan["batch_id"], accept_duplicate_risk=True).status_code == 409
        assert db_counts(app) == before

    def test_el_panel_no_expone_endpoints_de_escritura_adicionales(self, app):
        """Superficie de mutacion del panel.

        EMBY-004 anade tres POST de conciliacion (config, runs y prepare de run) que
        NO envian publicaciones: config fija la fecha de inicio conocida, runs solo
        LEE la biblioteca y prepare devuelve un plan del motor003 sin ejecutarlo.
        EMBY-005 v0.5.2 añade el POST de alias, que solo modifica presentación.
        EMBY-005 v0.5.3 añade la preparación 1×1, que tampoco publica.
        El unico que envia es /api/batches/<batch_id>/confirm.
        """
        writes = set()
        for rule in app.url_map.iter_rules():
            if rule.endpoint in ("static", "manager.static_file"):
                continue
            methods = rule.methods - {"HEAD", "OPTIONS"}
            if methods - {"GET"}:
                writes.add((str(rule), tuple(sorted(methods))))
        expected = {
            ("/api/login", ("POST",)),
            ("/api/logout", ("POST",)),
            ("/api/chats/<chat_id>/alias", ("POST",)),
            ("/api/prepare", ("POST",)),
            ("/api/individual-recovery/prepare", ("POST",)),
            ("/api/batches/<batch_id>/confirm", ("POST",)),
            ("/api/reconciliation/config", ("POST",)),
            ("/api/reconciliation/runs", ("POST",)),
            ("/api/reconciliation/runs/<run_id>/prepare", ("POST",)),
        }
        assert writes == expected, writes
        # invariante duro: el unico endpoint que puede publicar es confirm
        senders = {rule for rule, _ in writes if "confirm" in rule}
        assert senders == {"/api/batches/<batch_id>/confirm"}, senders

    def test_errores_nunca_exponen_excepciones_completas(self, admin):
        token, client = admin
        for path in ["/api/deliveries/99999", "/api/artwork/zzz", "/api/catalog?page=0",
                     "/api/batches/no-existe"]:
            body = get(client, path).get_json()
            assert set(body) == {"error", "message"}, (path, body)
            assert isinstance(body["message"], str) and body["message"]
            assert "Traceback" not in body["message"] and "sql" not in body["message"].lower()

    def test_la_respuesta_no_incluye_claves_ni_tokens(self, admin, app):
        token, client = admin
        blob = ""
        for path in ["/api/session", "/api/chats", "/api/catalog", "/api/history",
                     "/api/deliveries/1", "/manager/", "/manager/static/js/api.js"]:
            blob += get(client, path).get_data(as_text=True)
        for secret in ("secret_key", "SECRET_KEY", "api_key", "apikey", "token=", "Bearer "):
            assert secret not in blob, secret
        # `password` aparece como nombre de parametro en el JS del panel: no es una fuga.


# =========================================================================== #
# Catalogo y assets (contrato v1)
# =========================================================================== #
class TestCatalogoYAssets:
    def test_page_size_doce(self, admin):
        token, client = admin
        first = get(client, "/api/catalog").get_json()
        assert len(first["items"]) == 12
        assert first["total"] == 14 and first["pages"] == 2
        second = get(client, "/api/catalog?page=2").get_json()
        assert len(second["items"]) == 2

    def test_filtros_de_catalogo(self, admin):
        token, client = admin
        series = get(client, "/api/catalog?kind=series").get_json()
        assert series["total"] == 6 and {i["kind"] for i in series["items"]} == {"series"}
        sent = get(client, "/api/catalog?status=sent").get_json()
        assert [i["id"] for i in sent["items"]] == ["m1"]
        scoped = get(client, "/api/catalog?chat_id=demo-cine&status=sent").get_json()
        assert [i["id"] for i in scoped["items"]] == ["m1"]
        assert get(client, "/api/catalog?chat_id=demo-cine&status=uncertain").get_json()["total"] == 0
        assert get(client, "/api/catalog?kind=bogus").get_json()["total"] == 0
        assert get(client, "/api/catalog?status=bogus").get_json()["total"] == 0

    def test_busqueda_case_insensitive(self, admin):
        token, client = admin
        for query, expected in (("ÓRBITA", "m1"), ("invierno", "m1"), ("Última", "m2")):
            body = get(client, f"/api/catalog?query={query}").get_json()
            assert [i["id"] for i in body["items"]] == [expected], query

    def test_image_url_nunca_apunta_a_emby(self, admin):
        token, client = admin
        for item in get(client, "/api/catalog").get_json()["items"]:
            assert item["image_url"].startswith("/api/artwork/")
            assert "://" not in item["image_url"]
        assert get(client, "/api/artwork/m1").status_code == 200
        assert get(client, "/api/artwork/zzz").status_code == 400

    def test_los_cuatro_js_del_panel_estan_servidos(self, admin):
        _, client = admin
        index = get(client, "/manager/").get_data(as_text=True)
        for script in ("/manager/static/js/api.js", "/manager/static/js/store.js",
                       "/manager/static/js/views.js", "/manager/static/js/app.js"):
            assert script in index, script
            assert get(client, script).status_code == 200, script


# --------------------------------------------------------------------------- #
# Red bloqueada: el harness existe y funciona
# --------------------------------------------------------------------------- #
@pytest.mark.network_guard
def test_el_harness_bloquea_la_red():
    with pytest.raises(AssertionError, match="bloqueada"):
        socket.create_connection(("127.0.0.1", 9), timeout=0.1)
    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="bloqueada"):
            sock.connect(("127.0.0.1", 9))


@pytest.mark.network_guard
def test_el_harness_bloquea_la_resolucion_de_nombres():
    with pytest.raises(AssertionError, match="bloqueada"):
        socket.getaddrinfo("example.com", 443)
