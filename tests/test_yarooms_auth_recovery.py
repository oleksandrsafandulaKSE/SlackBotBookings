"""Recovery from a stale Yarooms token and from failing requests.

Single seam: a real local HTTP server standing in for Yarooms, so session,
header and re-auth behaviour of ``YaroomsClient._request`` is exercised
end to end. The fake answers HTTP 500 to a stale token — what production
saw before the bot had to be restarted by hand.
"""

import asyncio

import pytest
from aiohttp import ClientResponseError, web
from aiohttp.test_utils import TestServer

from clients.yarooms_client import YaroomsClient

BOOKINGS = {"status": 1, "data": {"list": []}}


class FakeYarooms:
    def __init__(self, valid_token="fresh-token", stale_status=500):
        self.valid_token = valid_token
        self.stale_status = stale_status
        self.auth_calls = 0
        self.always_500_paths: set[str] = set()
        self.seen_tokens: list[str] = []

    async def auth(self, request):
        self.auth_calls += 1
        await asyncio.sleep(0.01)
        return web.json_response({"data": {"token": self.valid_token}})

    async def api(self, request):
        token = request.headers.get("X-Token", "")
        self.seen_tokens.append(token)
        if request.path in self.always_500_paths:
            return web.json_response({"success": 0}, status=500)
        if token != self.valid_token:
            return web.json_response({"success": 0}, status=self.stale_status)
        return web.json_response(BOOKINGS)

    def app(self):
        app = web.Application()
        app.router.add_post("/api/auth", self.auth)
        app.router.add_get("/api/{tail:.*}", self.api)
        return app


async def make_client(server, *, credentials=True, api_key="stale-token"):
    client = YaroomsClient(api_key=api_key, base_url=str(server.make_url("")))
    if credentials:
        client._auth_email = "bot@example.test"
        client._auth_password = "secret"
    return client


@pytest.mark.asyncio
async def test_stale_token_answered_with_500_is_refreshed_and_request_succeeds():
    fake = FakeYarooms()
    async with TestServer(fake.app()) as server:
        client = await make_client(server)
        try:
            assert await client._request("GET", "/api/bookings") == BOOKINGS
        finally:
            await client.close()
    assert fake.auth_calls == 1
    assert fake.seen_tokens == ["stale-token", "fresh-token"]


@pytest.mark.asyncio
async def test_stale_token_answered_with_401_is_refreshed_and_request_succeeds():
    fake = FakeYarooms(stale_status=401)
    async with TestServer(fake.app()) as server:
        client = await make_client(server)
        try:
            assert await client._request("GET", "/api/bookings") == BOOKINGS
        finally:
            await client.close()
    assert fake.seen_tokens[-1] == "fresh-token"


@pytest.mark.asyncio
async def test_parallel_requests_with_a_stale_token_reauth_only_once():
    fake = FakeYarooms()
    async with TestServer(fake.app()) as server:
        client = await make_client(server)
        try:
            results = await asyncio.gather(
                *[client._request("GET", f"/api/bookings?space_id={i}") for i in range(8)]
            )
        finally:
            await client.close()
    assert results == [BOOKINGS] * 8
    assert fake.auth_calls == 1


@pytest.mark.asyncio
async def test_one_failing_request_does_not_break_parallel_ones():
    fake = FakeYarooms()
    fake.always_500_paths.add("/api/broken")
    async with TestServer(fake.app()) as server:
        client = await make_client(server, api_key="fresh-token")
        try:
            results = await asyncio.gather(
                client._request("GET", "/api/broken"),
                *[client._request("GET", "/api/bookings") for _ in range(7)],
                return_exceptions=True,
            )
        finally:
            await client.close()
    assert isinstance(results[0], ClientResponseError)
    assert results[1:] == [BOOKINGS] * 7


@pytest.mark.asyncio
async def test_persistent_5xx_does_not_reauth_again_within_cooldown():
    fake = FakeYarooms()
    fake.always_500_paths.add("/api/broken")
    async with TestServer(fake.app()) as server:
        client = await make_client(server)
        try:
            for _ in range(3):
                with pytest.raises(ClientResponseError):
                    await client._request("GET", "/api/broken")
        finally:
            await client.close()
    assert fake.auth_calls == 1


@pytest.mark.asyncio
async def test_static_api_key_mode_surfaces_500_without_reauth():
    fake = FakeYarooms()
    async with TestServer(fake.app()) as server:
        client = await make_client(server, credentials=False)
        try:
            with pytest.raises(ClientResponseError) as exc:
                await client._request("GET", "/api/bookings")
        finally:
            await client.close()
    assert exc.value.status == 500
    assert fake.auth_calls == 0
