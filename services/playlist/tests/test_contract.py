"""The code must offer exactly what contracts/api/playlist.openapi.yaml promises."""

from pathlib import Path

import yaml

from playlist_service.api.main import app

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "api" / "playlist.openapi.yaml"
METHODS = {"get", "post", "put", "patch", "delete"}


def operations(spec: dict) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in METHODS
    }


def test_the_api_has_exactly_the_contract_operations() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert operations(app.openapi()) == operations(contract)


def test_every_contract_status_code_is_documented_by_the_api() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    implemented = app.openapi()
    for path, item in contract["paths"].items():
        for method, operation in item.items():
            if method not in METHODS:
                continue
            promised = set(operation["responses"])
            offered = set(implemented["paths"][path][method]["responses"])
            # FastAPI always adds 422 for validation errors; this service returns 400 instead.
            assert promised <= offered, f"{method.upper()} {path}: missing {promised - offered}"
