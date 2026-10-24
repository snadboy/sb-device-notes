"""Config flow (one entry, nothing to set) and the options flow that manages fields."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import DOMAIN, ENTRY_TITLE
from .manager import NotesManager
from .model import (
    FIELD_TYPES,
    LINK,
    LONG_TEXT,
    SCOPE_PICKED,
    SCOPES,
    TEXT,
    NoteError,
)

_STRING_TYPES = [TEXT, LONG_TEXT, LINK]


class DeviceNotesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add SB Device Notes."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=ENTRY_TITLE, data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DeviceNotesOptionsFlow()


def _select(options: list[str] | list[SelectOptionDict], *, key: str | None = None, multiple: bool = False) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            translation_key=key,
            multiple=multiple,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class DeviceNotesOptionsFlow(OptionsFlow):
    """Configure: create, edit and delete fields; add a field to a device."""

    def __init__(self) -> None:
        self._fid: str | None = None

    @property
    def _manager(self) -> NotesManager:
        return self.config_entry.runtime_data

    def _done(self) -> ConfigFlowResult:
        self._manager.changed()
        return self.async_create_entry(data={})

    def _field_options(self) -> list[SelectOptionDict]:
        book = self._manager.book
        return [
            SelectOptionDict(value=fid, label=f"{f['name']} ({f['type'].replace('_', ' ')})")
            for fid, f in book.fields.items()
        ]

    def _domains(self) -> list[str]:
        return sorted({e.domain for e in self.hass.config_entries.async_entries() if e.domain != DOMAIN})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_to_device", "add_field", "edit_field", "delete_field"],
        )

    # ---- add a field to a device ---------------------------------------------------

    async def async_step_add_to_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            device = self._manager.device(user_input["device_id"])
            if device is None:
                errors["device_id"] = "bad_device"
            else:
                try:
                    self._manager.book.pick(device, user_input["field"])
                except NoteError as err:
                    errors["base"], placeholders["error"] = "invalid", str(err)
                else:
                    return self._done()
        schema = vol.Schema(
            {
                vol.Required("device_id"): DeviceSelector(DeviceSelectorConfig()),
                vol.Required("field"): _select(self._field_options()),
            }
        )
        return self.async_show_form(
            step_id="add_to_device",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    # ---- create a field ---------------------------------------------------------------

    async def async_step_add_field(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            try:
                self._manager.book.add_field(
                    user_input["name"],
                    user_input["type"],
                    user_input["scope"],
                    user_input.get("integrations", []),
                )
            except NoteError as err:
                errors["base"], placeholders["error"] = "invalid", str(err)
            else:
                return self._done()
        schema = vol.Schema(
            {
                vol.Required("name"): TextSelector(),
                vol.Required("type", default=TEXT): _select(list(FIELD_TYPES), key="field_type"),
                vol.Required("scope", default=SCOPE_PICKED): _select(list(SCOPES), key="scope"),
                vol.Optional("integrations", default=[]): _select(self._domains(), multiple=True),
            }
        )
        return self.async_show_form(
            step_id="add_field",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
            description_placeholders=placeholders,
        )

    # ---- edit a field -----------------------------------------------------------------------

    async def async_step_edit_field(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._fid = user_input["field"]
            return await self.async_step_edit_field_details()
        return self.async_show_form(
            step_id="edit_field",
            data_schema=vol.Schema({vol.Required("field"): _select(self._field_options())}),
        )

    async def async_step_edit_field_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        book = self._manager.book
        assert self._fid is not None
        field = book.fields[self._fid]
        errors: dict[str, str] = {}
        placeholders = {"error": "", "field": field["name"]}
        if user_input is not None:
            try:
                book.update_field(
                    self._fid,
                    name=user_input["name"],
                    ftype=user_input.get("type", field["type"]),
                    scope=user_input["scope"],
                    integrations=user_input.get("integrations", []),
                )
            except NoteError as err:
                errors["base"], placeholders["error"] = "invalid", str(err)
            else:
                return self._done()
        types = _STRING_TYPES if field["type"] in _STRING_TYPES else [field["type"]]
        schema = vol.Schema(
            {
                vol.Required("name"): TextSelector(),
                vol.Required("type"): _select(types, key="field_type"),
                vol.Required("scope"): _select(list(SCOPES), key="scope"),
                vol.Optional("integrations"): _select(self._domains(), multiple=True),
            }
        )
        current = {
            "name": field["name"],
            "type": field["type"],
            "scope": field["scope"],
            "integrations": field["integrations"],
        }
        return self.async_show_form(
            step_id="edit_field_details",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or current),
            errors=errors,
            description_placeholders=placeholders,
        )

    # ---- delete a field -----------------------------------------------------------------------

    async def async_step_delete_field(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._fid = user_input["field"]
            return await self.async_step_delete_field_confirm()
        return self.async_show_form(
            step_id="delete_field",
            data_schema=vol.Schema({vol.Required("field"): _select(self._field_options())}),
        )

    async def async_step_delete_field_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        book = self._manager.book
        assert self._fid is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("confirm"):
                book.delete_field(self._fid)
                return self._done()
            errors["confirm"] = "not_confirmed"
        return self.async_show_form(
            step_id="delete_field_confirm",
            data_schema=vol.Schema({vol.Required("confirm", default=False): BooleanSelector()}),
            errors=errors,
            description_placeholders={
                "field": book.fields[self._fid]["name"],
                "count": str(book.field_usage(self._fid)),
            },
        )
