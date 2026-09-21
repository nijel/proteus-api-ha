"""Proteus API integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONSUMPTION_KWH,
    ATTR_PREDICTIONS,
    ATTR_PRODUCTION_KWH,
    ATTR_TIME,
    ATTR_TIMES,
    DOMAIN,
    SERVICE_CLEAR_PLAN_STEPS,
    SERVICE_CLEAR_PREDICTIONS,
    SERVICE_SET_PLAN_STEPS,
    SERVICE_SET_PREDICTIONS,
    UPDATE_INTERVAL,
    normalize_email,
)
from .plan import BATTERY_STATES, PV_STATES, validate_soc, validate_times
from .proteus_api import AuthenticationError, ProteusAPI, ProteusConnectionError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]


def _validate_hour(value: Any) -> Any:
    """Parse a local or offset timestamp and require an hourly UTC boundary."""
    parsed = cv.datetime(value)
    try:
        validate_times([dt_util.as_utc(parsed)])
    except ValueError as err:
        raise vol.Invalid(str(err)) from err
    return parsed


def _unique_hours(values: list[Any]) -> list[Any]:
    """Reject duplicate hours, including timestamps with different UTC offsets."""
    times = [item[ATTR_TIME] if isinstance(item, dict) else item for item in values]
    try:
        validate_times([dt_util.as_utc(value) for value in times])
    except ValueError as err:
        raise vol.Invalid(str(err)) from err
    return values


def _soc(value: Any) -> Any:
    """Validate a target percentage without accepting booleans or nonfinite values."""
    try:
        validate_soc(value)
    except ValueError as err:
        raise vol.Invalid(str(err)) from err
    return value


def _has_step_change(value: dict[str, Any]) -> dict[str, Any]:
    """Require an actual action field alongside the time."""
    if len(value) < 2:
        raise vol.Invalid("Each step requires at least one change")
    return value


def _has_prediction_value(prediction: dict[str, Any]) -> dict[str, Any]:
    """Require at least one of consumption or production to be set."""
    if (
        prediction.get(ATTR_CONSUMPTION_KWH) is None
        and prediction.get(ATTR_PRODUCTION_KWH) is None
    ):
        raise vol.Invalid(
            f"at least one of {ATTR_CONSUMPTION_KWH} or {ATTR_PRODUCTION_KWH} "
            "is required; use clear_predictions to remove an override"
        )
    return prediction


PREDICTION_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_TIME): _validate_hour,
            vol.Optional(ATTR_CONSUMPTION_KWH): vol.Any(None, vol.Coerce(float)),
            vol.Optional(ATTR_PRODUCTION_KWH): vol.Any(None, vol.Coerce(float)),
        }
    ),
    _has_prediction_value,
)

TARGET_SCHEMA = {
    vol.Optional(ATTR_DEVICE_ID): cv.ensure_list,
    vol.Optional(ATTR_ENTITY_ID): cv.ensure_list,
}

SET_PREDICTIONS_SCHEMA = vol.Schema(
    {
        **TARGET_SCHEMA,
        vol.Required(ATTR_PREDICTIONS): vol.All(
            cv.ensure_list,
            [PREDICTION_SCHEMA],
            vol.Length(min=1, max=96),
            _unique_hours,
        ),
    }
)

CLEAR_PREDICTIONS_SCHEMA = vol.Schema(
    {
        **TARGET_SCHEMA,
        vol.Required(ATTR_TIMES): vol.All(
            cv.ensure_list, [_validate_hour], vol.Length(min=1, max=96), _unique_hours
        ),
    }
)


PLAN_STEP_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_TIME): _validate_hour,
            vol.Optional("flexalgo_battery"): vol.In(BATTERY_STATES),
            vol.Optional("flexalgo_pv"): vol.In(PV_STATES),
            vol.Optional("target_soc"): _soc,
            vol.Optional("is_manually_locked"): bool,
        }
    ),
    _has_step_change,
)
SET_PLAN_STEPS_SCHEMA = vol.Schema(
    {
        **TARGET_SCHEMA,
        vol.Required("steps"): vol.All(
            cv.ensure_list, [PLAN_STEP_SCHEMA], vol.Length(min=1), _unique_hours
        ),
    }
)
CLEAR_PLAN_STEPS_SCHEMA = vol.Schema(
    {
        **TARGET_SCHEMA,
        vol.Required(ATTR_TIMES): vol.All(
            cv.ensure_list, [_validate_hour], vol.Length(min=1), _unique_hours
        ),
    }
)


@callback
def _async_remove_stale_devices(
    hass: HomeAssistant, entry: ConfigEntry, current_inverter_ids: set[str]
) -> None:
    """Remove orphaned Proteus devices left behind by older installs."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    for device_entry in dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    ):
        proteus_ids = {
            identifier
            for domain, identifier in device_entry.identifiers
            if domain == DOMAIN
        }
        if not proteus_ids:
            continue
        if proteus_ids & current_inverter_ids:
            continue
        if er.async_entries_for_device(
            entity_registry,
            device_entry.id,
            include_disabled_entities=True,
        ):
            continue

        _LOGGER.info(
            "Removing stale device entry %s for missing inverter identifiers %s",
            device_entry.id,
            sorted(proteus_ids),
        )
        device_registry.async_remove_device(device_entry.id)


@callback
def _async_get_target_inverter_ids(
    hass: HomeAssistant, call: ServiceCall
) -> set[str] | None:
    """Return the inverter IDs a service call targets, or None for all of them."""
    device_ids = set(call.data.get(ATTR_DEVICE_ID, []))
    entity_ids = call.data.get(ATTR_ENTITY_ID, [])
    if not device_ids and not entity_ids:
        return None

    entity_registry = er.async_get(hass)
    for entity_id in entity_ids:
        entity_entry = entity_registry.async_get(entity_id)
        if entity_entry is not None and entity_entry.device_id is not None:
            device_ids.add(entity_entry.device_id)

    device_registry = dr.async_get(hass)
    inverter_ids = set()
    for device_id in device_ids:
        device_entry = device_registry.async_get(device_id)
        if device_entry is None:
            continue
        inverter_ids.update(
            identifier
            for domain, identifier in device_entry.identifiers
            if domain == DOMAIN
        )

    return inverter_ids


@callback
def _async_get_target_apis(
    hass: HomeAssistant, call: ServiceCall
) -> list[tuple[str, ProteusAPI]]:
    """Resolve a service call to the API clients it should run against."""
    target_inverter_ids = _async_get_target_inverter_ids(hass, call)

    apis = [
        (inverter_id, inverter_info["api"])
        for entry_data in hass.data.get(DOMAIN, {}).values()
        for inverter_id, inverter_info in entry_data["inverters"].items()
        if target_inverter_ids is None or inverter_id in target_inverter_ids
    ]

    if not apis:
        raise ServiceValidationError(
            "No Proteus inverter matched the service call target"
        )

    return apis


async def _async_refresh_written_plan(hass: HomeAssistant, api: ProteusAPI) -> None:
    """Publish refreshed plans for the target and known household peers."""
    for entry_data in hass.data.get(DOMAIN, {}).values():
        for info in entry_data["inverters"].values():
            other = info["api"]
            if other is api or api.shares_household(other):
                other.request_plan_refresh()
                await info["coordinator"].async_request_refresh()


async def _async_plan_steps(
    hass: HomeAssistant, call: ServiceCall, *, clear: bool = False
) -> None:
    """Apply or reset explicitly targeted hours in one household plan."""
    if not call.data.get(ATTR_DEVICE_ID) and not call.data.get(ATTR_ENTITY_ID):
        raise ServiceValidationError("Select exactly one Proteus inverter")
    apis = _async_get_target_apis(hass, call)
    if len(apis) != 1:
        raise ServiceValidationError("Select exactly one Proteus inverter")
    _, api = apis[0]
    changes = (
        [{"time": dt_util.as_utc(value)} for value in call.data[ATTR_TIMES]]
        if clear
        else [
            {**item, "time": dt_util.as_utc(item[ATTR_TIME])}
            for item in call.data["steps"]
        ]
    )
    try:
        await api.update_plan_steps(changes, clear=clear)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
    except ProteusConnectionError as err:
        raise HomeAssistantError(str(err)) from err
    finally:
        if api.plan_refresh_pending:
            await _async_refresh_written_plan(hass, api)


async def _async_set_predictions(hass: HomeAssistant, call: ServiceCall) -> None:
    """Override predicted consumption and/or production in Proteus.

    A quantity left out of an item is sent as null, so Proteus keeps its own
    prediction for it.
    """
    predictions = [
        {
            "time": dt_util.as_utc(prediction[ATTR_TIME]),
            "consumption_kwh": prediction.get(ATTR_CONSUMPTION_KWH),
            "production_kwh": prediction.get(ATTR_PRODUCTION_KWH),
        }
        for prediction in call.data[ATTR_PREDICTIONS]
    ]

    for inverter_id, api in _async_get_target_apis(hass, call):
        success = await api.upsert_prediction_overrides(predictions)
        if api.plan_refresh_pending:
            await _async_refresh_written_plan(hass, api)
        if not success:
            raise HomeAssistantError(
                api.last_write_error
                or f"Failed to override predictions for inverter {inverter_id}"
            )


async def _async_clear_predictions(hass: HomeAssistant, call: ServiceCall) -> None:
    """Remove prediction overrides so Proteus uses its own predictions again."""
    times = [dt_util.as_utc(time) for time in call.data[ATTR_TIMES]]

    for inverter_id, api in _async_get_target_apis(hass, call):
        success = await api.clear_prediction_overrides(times)
        if api.plan_refresh_pending:
            await _async_refresh_written_plan(hass, api)
        if not success:
            raise HomeAssistantError(
                api.last_write_error
                or f"Failed to clear predictions for inverter {inverter_id}"
            )


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration-wide services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_PREDICTIONS):
        return

    async def handle_set_predictions(call: ServiceCall) -> None:
        """Handle the set_predictions service call."""
        await _async_set_predictions(hass, call)

    async def handle_clear_predictions(call: ServiceCall) -> None:
        """Handle the clear_predictions service call."""
        await _async_clear_predictions(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PREDICTIONS,
        handle_set_predictions,
        schema=SET_PREDICTIONS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_PREDICTIONS,
        handle_clear_predictions,
        schema=CLEAR_PREDICTIONS_SCHEMA,
    )

    async def handle_set_plan_steps(call: ServiceCall) -> None:
        """Handle edits to a household schedule."""
        await _async_plan_steps(hass, call)

    async def handle_clear_plan_steps(call: ServiceCall) -> None:
        """Handle resetting manually edited hours."""
        await _async_plan_steps(hass, call, clear=True)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PLAN_STEPS,
        handle_set_plan_steps,
        schema=SET_PLAN_STEPS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_PLAN_STEPS,
        handle_clear_plan_steps,
        schema=CLEAR_PLAN_STEPS_SCHEMA,
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy single-inverter config entries to the account-wide format."""
    if entry.version >= 2:
        return True

    _LOGGER.info(
        "Migrating config entry %s from version %s", entry.entry_id, entry.version
    )

    if "inverter_id" not in entry.data:
        hass.config_entries.async_update_entry(entry, version=2)
        return True

    normalized_email = normalize_email(entry.data["email"])

    for other_entry in hass.config_entries.async_entries(DOMAIN):
        if other_entry.entry_id == entry.entry_id:
            continue

        if normalize_email(other_entry.data.get("email", "")) != normalized_email:
            continue

        _LOGGER.info(
            "Removing duplicate legacy config entry %s for account %s during migration",
            entry.entry_id,
            entry.data["email"],
        )
        await hass.config_entries.async_remove(entry.entry_id)
        return False

    hass.config_entries.async_update_entry(
        entry,
        data={
            "email": entry.data["email"],
            "password": entry.data["password"],
        },
        title=f"Proteus API ({entry.data['email']})",
        unique_id=normalized_email,
        version=2,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Proteus API from a config entry."""
    email = entry.data["email"]
    password = entry.data["password"]

    # Empty string for inverter_id is acceptable here as we only need to
    # authenticate and fetch the list of available inverters.
    temp_api = ProteusAPI("", email, password)
    try:
        inverters = await temp_api.fetch_inverters()
    except AuthenticationError as ex:
        _LOGGER.error("Authentication failed: %s", ex)
        raise ConfigEntryAuthFailed(f"Authentication failed: {ex}") from ex
    except (ConnectionError, aiohttp.ClientError, TimeoutError) as ex:
        _LOGGER.error("Failed to fetch inverters: %s", ex)
        raise ConfigEntryNotReady(f"Failed to fetch inverters: {ex}") from ex
    finally:
        await temp_api.close()

    if not inverters:
        _LOGGER.warning("No inverters found for account %s", email)
        raise ConfigEntryNotReady(
            "No inverters found for this account. Please check your account status."
        )

    inverter_data = {}
    created_apis: dict[str, ProteusAPI] = {}
    try:
        for inverter in inverters:
            inverter_id = inverter["id"]
            _LOGGER.info(
                "Setting up inverter %s (%s)",
                inverter_id,
                inverter.get("vendor", "Unknown"),
            )

            api = ProteusAPI(inverter_id, email, password)
            created_apis[inverter_id] = api
            coordinator = ProteusDataUpdateCoordinator(
                hass,
                _LOGGER,
                name=f"proteus_api_{inverter_id}",
                update_method=api.get_data,
                update_interval=timedelta(seconds=UPDATE_INTERVAL),
            )

            await coordinator.async_config_entry_first_refresh()

            inverter_data[inverter_id] = {
                "coordinator": coordinator,
                "api": api,
                "inverter": inverter,
            }
    except Exception:
        for inverter_id, api in created_apis.items():
            await api.close()
            _LOGGER.debug(
                "Closed API session for inverter %s after setup failure",
                inverter_id,
            )
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "inverters": inverter_data,
    }

    _async_remove_stale_devices(hass, entry, set(inverter_data))
    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Close all API sessions
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        for inverter_id, inverter_info in entry_data["inverters"].items():
            api = inverter_info["api"]
            await api.close()
            _LOGGER.debug("Closed API session for inverter %s", inverter_id)

        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SET_PREDICTIONS)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_PREDICTIONS)
            hass.services.async_remove(DOMAIN, SERVICE_SET_PLAN_STEPS)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_PLAN_STEPS)

    return unload_ok


class ProteusDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Proteus API."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        update_method,
        update_interval: timedelta,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            logger,
            name=name,
            update_method=update_method,
            update_interval=update_interval,
        )

    async def _async_update_data(self):
        """Update data via library."""
        try:
            return await self.update_method()
        except AuthenticationError as exception:
            raise ConfigEntryAuthFailed(
                f"Authentication failed: {exception}"
            ) from exception
        except Exception as exception:
            raise UpdateFailed(exception) from exception
