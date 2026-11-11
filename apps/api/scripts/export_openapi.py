"""Write the API's OpenAPI document to a file: the source of truth for shared contracts.

Usage: ``python scripts/export_openapi.py <output-path>``. Requires the same environment
variables as the API (see .env.example) because the application factory validates settings.
"""

import json
import sys
from pathlib import Path

from auren_api.main import create_app


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: export_openapi.py <output-path>\n")
        return 2
    document = create_app().openapi()
    Path(argv[1]).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
