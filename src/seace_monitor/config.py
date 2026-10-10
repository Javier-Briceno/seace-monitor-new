import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

from .search import ALL_DEPARTAMENTOS, LIMA, Query, normalize


def load(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def queries(config: dict, today: date | None = None, open_since: dict[str, date] | None = None) -> list[Query]:
    """One query per departamento: the configured ones over the last N days, stretched back
    to the oldest obra still tracked there. open_since maps a stored departamento_busqueda
    to that date, so departamentos no longer configured are still searched while obras stay open.
    """
    search = config["search"]
    hasta = today or datetime.now(LIMA).date()
    recent = hasta - timedelta(days=search["dias"])
    # Labels match without accents or case, as the portal options do.
    oldest = {normalize(d): since for d, since in (open_since or {}).items()}
    labels = {normalize(d): d for d in search["departamentos"]}
    labels.update({key: d for key, d in zip(oldest, open_since or {}) if key not in labels})
    return [
        Query(
            objeto=search["objeto"],
            departamento=None if label == ALL_DEPARTAMENTOS else label,
            anio=search.get("anio"),
            version_seace=search.get("version_seace"),
            desde=min(recent, oldest.get(key, recent)),
            hasta=hasta,
        )
        for key, label in labels.items()
    ]


def proxy(config: dict) -> str | None:
    """HTTP proxy for portal requests; None means a direct connection."""
    return config.get("network", {}).get("proxy") or None


def download_dir(config: dict) -> Path:
    return Path(config.get("download", {}).get("dir") or "data/documentos")


def report_dir(config: dict) -> Path:
    return Path(config.get("report", {}).get("dir") or "data/informes")


def watched(config: dict) -> list[str]:
    return list(config["search"]["departamentos"])


def extraction_dir(config: dict) -> Path:
    return Path(config.get("extract", {}).get("dir") or "data/extracciones")
