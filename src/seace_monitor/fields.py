"""The fields read from the bases, in one place. Manual extraction uses them now, automatic extraction later.

Where to look: chapters I and II keep their numbers (1.4, 1.6 and 2.3 in nearly all of 79 text bases
checked); chapter III does not, because entities drop or add subsections, so its numbers are only
the most common ones and the title is what counts.

Every section of the 2025-law standard bases is either a field here or listed in EXCLUDED with a reason,
so nothing is left out without a decision.
"""

# key, label, where to look in the standard bases (by title)
FIELDS = (
    ("cuantia", "Cuantía de la contratación (S/)", "1.4 CUANTÍA DE LA CONTRATACIÓN"),
    ("fuente_financiamiento", "Fuente de financiamiento", "1.6 FUENTE DE FINANCIAMIENTO"),
    ("sistema_entrega", "Sistema de entrega (solo construcción / diseño y construcción)", "cap. III, título del requerimiento"),
    ("plazo_ejecucion_dias", "Plazo de ejecución (días calendario)", "cap. III, PLAZO DE EJECUCIÓN (suele ser 3.3.12)"),
    ("modalidad_pago", "Modalidad de pago (suma alzada / precios unitarios / mixta)", "cap. III, MODALIDAD DE PAGO (suele ser 3.3.14)"),
    ("oferta_economica", "Evaluación económica (fija / limitada)", "cap. IV, EVALUACIÓN ECONÓMICA"),
    ("experiencia_monto", "Experiencia del postor: monto facturado pedido (S/)", "cap. III, REQUISITOS DE CALIFICACIÓN, EXPERIENCIA DEL POSTOR"),
    ("experiencia_especialidad", "Experiencia del postor: especialidad y subespecialidades", "cap. III, REQUISITOS DE CALIFICACIÓN, EXPERIENCIA DEL POSTOR"),
    ("experiencia_ventana_anios", "Experiencia del postor: años hacia atrás", "cap. III, REQUISITOS DE CALIFICACIÓN, EXPERIENCIA DEL POSTOR"),
    ("personal_clave", "Personal clave: un bloque por cargo; copia el bloque entero para cada uno", "cap. III, REQUISITOS DE CALIFICACIÓN, PERSONAL CLAVE"),
    ("equipamiento", "Equipamiento estratégico", "cap. III, REQUISITOS DE CALIFICACIÓN, EQUIPAMIENTO ESTRATÉGICO"),
    ("consorcio", "Consorcio: máximo de integrantes y porcentajes mínimos", "cap. III, REQUISITOS DE CALIFICACIÓN, PARTICIPACIÓN EN CONSORCIO"),
    ("factores", "Factores de evaluación con sus puntos, uno por línea", "cap. IV, FACTORES DE EVALUACIÓN"),
    ("factores_subjetivos", "Factores que el evaluador juzga por contenido (mejora al requerimiento, plan, metodología); o 'ninguno'", "cap. IV, FACTORES DE EVALUACIÓN"),
    ("minimo_tecnico", "Puntaje técnico mínimo", "cap. IV, EVALUACIÓN TÉCNICA"),
    ("adelantos", "Adelantos: directo y de materiales (%)", "cap. III, ADELANTOS (suele ser 3.3.15)"),
    ("penalidades", "Penalidades: por mora y otras", "cap. III, PENALIDADES (suele ser 3.3.19 o 3.3.20)"),
    ("terreno", "Disponibilidad física del terreno", "cap. III, DISPONIBILIDAD FÍSICA DEL TERRENO (suele ser 3.3.3)"),
    ("garantias", "Garantías para firmar el contrato", "2.3 REQUISITOS PARA PERFECCIONAR EL CONTRATO"),
    ("notas", "Notas libres; cada consulta a la entidad en su propia línea, empezando con 'Consulta:'", ""),
)

KEYS = tuple(key for key, _, _ in FIELDS)

# Fields filled as rows because the verdict compares their parts one by one (see 02-verdict-design).
# Each column has a kind: str, int, bool, list (of strings, not empty), OPTIONAL_LIST, or a tuple of the allowed values.
OPTIONAL_LIST = "optional list"

# An accepted job is a role, or a role in an area when the bases combine them ("Jefe y/o Coordinador
# en/de: Seguridad ... y/o SSOMA"); `areas` stays empty when the bases list whole job titles.
ROW_FIELDS = {
    "personal_clave": (
        ("cargo", str), ("cantidad", int), ("profesiones", list), ("grado", ("título profesional", "bachiller")),
        ("colegiado", bool), ("meses", int), ("desde_colegiatura", bool), ("roles", list), ("areas", OPTIONAL_LIST),
        ("ambito", ("subespecialidad", "obras en general")), ("ventana_anios", int), ("pagina", str),
    ),
}

# Short names for readers of the report; the labels above are instructions for whoever fills a template.
NAMES = {
    "cuantia": "Cuantía", "fuente_financiamiento": "Fuente de financiamiento", "sistema_entrega": "Sistema de entrega",
    "plazo_ejecucion_dias": "Plazo", "modalidad_pago": "Modalidad de pago", "oferta_economica": "Evaluación económica",
    "experiencia_monto": "Experiencia pedida", "experiencia_especialidad": "Especialidad de la experiencia",
    "experiencia_ventana_anios": "Antigüedad de la experiencia", "personal_clave": "Personal clave",
    "equipamiento": "Equipamiento", "consorcio": "Consorcio", "factores": "Factores de evaluación",
    "factores_subjetivos": "Factores subjetivos", "minimo_tecnico": "Mínimo técnico", "adelantos": "Adelantos",
    "penalidades": "Penalidades", "terreno": "Terreno", "garantias": "Garantías", "notas": "Notas",
}

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
