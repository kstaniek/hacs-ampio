"""Update the manifest file."""

import json
import sys
from pathlib import Path

MANIFEST_FILE = Path.cwd() / "custom_components" / "hacs" / "manifest.json"


def update_manifest() -> None:
    """Update the manifest file."""
    version = "0.0.0"
    for index, value in enumerate(sys.argv):
        if value in ["--version", "-V"]:
            version = sys.argv[index + 1]

    with MANIFEST_FILE.open(encoding="utf-8") as manifestfile:
        base: dict = json.load(manifestfile)
        base["version"] = version

    with MANIFEST_FILE.open("w", encoding="utf-8") as manifestfile:
        manifestfile.write(
            json.dumps(
                {
                    "domain": base["domain"],
                    "name": base["name"],
                    **{
                        k: v
                        for k, v in sorted(base.items())
                        if k not in ("domain", "name")
                    },
                },
                indent=4,
            )
        )


update_manifest()
