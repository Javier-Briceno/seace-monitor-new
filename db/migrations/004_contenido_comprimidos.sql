-- What a downloaded ZIP, RAR or 7z holds. contenido_estado stays NULL until it is unpacked.
ALTER TABLE documentos ADD COLUMN contenido_estado text CHECK (contenido_estado IN ('done', 'error'));
ALTER TABLE documentos ADD COLUMN contenido_error text;

CREATE TABLE documento_contenido (
    id                 bigserial PRIMARY KEY,
    documento_id       bigint NOT NULL REFERENCES documentos (id),
    ruta               text NOT NULL,     -- relative to the archive's _contenido folder
    tamano_bytes       bigint NOT NULL,
    dentro_de          text NOT NULL,     -- the archive it came out of; '' for the downloaded one
    error              text,              -- why an archive inside could not be opened
    UNIQUE (documento_id, ruta)
);
