"""Sonda de aislamiento QA EMBY-003 (Hermes) — no ejecuta código bajo test.

Verifica, SIN tocar la red ni servicios reales, que el harness de aislamiento que
usará tests/test_panel_hermes.py es efectivo en este runtime. No importa
emby_telegram_bot (el backend demo aún no existe) ni abre sockets.

Los dos tests marcados `network_guard` son los ÚNICOS autorizados a provocar un
intento de conexión (y por tanto el fallo esperado del guard): demuestran que el
bloqueo existe. El resto de la suite EMBY-003 no debe tocar la red en absoluto.
"""
from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def blocked_network(monkeypatch, request):
    attempts = []

    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("EMBY-003 QA: conexión externa bloqueada por el harness")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    yield
    if "network_guard" not in request.keywords:
        assert not attempts, "Un test intentó usar la red"


@pytest.mark.network_guard
def test_harness_bloquea_red_efectivamente():
    with pytest.raises(AssertionError, match="bloqueada"):
        socket.create_connection(("127.0.0.1", 9), timeout=0.1)
    sock = socket.socket()
    try:
        with pytest.raises(AssertionError, match="bloqueada"):
            sock.connect(("127.0.0.1", 9))
    finally:
        sock.close()


@pytest.mark.network_guard
def test_harness_bloquea_getaddrinfo():
    with pytest.raises(AssertionError, match="bloqueada"):
        socket.getaddrinfo("example.com", 443)


def test_pytest_available_y_sin_red_por_defecto():
    """Sanidad del harness: la suite corre y el guard no dispara en tests normales."""
    assert socket.getaddrinfo is not None
