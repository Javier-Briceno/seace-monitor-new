-- Runs only when the Postgres volume is empty (docker-entrypoint-initdb.d).
-- Changes to a database that already holds data go into numbered migrations.

CREATE TABLE licitaciones (
    nid_proceso        bigint PRIMARY KEY,  -- SEACE nidProceso = OCDS tenderId
    nomenclatura       text NOT NULL,
    entidad            text NOT NULL,
    objeto             text NOT NULL,
    descripcion        text NOT NULL,
    fecha_publicacion  timestamptz,
    valor_referencial  numeric(15, 2),       -- NULL when the list shows "---"
    moneda             text,
    cui                text,
    departamentos      text[] NOT NULL DEFAULT '{}',  -- every one named; a road can span two
    ubicacion_fuente   text NOT NULL DEFAULT 'unknown'
        CHECK (ubicacion_fuente IN ('mef', 'text', 'ubigeo', 'entity', 'unknown')),
    reiniciado_desde   text,
    posible_duplicado  boolean NOT NULL DEFAULT false,
    -- Reading the ficha (document list) needs the search session, so it is
    -- retried on later searches until at least one bases is listed.
    ficha_estado       text NOT NULL DEFAULT 'pending'
        CHECK (ficha_estado IN ('pending', 'done', 'error')),
    ficha_intentos     integer NOT NULL DEFAULT 0 CHECK (ficha_intentos >= 0),
    ficha_ultimo_error text,
    visto_primero_en   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE documentos (
    id                 bigserial PRIMARY KEY,
    nid_proceso        bigint NOT NULL REFERENCES licitaciones (nid_proceso),
    uuid               text NOT NULL UNIQUE,  -- id in SEACE's document store; enough to download
    etapa              text NOT NULL,
    tipo               text NOT NULL,         -- e.g. "Bases Administrativas"
    nombre_archivo     text NOT NULL,
    publicado_en       timestamptz,
    ruta_local         text,
    tamano_bytes       bigint,
    estado             text NOT NULL DEFAULT 'pending'
        CHECK (estado IN ('pending', 'done', 'error')),
    intentos           integer NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    ultimo_error       text,
    visto_primero_en   timestamptz NOT NULL DEFAULT now()
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
