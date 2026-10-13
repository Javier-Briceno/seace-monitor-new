-- The web search tool: sign-in links sent by mail, sessions, and the obras each person follows.
-- Only hashes of the tokens are stored; the token itself travels in the link or the cookie.
CREATE TABLE web_accesos (
    token_hash   text PRIMARY KEY,
    correo       text NOT NULL,
    creado_en    timestamptz NOT NULL DEFAULT now(),
    vence_en     timestamptz NOT NULL,
    usado_en     timestamptz
);
CREATE INDEX ON web_accesos (correo, creado_en);

CREATE TABLE web_sesiones (
    token_hash   text PRIMARY KEY,
    correo       text NOT NULL,
    csrf         text NOT NULL,
    creado_en    timestamptz NOT NULL DEFAULT now(),
    vence_en     timestamptz NOT NULL
);

CREATE TABLE seguidas (
    correo       text NOT NULL,
    nid_proceso  bigint NOT NULL REFERENCES licitaciones (nid_proceso),
    creado_en    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (correo, nid_proceso)
);
