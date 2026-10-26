"""All test runs are offline and use a fresh working directory/SQLite path."""
import socket
import pytest


@pytest.fixture(autouse=True)
def isolated_offline_tests(monkeypatch, tmp_path, request):
    monkeypatch.chdir(tmp_path)
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("External connections disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    # Metadata delays have no bearing on these unit/HTTP-in-memory tests.
    monkeypatch.setattr("emby_telegram_bot.webhook.time.sleep", lambda seconds: None)
    yield
    if "network_guard" not in request.keywords:
        assert not attempts, "A test tried to use an external connection, even if caught by application code"
