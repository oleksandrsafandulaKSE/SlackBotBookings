"""Behaviour of the room list when a room is decommissioned in Yarooms.

Single seam: the ``YaroomsClient`` public surface with ``_request`` stubbed.
A room disappearing is expressed as a change in the stubbed ``/api/spaces``
response between two calls — exactly the real-world sequence.
"""

import pytest

from clients.yarooms_client import YaroomsClient
from handlers.home_common import is_room_gone

SKYPE_01 = {"id": "sk-01", "name": "Skype-room 0.1"}
SKYPE_03 = {"id": "sk-03", "name": "Skype-room 0.3"}
SILENT_BOX = {"id": "sb-1", "name": "Silent Box 1"}
MEETING_ROOM = {"id": "mr-1", "name": "Large Meeting Room"}


def make_client(space_pages):
    """Client whose /api/spaces returns each page in turn (last one repeats).

    A page may be an exception instance, which is raised instead.
    """
    client = YaroomsClient(api_key="test-token", base_url="https://example.test")
    pages = list(space_pages)
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path))
        page = pages[0] if len(pages) == 1 else pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page

    client._request = fake_request  # type: ignore[method-assign]
    client.spaces_calls = calls  # type: ignore[attr-defined]
    return client


@pytest.mark.asyncio
async def test_only_skype_rooms_and_silent_boxes_are_offered():
    client = make_client([[SKYPE_03, SILENT_BOX, MEETING_ROOM]])

    names = [s["name"] for s in await client.get_spaces_cached()]

    assert names == ["Skype-room 0.3", "Silent Box 1"]


@pytest.mark.asyncio
async def test_live_room_is_reported_live_without_extra_request():
    client = make_client([[SKYPE_03, SILENT_BOX]])
    await client.get_spaces_cached()
    calls_before = len(client.spaces_calls)

    assert await client.check_space_live("sk-03") == "live"
    assert len(client.spaces_calls) == calls_before, "happy path must not re-fetch"


@pytest.mark.asyncio
async def test_decommissioned_room_is_reported_gone_once_it_leaves_the_cache():
    # Nothing cached yet: the first list Yarooms serves no longer has 0.1.
    client = make_client([[SKYPE_03]])

    assert await client.check_space_live("sk-01") == "gone"


@pytest.mark.asyncio
async def test_room_still_inside_the_cache_window_is_caught_by_a_forced_check():
    """The reported bug: 0.1 is gone upstream but still cached, so a booking
    fails. A forced check must diagnose it rather than trusting the cache."""
    client = make_client([[SKYPE_01, SKYPE_03], [SKYPE_03]])
    listed = await client.get_spaces_cached()
    assert any(s["id"] == "sk-01" for s in listed), "0.1 starts out cached"

    assert await client.check_space_live("sk-01") == "live", "cached fast path"
    assert await client.check_space_live("sk-01", force=True) == "gone"


@pytest.mark.asyncio
async def test_detecting_a_gone_room_clears_the_cache():
    client = make_client([[SKYPE_01, SKYPE_03], [SKYPE_03]])
    await client.get_spaces_cached()

    await client.check_space_live("sk-01", force=True)

    assert client.get_spaces_cache_meta()["state"] == "empty"


@pytest.mark.asyncio
async def test_gone_room_disappears_from_the_room_list():
    client = make_client([[SKYPE_01, SKYPE_03], [SKYPE_03]])
    await client.get_spaces_cached()

    await client.check_space_live("sk-01", force=True)
    names = [s["name"] for s in await client.get_spaces_cached()]

    assert names == ["Skype-room 0.3"]


@pytest.mark.asyncio
async def test_unreachable_yarooms_is_unknown_not_gone():
    client = make_client([RuntimeError("Yarooms down")])

    assert await client.check_space_live("sk-01") == "unknown"


@pytest.mark.asyncio
async def test_other_rooms_stay_bookable_when_one_is_removed():
    client = make_client([[SKYPE_01, SKYPE_03, SILENT_BOX], [SKYPE_03, SILENT_BOX]])
    await client.get_spaces_cached()
    await client.check_space_live("sk-01", force=True)

    assert await client.check_space_live("sk-03") == "live"
    assert await client.check_space_live("sb-1") == "live"


@pytest.mark.asyncio
async def test_booking_is_refused_for_a_gone_room():
    client = make_client([[SKYPE_03]])

    assert await is_room_gone(client, "sk-01", flow="test") is True


@pytest.mark.asyncio
async def test_failed_booking_on_a_still_cached_room_is_diagnosed_as_gone():
    client = make_client([[SKYPE_01, SKYPE_03], [SKYPE_03]])
    await client.get_spaces_cached()

    assert await is_room_gone(client, "sk-01", flow="test") is False, "cached"
    assert await is_room_gone(client, "sk-01", flow="test", force=True) is True


@pytest.mark.asyncio
async def test_booking_proceeds_for_a_live_room():
    client = make_client([[SKYPE_03]])

    assert await is_room_gone(client, "sk-03", flow="test") is False


@pytest.mark.asyncio
async def test_booking_fails_open_when_the_room_list_is_unverifiable():
    client = make_client([RuntimeError("Yarooms down")])

    assert await is_room_gone(client, "sk-03", flow="test") is False
    assert await is_room_gone(client, "sk-03", flow="test", force=True) is False


# ── Regression: Yarooms payloads do not always key the id as "id" ────────────

SKYPE_03_ALT = {"spaceId": "sk-03", "name": "Skype-room 0.3"}
SILENT_BOX_ALT = {"space_id": "sb-1", "name": "Silent Box 1"}


@pytest.mark.asyncio
async def test_live_room_keyed_as_spaceid_is_not_reported_gone():
    client = make_client([[SKYPE_03_ALT, SILENT_BOX_ALT]])

    assert await client.check_space_live("sk-03") == "live"
    assert await client.check_space_live("sk-03", force=True) == "live"
    assert await client.check_space_live("sb-1", force=True) == "live"


@pytest.mark.asyncio
async def test_booking_proceeds_for_a_live_room_keyed_as_spaceid():
    client = make_client([[SKYPE_03_ALT]])

    assert await is_room_gone(client, "sk-03", flow="test") is False
    assert await is_room_gone(client, "sk-03", flow="test", force=True) is False


@pytest.mark.asyncio
async def test_an_empty_room_list_is_unknown_not_gone():
    client = make_client([[]])

    assert await client.check_space_live("sk-03", force=True) == "unknown"
    assert await is_room_gone(client, "sk-03", flow="test", force=True) is False


@pytest.mark.asyncio
async def test_blank_room_id_is_never_judged_gone():
    client = make_client([[SKYPE_03]])

    assert await client.check_space_live("") == "unknown"
    assert await is_room_gone(client, "", flow="test") is False
