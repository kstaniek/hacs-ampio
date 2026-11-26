"""Keep translated onboarding forms aligned with integration strings."""

import json
from pathlib import Path
from string import Formatter

import pytest


@pytest.mark.parametrize("language", ["en", "pl"])
def test_translation_structure_and_placeholders(language: str) -> None:
    """Every form, error, and placeholder must remain available in each locale."""
    root = Path(__file__).parents[1] / "custom_components" / "ampio"
    reference = json.loads((root / "strings.json").read_text())
    translated = json.loads((root / "translations" / f"{language}.json").read_text())

    def compare(expected: dict, actual: dict) -> None:
        assert expected.keys() == actual.keys()
        for key, value in expected.items():
            if isinstance(value, dict):
                compare(value, actual[key])
            else:
                fields = {name for _, name, _, _ in Formatter().parse(value) if name}
                translated_fields = {
                    name for _, name, _, _ in Formatter().parse(actual[key]) if name
                }
                assert fields == translated_fields

    compare(reference, translated)
