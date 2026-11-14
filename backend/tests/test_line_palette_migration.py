"""Reordering the line palette keeps every existing network in the colour it had (migration step)."""

import json

import pytest
from sqlalchemy import select

import app.database.migrations as migrations
from app.models.network import Subnet
from app.models.setting import Setting


async def _line_colours(db) -> dict | None:
    row = (await db.execute(select(Setting).where(Setting.key == "ui.line_colors"))).scalar_one_or_none()
    return None if row is None else json.loads(row.value)


async def _marker(db) -> Setting | None:
    return (await db.execute(select(Setting).where(Setting.key == migrations.LINE_PALETTE_MARKER))).scalar_one_or_none()


def _subnets(*ids: int) -> list[Subnet]:
    return [Subnet(id=i, cidr=f"10.{i}.0.0/24", name=f"Net {i}") for i in ids]


def test_every_old_slot_has_a_new_one():
    assert sorted(migrations.LINE_SLOT_MOVES) == list(range(1, 11))
    assert sorted(migrations.LINE_SLOT_MOVES.values()) == list(range(1, 11))


@pytest.mark.parametrize("subnet_id, old", [(1, 1), (2, 2), (10, 10), (11, 1), (13, 3), (20, 10)])
def test_old_slot_matches_network_color(subnet_id, old):
    assert migrations._old_line_slot(subnet_id) == old


def test_pinning_keeps_own_colours_and_skips_unmoved_slots():
    pinned = migrations.pinned_line_colours([1, 2, 3, 4, 10, 11], {"4": "#123456"})
    # 1 and 11 were teal (old slot 1, now 8), 3 was blue (now 9); 2 and 10 did not move; 4 has its own colour
    assert pinned == {"1": "line:8", "3": "line:9", "4": "#123456", "11": "line:8"}


async def test_existing_networks_keep_their_colour(db):
    db.add_all(_subnets(1, 2, 3))
    db.add(Setting(key="ui.line_colors", value=json.dumps({"2": "#abcdef"}), category="ui"))
    await db.commit()

    await migrations._pin_line_colours_to_reordered_palette(db)

    assert await _line_colours(db) == {"2": "#abcdef", "1": "line:8", "3": "line:9"}
    marker = await _marker(db)
    assert (marker.value, marker.category) == ("true", "system")


async def test_networks_without_a_colour_setting_get_one(db):
    db.add_all(_subnets(1))
    await db.commit()

    await migrations._pin_line_colours_to_reordered_palette(db)

    assert await _line_colours(db) == {"1": "line:8"}


async def test_a_fresh_database_only_gets_the_marker(db):
    await migrations._pin_line_colours_to_reordered_palette(db)

    assert await _line_colours(db) is None
    assert await _marker(db) is not None


async def test_it_runs_only_once(db):
    await migrations._pin_line_colours_to_reordered_palette(db)
    db.add_all(_subnets(1))  # a network added after the reorder starts in the new order
    await db.commit()

    await migrations._pin_line_colours_to_reordered_palette(db)

    assert await _line_colours(db) is None


async def test_an_unreadable_colour_setting_is_replaced(db):
    db.add_all(_subnets(1))
    db.add(Setting(key="ui.line_colors", value="not json", category="ui"))
    await db.commit()

    await migrations._pin_line_colours_to_reordered_palette(db)

    assert await _line_colours(db) == {"1": "line:8"}
