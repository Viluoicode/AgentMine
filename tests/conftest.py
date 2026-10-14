"""Automated tests never access a real provider; the live probe is a separate CLI."""

import socket
from typing import NoReturn

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Network disabled in tests; use offline transports")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
