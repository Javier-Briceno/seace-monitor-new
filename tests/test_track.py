from seace_monitor.track import closes

BASES = {"tipo": "Bases Administrativas"}


def test_open_while_an_item_is_convocado():
    assert not closes(["Convocado"], [BASES])
    assert not closes(["Desierto", "Convocado"], [BASES])


def test_closed_when_no_item_is_convocado():
    for estado in ("Adjudicado", "Consentido", "Contratado", "Apelado", "Desierto", "Nulo", "Cancelado",
                   "Retrotraído por resolución", "Registro de efecto no culminado"):
        assert closes([estado], [BASES]), estado
    assert closes(["Desierto", "Contratado"], [BASES])


def test_closed_when_offers_or_calificacion_are_published():
    assert closes(["Convocado"], [BASES, {"tipo": "Documentos de Presentación de Propuestas"}])
    assert closes(["Convocado"], [BASES, {"tipo": "Documentos de Calificación y Evaluación"}])


def test_without_estados_only_documents_decide():
    assert not closes(None, [BASES])
    assert not closes([], [BASES])
    assert closes(None, [{"tipo": "Documentos de Calificacion y Evaluacion"}])
