"""Which licitaciones are still followed: re-read until they stop taking offers."""

from .search import normalize

# Published once the offers are opened, even while the estado still says Convocado.
RESULT_DOCUMENTS = ("presentacion de propuestas", "calificacion y evaluacion")


def closes(estados: list[str] | None, documents: list[dict]) -> bool:
    """True when no item is Convocado any more, or the offers or the calificación are published.

    An obra with several items stays open while any of them is Convocado.
    Without estados only the documents decide.
    """
    if estados and "convocado" not in {normalize(e) for e in estados}:
        return True
    return any(r in normalize(d["tipo"]) for d in documents for r in RESULT_DOCUMENTS)
