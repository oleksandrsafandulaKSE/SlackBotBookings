"""The bot must build its Slack app without a signing secret.

Socket Mode exposes no HTTP endpoint, so there is nothing to verify inbound
signatures for and no SLACK_SIGNING_SECRET is configured. slack_sdk >= 3.4x
raises "signing_secret must not be empty" if the request-verification
middleware is built anyway — which crashed the worker on every start.
"""

import os

import pytest
from slack_bolt.async_app import AsyncApp


@pytest.fixture(autouse=True)
def no_signing_secret_in_env(monkeypatch):
    monkeypatch.delenv("SLACK_SIGNING_SECRET", raising=False)


def test_app_builds_with_no_signing_secret():
    app = AsyncApp(
        token="xoxb-not-a-real-token",
        request_verification_enabled=False,
    )

    assert app is not None


def test_main_builds_the_app_the_same_way():
    """Guards against main.py drifting back to a verification-enabled app."""
    source = open(
        os.path.join(os.path.dirname(__file__), os.pardir, "main.py")
    ).read()

    assert "request_verification_enabled=False" in source, (
        "main.py must disable request verification — Socket Mode has no "
        "signing secret and slack_sdk refuses an empty one."
    )
