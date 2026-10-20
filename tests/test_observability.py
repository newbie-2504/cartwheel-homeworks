"""HW2 Part D: authentication tests for the session endpoints.

Both requests are rejected before the agent runs, so these tests need no
Langfuse, Docker, or model provider key.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from server import app as server_app


def test_session_rejects_role_that_differs_from_database(world: dict) -> None:
    # Shopper 1 claims to be support: refuse with 403 and create no session.
    server_app._SESSIONS.clear()
    with pytest.raises(HTTPException) as err:
        server_app.create_session(server_app.SessionCreate(user_id=1, role="support"))
    assert err.value.status_code == 403
    assert server_app._SESSIONS == {}


def test_token_for_one_session_cannot_authorize_another(world: dict) -> None:
    # A real but different user's token on shopper 1's session: refuse with 403.
    server_app._SESSIONS.clear()
    shopper = server_app.create_session(server_app.SessionCreate(user_id=1, role="shopper"))
    merchant = server_app.create_session(server_app.SessionCreate(user_id=9002, role="merchant"))
    with pytest.raises(HTTPException) as err:
        asyncio.run(
            server_app.post_message(
                shopper["session_id"],
                server_app.MessageIn(message="Show my recent orders."),
                authorization=f"Bearer {merchant['token']}",
            )
        )
    assert err.value.status_code == 403
