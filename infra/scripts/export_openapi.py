"""Export a reproducible OpenAPI document without starting external services."""

import json
from pathlib import Path

from app.main import create_app

document = create_app().openapi()
Path("backend/openapi.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
