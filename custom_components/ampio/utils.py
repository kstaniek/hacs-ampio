"""Utility functions for the Ampio integration."""

from __future__ import annotations

from homeassistant.util import slugify

from .const import DEFAULT_CAN_CHANNEL, DEFAULT_CAN_INTERFACE


def entity_area(area: str | None, device_area: str | None = None) -> str | None:
    """Prefer the resource's YAML area, falling back to its owning module's area."""
    return next(
        (value.strip() for value in (area, device_area) if value and value.strip()),
        None,
    )


def entity_object_id(name: str, resource_id: str, area: str | None = None) -> str:
    """Prefix the configured entity name with its resolved YAML area, if distinct."""
    object_id = slugify(name) or slugify(resource_id)
    area_id = slugify(area.strip()) if area and area.strip() else ""
    return f"{area_id}_{object_id}" if area_id and area_id != object_id else object_id


def describe_can_connection(
    host: str,
    port: int,
    *,
    interface: str = DEFAULT_CAN_INTERFACE,
    channel: str = DEFAULT_CAN_CHANNEL,
) -> str:
    """Describe the active transport for device metadata and entry titles."""
    address = f"[{host}]" if ":" in host else host
    return f"CAN Bridge ({interface} / {channel}, {address}:{port})"


def hex_to_int(value: str) -> int:
    """
    Convert an unsigned hexadecimal string to an integer.

    Accepts optional "0x"/"0X" prefix, allows leading zeros, and is
    case-insensitive. Whitespace around the value is ignored.

    Raises ValueError if the string is not a valid hexadecimal number.
    """
    if not isinstance(value, str):
        msg = "value must be a string"
        raise TypeError(msg)

    s = value.strip()
    if not s:
        msg = "empty string is not a valid hexadecimal number"
        raise ValueError(msg)

    # Optional 0x/0X prefix
    if s[:2].lower() == "0x":
        s = s[2:]
        if not s:
            msg = f"invalid hexadecimal string: {value!r}"
            raise ValueError(msg)

    try:
        return int(s, 16)
    except ValueError as err:
        msg = f"invalid hexadecimal string: {value!r}"
        raise ValueError(msg) from err
