"""Rooms Yarooms still returns but that must not be bookable.

[0.1] and [0.2] Shelter Skype Room were decommissioned in the building but are
still live in the Yarooms API, so they are excluded by id via the
YAROOMS_EXCLUDED_SPACE_IDS environment variable.
"""

import pytest

from clients.yarooms_client import EXCLUDED_SPACE_IDS_ENV, YaroomsClient

# Real payload shape, taken from a live /api/spaces response.
SHELTER_01 = {"id": 1000020365, "name": "[0.1] Shelter Skype Room"}
SHELTER_02 = {"id": 1000020366, "name": "[0.2] Shelter Skype Room"}
SKYPE_112 = {"id": 1000015972, "name": "[1.12] Skype room"}
SILENT_BOX = {"id": 1000019282, "name": "Silent box 2-1"}
MEETING_ROOM = {"id": 1000000001, "name": "Large Meeting Room"}

ALL_SPACES = [SHELTER_01, SHELTER_02, SKYPE_112, SILENT_BOX, MEETING_ROOM]


def make_client(spaces):
    client = YaroomsClient(api_key="test-token", base_url="https://example.test")

    async def fake_request(method, path, **kwargs):
        return spaces

    client._request = fake_request  # type: ignore[method-assign]
    return client


@pytest.mark.asyncio
async def test_excluded_rooms_are_not_offered(monkeypatch):
    monkeypatch.setenv(EXCLUDED_SPACE_IDS_ENV, "1000020365,1000020366")
    client = make_client(ALL_SPACES)

    names = [s["name"] for s in await client.get_spaces()]

    assert names == ["[1.12] Skype room", "Silent box 2-1"]


@pytest.mark.asyncio
async def test_excluded_rooms_never_reach_the_cache(monkeypatch):
    monkeypatch.setenv(EXCLUDED_SPACE_IDS_ENV, "1000020365 1000020366")
    client = make_client(ALL_SPACES)

    cached = await client.get_spaces_cached()

    assert all("Shelter" not in s["name"] for s in cached)


@pytest.mark.asyncio
async def test_an_excluded_room_is_reported_gone(monkeypatch):
    """A stale modal booking an excluded room must be refused, not attempted."""
    monkeypatch.setenv(EXCLUDED_SPACE_IDS_ENV, "1000020365")
    client = make_client(ALL_SPACES)

    assert await client.check_space_live("1000020365") == "gone"


@pytest.mark.asyncio
async def test_other_rooms_are_unaffected(monkeypatch):
    monkeypatch.setenv(EXCLUDED_SPACE_IDS_ENV, "1000020365,1000020366")
    client = make_client(ALL_SPACES)

    assert await client.check_space_live("1000015972") == "live"
    assert await client.check_space_live("1000019282") == "live"


@pytest.mark.asyncio
async def test_no_exclusions_configured_keeps_every_target_room(monkeypatch):
    monkeypatch.delenv(EXCLUDED_SPACE_IDS_ENV, raising=False)
    client = make_client(ALL_SPACES)

    names = [s["name"] for s in await client.get_spaces()]

    assert names == [
        "[0.1] Shelter Skype Room",
        "[0.2] Shelter Skype Room",
        "[1.12] Skype room",
        "Silent box 2-1",
    ]


@pytest.mark.asyncio
async def test_blank_and_malformed_values_exclude_nothing(monkeypatch):
    for raw in ("", "   ", ",,,"):
        monkeypatch.setenv(EXCLUDED_SPACE_IDS_ENV, raw)
        client = make_client(ALL_SPACES)

        assert len(await client.get_spaces()) == 4, f"raw={raw!r}"
