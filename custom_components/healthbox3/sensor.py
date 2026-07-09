"""Sensor platform for the Renson Healthbox 3 integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfRatio, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import Room, Sensor
from .const import (
    SENSOR_TYPE_AQI,
    SENSOR_TYPE_CO2,
    SENSOR_TYPE_GLOBAL_AQI,
    SENSOR_TYPE_HUMIDITY,
    SENSOR_TYPE_TEMPERATURE,
    SENSOR_TYPE_VOC,
)
from .coordinator import Healthbox3ConfigEntry, Healthbox3DataUpdateCoordinator
from .entity import Healthbox3Entity

# Entities only read from the coordinator; the coordinator itself
# serializes the actual device polling, so there's nothing for per-entity
# parallel updates to limit.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class RoomSensorMeta:
    """Presentation metadata for a room sensor type.

    `parameter_keys` lists candidate parameter names in priority order: the
    real device (firmware 2.6.9) and the Renson PDF examples disagree on
    which sub-key holds a VOC sensor's headline value (`concentration` vs
    `voc_calc_embedded`), so we try known candidates instead of hardcoding
    a single one.
    """

    translation_key: str
    parameter_keys: tuple[str, ...]
    device_class: SensorDeviceClass | None
    native_unit_of_measurement: str | None
    suggested_display_precision: int


ROOM_SENSOR_META: dict[str, RoomSensorMeta] = {
    SENSOR_TYPE_TEMPERATURE: RoomSensorMeta(
        translation_key="room_temperature",
        parameter_keys=("temperature",),
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    SENSOR_TYPE_HUMIDITY: RoomSensorMeta(
        translation_key="room_humidity",
        parameter_keys=("humidity",),
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    SENSOR_TYPE_CO2: RoomSensorMeta(
        translation_key="room_co2",
        parameter_keys=("concentration",),
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        suggested_display_precision=0,
    ),
    SENSOR_TYPE_VOC: RoomSensorMeta(
        translation_key="room_voc",
        parameter_keys=("concentration", "voc_calc_embedded"),
        device_class=None,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        suggested_display_precision=0,
    ),
    SENSOR_TYPE_AQI: RoomSensorMeta(
        translation_key="room_aqi",
        parameter_keys=("index",),
        device_class=None,
        native_unit_of_measurement=None,
        suggested_display_precision=1,
    ),
}

_GLOBAL_AQI_DISPLAY_PRECISION = 1
_AIRFLOW_DISPLAY_PRECISION = 0


def _as_float(value: bool | float | str | None) -> float | None:
    """Narrow a Parameter's value to a float, or None if it isn't one.

    Parameter.value is a bool/float/str/None union covering every
    parameter type across the whole API - real hardware has only ever
    sent a float for nominal/flow_rate specifically, but nothing in the
    schema actually guarantees that. A graceful "treat it as not
    reporting" fallback here, not a silent cast, matches how an empty/
    unexpected CO2 reading is already treated as unavailable rather than
    crashing - this project has been burned by "trust the device"
    assumptions before (the profile index's cross-firmware convention
    change, boost's restart-not-adjust behavior), so a real, if currently
    theoretical, type mismatch here is worth handling the same way.
    """
    return value if isinstance(value, float) else None


def _room_nominal_flow(room: Room) -> float | None:
    """Return a room's nominal (rated reference) flow rate in m3/h."""
    param = room.parameters.get("nominal")
    return _as_float(param.value) if param is not None else None


def _room_current_flow_rate(room: Room) -> float | None:
    """Return a room's current live flow rate in m3/h.

    Sums flow_rate across every actuator that reports one. Both real
    fixtures only ever have a single air-valve actuator per room, but the
    API schema allows more than one (Room.actuators is a list) and
    `nominal` is scoped to the whole room rather than a specific valve -
    so if a room is ever fed by more than one valve, this combines their
    live flow rates against that single room-level reference instead of
    silently reading only the first one found. An actuator reporting a
    non-numeric flow_rate is treated the same as one not reporting it at
    all - skipped, not a reason to fail the whole room's reading.
    """
    rates: list[float] = []
    for actuator in room.actuators:
        parameter = actuator.parameters.get("flow_rate")
        if parameter is None:
            continue
        rate = _as_float(parameter.value)
        if rate is not None:
            rates.append(rate)
    if not rates:
        return None
    return sum(rates)


def _room_airflow_percentage(room: Room) -> float | None:
    """Return a room's current flow rate as a percentage of nominal.

    Not a 0-100 bounded value: boost can drive live flow well past
    nominal (the boost API's own level field goes up to 200%), and
    there's a nonzero floor even at rest - real-world values run roughly
    10-200%, not 0-100.
    """
    nominal = _room_nominal_flow(room)
    flow_rate = _room_current_flow_rate(room)
    if not nominal or flow_rate is None:
        return None
    return flow_rate / nominal * 100


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Healthbox3ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Healthbox 3 sensors from a config entry."""
    coordinator = entry.runtime_data
    serial = coordinator.data.healthbox.serial

    entities: list[Healthbox3Entity] = []
    for room in coordinator.data.healthbox.rooms:
        for sensor in room.sensors:
            meta = ROOM_SENSOR_META.get(sensor.type)
            if meta is None:
                continue
            entities.append(
                Healthbox3RoomSensor(coordinator, serial, room.id, room.name, sensor.type, meta)
            )
        if _room_airflow_percentage(room) is not None:
            entities.append(
                Healthbox3RoomAirflowSensor(coordinator, serial, room.id, room.name)
            )

    if any(s.type == SENSOR_TYPE_GLOBAL_AQI for s in coordinator.data.healthbox.global_sensors):
        entities.append(Healthbox3GlobalAqiSensor(coordinator, serial))

    if coordinator.use_v2:
        entities.append(Healthbox3GlobalVentilationLevelSensor(coordinator, serial))

    async_add_entities(entities)


class Healthbox3RoomSensor(Healthbox3Entity, SensorEntity):
    """A single sensor (temperature/humidity/CO2/VOC/AQI) within a room."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: Healthbox3DataUpdateCoordinator,
        serial: str,
        room_id: int,
        room_name: str,
        sensor_type: str,
        meta: RoomSensorMeta,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, serial)
        self._room_id = room_id
        self._sensor_type = sensor_type
        self._meta = meta
        self._attr_translation_key = meta.translation_key
        self._attr_translation_placeholders = {"room_name": room_name}
        self._attr_device_class = meta.device_class
        self._attr_native_unit_of_measurement = meta.native_unit_of_measurement
        self._attr_suggested_display_precision = meta.suggested_display_precision
        self._attr_unique_id = f"{serial}_room{room_id}_{meta.translation_key}"

    def _find_sensor(self) -> Sensor | None:
        room = next(
            (r for r in self.coordinator.data.healthbox.rooms if r.id == self._room_id),
            None,
        )
        if room is None:
            return None
        return next((s for s in room.sensors if s.type == self._sensor_type), None)

    @property
    @override
    def available(self) -> bool:
        """Return whether the sensor is reporting data.

        A sensor with an empty `parameter` dict (confirmed on real
        hardware for a CO2 sensor) is not-yet-reporting, not an error.
        """
        if not super().available:
            return False
        sensor = self._find_sensor()
        return sensor is not None and sensor.is_available

    @property
    @override
    def native_value(self) -> bool | float | str | None:
        """Return the sensor's current value."""
        sensor = self._find_sensor()
        if sensor is None:
            return None
        for key in self._meta.parameter_keys:
            if key in sensor.parameters:
                return sensor.parameters[key].value
        return None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return the main pollutant, for the AQI sensor only."""
        if self._sensor_type != SENSOR_TYPE_AQI:
            return None
        sensor = self._find_sensor()
        if sensor is None:
            return None
        main_pollutant = sensor.parameters.get("main_pollutant")
        if main_pollutant is None or not main_pollutant.value:
            return None
        return {"main_pollutant": str(main_pollutant.value)}


class Healthbox3RoomAirflowSensor(Healthbox3Entity, SensorEntity):
    """A room's current airflow, as a percentage of its valve's nominal
    (rated reference) flow rate - not a 0-100 bounded value, see
    `_room_airflow_percentage`.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "room_airflow"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = _AIRFLOW_DISPLAY_PRECISION

    def __init__(
        self,
        coordinator: Healthbox3DataUpdateCoordinator,
        serial: str,
        room_id: int,
        room_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, serial)
        self._room_id = room_id
        self._attr_translation_placeholders = {"room_name": room_name}
        self._attr_unique_id = f"{serial}_room{room_id}_airflow"

    def _find_room(self) -> Room | None:
        return next(
            (r for r in self.coordinator.data.healthbox.rooms if r.id == self._room_id),
            None,
        )

    @property
    @override
    def available(self) -> bool:
        """Return whether this room currently reports both flow_rate and nominal."""
        if not super().available:
            return False
        room = self._find_room()
        return room is not None and _room_airflow_percentage(room) is not None

    @property
    @override
    def native_value(self) -> float | None:
        """Return current flow rate as a percentage of nominal."""
        room = self._find_room()
        if room is None:
            return None
        return _room_airflow_percentage(room)


class Healthbox3GlobalAqiSensor(Healthbox3Entity, SensorEntity):
    """The whole-house air quality index sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "global_aqi"
    _attr_suggested_display_precision = _GLOBAL_AQI_DISPLAY_PRECISION

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_global_aqi"

    def _find_sensor(self) -> Sensor | None:
        return next(
            (
                s
                for s in self.coordinator.data.healthbox.global_sensors
                if s.type == SENSOR_TYPE_GLOBAL_AQI
            ),
            None,
        )

    @property
    @override
    def available(self) -> bool:
        """Return whether the global AQI sensor is reporting data."""
        if not super().available:
            return False
        sensor = self._find_sensor()
        return sensor is not None and sensor.is_available

    @property
    @override
    def native_value(self) -> bool | float | str | None:
        """Return the global AQI value."""
        sensor = self._find_sensor()
        if sensor is None or "index" not in sensor.parameters:
            return None
        return sensor.parameters["index"].value

    @property
    @override
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return the main pollutant and the room it was measured in."""
        sensor = self._find_sensor()
        if sensor is None:
            return None
        attributes = {}
        for key in ("main_pollutant", "room"):
            parameter = sensor.parameters.get(key)
            if parameter is not None and parameter.value:
                attributes[key] = str(parameter.value)
        return attributes or None


class Healthbox3GlobalVentilationLevelSensor(Healthbox3Entity, SensorEntity):
    """The whole-house current ventilation level, as a percentage.

    Distinct from the `Minimum ventilation level` number entity (the
    configured floor): this is the live aggregate figure, the whole-house
    counterpart to each room's airflow sensor. Not necessarily 0-100
    bounded - same reasoning as the per-room airflow sensor, so
    device_class is left unset (none of the built-in SensorDeviceClass
    members that accept a percentage unit fit a ventilation-level
    reading regardless of its bounds).
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "global_ventilation_level"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = _AIRFLOW_DISPLAY_PRECISION

    def __init__(
        self, coordinator: Healthbox3DataUpdateCoordinator, serial: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_global_ventilation_level"

    @property
    @override
    def available(self) -> bool:
        """Return whether the device's decision data is known."""
        return super().available and self.coordinator.data.decision is not None

    @property
    @override
    def native_value(self) -> float | None:
        """Return the current whole-house ventilation level."""
        decision = self.coordinator.data.decision
        return decision.global_ventilation_level if decision is not None else None
