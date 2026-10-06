-- A ficha can list a document without download link; it is stored so the gap is visible.
ALTER TABLE documentos ALTER COLUMN uuid DROP NOT NULL;
ALTER TABLE documentos DROP CONSTRAINT documentos_estado_check;
ALTER TABLE documentos ADD CONSTRAINT documentos_estado_check
    CHECK (estado IN ('pending', 'done', 'error', 'sin_enlace'));

-- Without a uuid, a row re-read from the same ficha is recognised by stage, type and name.
CREATE UNIQUE INDEX documentos_sin_enlace_unico ON documentos (nid_proceso, etapa, tipo, nombre_archivo)
    WHERE uuid IS NULL;
