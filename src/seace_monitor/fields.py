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
    ("experiencia_requerida", "Experiencia del postor en la especialidad: monto, tipo de obra y años", "cap. III, REQUISITOS DE CALIFICACIÓN, EXPERIENCIA DEL POSTOR"),
    ("personal_clave", "Personal clave: un bloque por cargo; copia el bloque entero para cada uno", "cap. III, REQUISITOS DE CALIFICACIÓN, PERSONAL CLAVE"),
    ("equipamiento", "Equipamiento estratégico", "cap. III, REQUISITOS DE CALIFICACIÓN, EQUIPAMIENTO ESTRATÉGICO"),
    ("consorcio", "Consorcio: máximo de integrantes y porcentajes mínimos", "cap. III, REQUISITOS DE CALIFICACIÓN, PARTICIPACIÓN EN CONSORCIO"),
    ("factores", "Factores de evaluación: un bloque por parte de cada factor; las columnas extra dependen del tipo (ver abajo)", "cap. IV, FACTORES DE EVALUACIÓN y CUADRO RESUMEN"),
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
        ("ambito", ("subespecialidad", "obras en general")), ("ventana_anios", int), ("cita", str), ("pagina", str),
    ),
}

# Fields filled as one block of typed columns. `cita` is the bases' own sentence, so every value
# can be checked; `veces_cuantia` keeps the rule behind `monto` so it can be recomputed.
CUENTA_DESDE = ("acta de recepción", "conformidad o comprobante de pago")

BLOCK_FIELDS = {
    "cuantia": (("monto", float), ("cita", str), ("pagina", str)),
    "experiencia_requerida": (
        ("monto", float), ("veces_cuantia", float), ("especialidad", str), ("subespecialidades", list),
        ("tipologias", OPTIONAL_LIST), ("ventana_anios", int), ("cuenta_desde", CUENTA_DESDE), ("cita", str),
        ("pagina", str),
    ),
}

# Evaluation factors, one row per part of a factor ("K" = k.1 ISO 45001 + k.3 software). A factor's rows
# repeat its letter, name and maximum from the summary table. Each type adds its own columns and the
# columns of each step of its `escala`; internal names, never shown to the reader.
FACTOR_COLUMNS = (("letra", str), ("nombre", str), ("parte", str), ("puntos_max", int), ("cita", str), ("pagina", str))

# type: (extra columns, columns of each escala step)
FACTOR_TYPES = {
    # share of the evaluated positions that exceed the required months by anios_extra; the highest step met counts
    "personal_adicional": ((("cargos", list), ("anios_extra", int)), (("pct_minimo", float), ("puntos", int))),
    # amount of additional experience; `estricto` when the bases say "más de" instead of "desde"
    "experiencia_adicional": ((("ventana_anios", int), ("cuenta_desde", CUENTA_DESDE)),
                              (("monto_minimo", float), ("estricto", bool), ("puntos", int))),
    "certificacion_empresa": ((("certificado", str), ("alcance_pedido", str)),
                              (("nivel", ("acredita", "con el alcance pedido", "con otro alcance")), ("puntos", int))),
    "capacitacion_personal": ((("cargo", str), ("tema", str)), (("nivel", str), ("puntos", int))),
    "herramienta": ((("herramienta", str),), (("nivel", ("avanzada", "básica")), ("puntos", int))),
    # judged by the committee on content (Ishikawa, plan, methodology): never scored by a rule
    "juicio_comite": ((("que_se_juzga", str),), (("nivel", str), ("puntos", int))),
}

# Short names for readers of the report; the labels above are instructions for whoever fills a template.
NAMES = {
    "cuantia": "Cuantía", "fuente_financiamiento": "Fuente de financiamiento", "sistema_entrega": "Sistema de entrega",
    "plazo_ejecucion_dias": "Plazo", "modalidad_pago": "Modalidad de pago", "oferta_economica": "Evaluación económica",
    "experiencia_requerida": "Experiencia pedida", "personal_clave": "Personal clave",
    "equipamiento": "Equipamiento", "consorcio": "Consorcio", "factores": "Factores de evaluación",
    "minimo_tecnico": "Mínimo técnico", "adelantos": "Adelantos",
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
