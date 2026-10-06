"""Device layout: the unit is one device, and each ventilated room is its own
device linked to it by `via_device_id`.

Covers a fresh install and the upgrade from the single-device layout that
earlier releases created. On upgrade, entity IDs must not change: only the
device each entity belongs to moves.
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.healthbox3.const import DOMAIN

from .conftest import make_config_entry, setup_integration

_PREFIX = "healthbox_3_0"


def _device_with_identifier(registry: dr.DeviceRegistry, identifier: tuple[str, str]):
    return next(iter(registry.async_get_devices(identifiers={identifier})), None)


def _room_device(registry: dr.DeviceRegistry, serial: str, room_id: int):
    return _device_with_identifier(registry, (DOMAIN, f"{serial}_room{room_id}"))


def _unit_device(registry: dr.DeviceRegistry, serial: str):
    return _device_with_identifier(registry, (DOMAIN, serial))


async def test_fresh_install_puts_each_room_on_its_own_device(
    hass, mock_api_client, v1_data, boost_status
):
    await setup_integration(
        hass,
        mock_api_client,
        serial=v1_data.serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    devices = dr.async_get(hass)
    unit = _unit_device(devices, v1_data.serial)
    room = _room_device(devices, v1_data.serial, v1_data.rooms[0].id)
    assert unit is not None
    assert room is not None
    assert room.via_device_id == unit.id
    assert room.name == v1_data.rooms[0].name

    # A new install gets the shorter entity ID, since the room is now the device.
    entry = er.async_get(hass).async_get("fan.toilet_boost")
    assert entry is not None
    assert entry.device_id == room.id
    # The device supplies the room name, so the friendly name is unchanged.
    assert hass.states.get("fan.toilet_boost").attributes["friendly_name"] == "Toilet Boost"


async def test_upgrade_moves_room_entities_to_room_devices_and_keeps_entity_ids(
    hass, mock_api_client, v1_data, boost_status
):
    serial = v1_data.serial
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    # State as the single-device release left it: the unit device owns the
    # room's boost entity, under the same unique_id the current code uses.
    old_config_entry = make_config_entry(hass, serial=serial, api_key=None)
    old_unit = devices.async_get_or_create(
        config_entry_id=old_config_entry.entry_id,
        identifiers={(DOMAIN, serial)},
        manufacturer="Renson",
        model="Healthbox 3.0",
        name="Healthbox 3.0",
    )
    old_entry = entities.async_get_or_create(
        "fan",
        DOMAIN,
        f"{serial}_room1_boost",
        suggested_object_id=f"{_PREFIX}_toilet_boost",
        device_id=old_unit.id,
    )
    assert old_entry.entity_id == f"fan.{_PREFIX}_toilet_boost"

    await setup_integration(
        hass,
        mock_api_client,
        serial=serial,
        api_key=None,
        healthbox_data=v1_data,
        boost_status=boost_status,
    )

    room = _room_device(devices, serial, v1_data.rooms[0].id)
    unit = _unit_device(devices, serial)
    assert room is not None
    assert room.via_device_id == unit.id

    migrated = entities.async_get(f"fan.{_PREFIX}_toilet_boost")
    assert migrated is not None
    assert migrated.unique_id == f"{serial}_room1_boost"
    assert migrated.device_id == room.id
