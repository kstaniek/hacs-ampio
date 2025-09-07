"""Utility functions for the Ampio integration."""

from __future__ import annotations


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
