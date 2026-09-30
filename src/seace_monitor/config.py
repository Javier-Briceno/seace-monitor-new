import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

from .search import LIMA, Query


def load(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def queries(config: dict, today: date | None = None) -> list[Query]:
    search = config["search"]
    hasta = today or datetime.now(LIMA).date()
    desde = hasta - timedelta(days=search["dias"])
    return [
        Query(
            objeto=search["objeto"],
            departamento=departamento,
            anio=search.get("anio"),
            version_seace=search.get("version_seace"),
            desde=desde,
            hasta=hasta,
        )
        for departamento in search["departamentos"]
    ]


def proxy(config: dict) -> str | None:
    """HTTP proxy for portal requests; None means a direct connection."""
    return config.get("network", {}).get("proxy") or None


def download_dir(config: dict) -> Path:
    return Path(config.get("download", {}).get("dir") or "data/documentos")
