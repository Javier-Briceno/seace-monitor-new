-- Runs only when the Postgres volume is empty (docker-entrypoint-initdb.d).
-- Changes to a database that already holds data go into numbered migrations.

CREATE TABLE licitaciones (
    nid_proceso        bigint PRIMARY KEY,  -- SEACE nidProceso = OCDS tenderId
    nomenclatura       text NOT NULL,
    entidad            text NOT NULL,
    descripcion        text NOT NULL,
    fecha_publicacion  timestamptz,
    departamento       text,
    ubicacion_fuente   text NOT NULL DEFAULT 'unknown'
        CHECK (ubicacion_fuente IN ('mef', 'text', 'ubigeo', 'entity', 'unknown')),
    reiniciado_desde   text,
    posible_duplicado  boolean NOT NULL DEFAULT false,
    visto_primero_en   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE documentos (
    id                 bigserial PRIMARY KEY,
    nid_proceso        bigint NOT NULL REFERENCES licitaciones (nid_proceso),
    tipo               text NOT NULL,
    url                text NOT NULL,
    ruta_local         text,
    estado             text NOT NULL DEFAULT 'pending'
        CHECK (estado IN ('pending', 'done', 'error')),
    intentos           integer NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    ultimo_error       text,
    visto_primero_en   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (nid_proceso, url)
);

-- A new extractor version adds a row; earlier extractions are kept.
CREATE TABLE extracciones (
    id                 bigserial PRIMARY KEY,
    documento_id       bigint NOT NULL REFERENCES documentos (id),
    version_extractor  text NOT NULL,
    campos             jsonb,
    motivo_no_legible  text,
    estado             text NOT NULL DEFAULT 'pending'
        CHECK (estado IN ('pending', 'done', 'error')),
    intentos           integer NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    ultimo_error       text,
    creado_en          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (documento_id, version_extractor)
);

CREATE TABLE historial (
    id                 bigserial PRIMARY KEY,
    nid_proceso        bigint NOT NULL REFERENCES licitaciones (nid_proceso),
    campo              text NOT NULL,
    valor_anterior     text,
    valor_nuevo        text,
    detectado_en       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON documentos (estado);
CREATE INDEX ON extracciones (estado);
CREATE INDEX ON historial (nid_proceso);
