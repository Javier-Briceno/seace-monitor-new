"""The fields read from the bases, in one place. Manual extraction uses them now, automatic extraction later.

Every section of the 2025-law standard bases is either a field here or listed in EXCLUDED with a reason,
so nothing is left out without a decision.
"""

# key, label, where to look in the standard bases
FIELDS = (
    ("cuantia", "Cuantía de la contratación (S/)", "1.4"),
    ("fuente_financiamiento", "Fuente de financiamiento", "1.6"),
    ("sistema_entrega", "Sistema de entrega (solo construcción / diseño y construcción)", "capítulo III, título"),
    ("plazo_ejecucion_dias", "Plazo de ejecución (días calendario)", "3.3.14"),
    ("modalidad_pago", "Modalidad de pago (suma alzada / precios unitarios / mixta)", "3.3.16"),
    ("oferta_economica", "Evaluación económica (fija / limitada)", "4.2"),
    ("experiencia_monto", "Experiencia del postor: monto facturado pedido (S/)", "3.8.1 A"),
    ("experiencia_especialidad", "Experiencia del postor: especialidad y subespecialidades", "3.8.1 A"),
    ("experiencia_ventana_anios", "Experiencia del postor: años hacia atrás", "3.8.1 A"),
    ("personal_clave", "Personal clave: cargo, profesión y meses, uno por línea", "3.8.1 B"),
    ("equipamiento", "Equipamiento estratégico", "3.8.1 C"),
    ("consorcio", "Consorcio: máximo de integrantes y porcentajes mínimos", "3.8.1 D"),
    ("factores", "Factores de evaluación con sus puntos, uno por línea", "capítulo IV"),
    ("factores_subjetivos", "Factores que el evaluador juzga por contenido (mejora al requerimiento, plan, metodología); o 'ninguno'", "capítulo IV"),
    ("minimo_tecnico", "Puntaje técnico mínimo", "4.1"),
    ("adelantos", "Adelantos: directo y de materiales (%)", "3.3.17"),
    ("penalidades", "Penalidades: por mora y otras", "3.3.1 y 3.3.2 (al final del capítulo III)"),
    ("terreno", "Disponibilidad física del terreno", "3.3.7"),
    ("garantias", "Garantías para firmar el contrato", "2.3"),
    ("notas", "Notas libres", ""),
)

KEYS = tuple(key for key, _, _ in FIELDS)

EXCLUDED = {
    "1.1 base legal, 1.5 expediente": "the same in every bases",
    "1.2 entidad, 1.3 objeto": "already in the search list",
    "2.1 cronograma": "read from the ficha",
    "2.2 contenido de las ofertas, 2.4 perfeccionamiento": "procedure, the same in every bases",
    "3.1-3.3.6 finalidad, descripción, alcance, ubicación, metas": "already in the description; location has its own module",
    "3.3.8-3.3.13 subcontratación, seguros, metodologías, calidad, contingencia, adicionales": "rarely differ; revisit after the first obras",
    "3.3.15, 3.3.18-3.3.20 plazos de respuesta, ahorros, incentivos, reajuste": "standard formulas",
    "3.4-3.7 forma de pago, recepción, controversias, liquidación": "contract execution, not the decision to bid",
}
