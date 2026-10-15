-- An obra located by the name its bases give in section 1.3, when SEACE's description named no departamento.
ALTER TABLE licitaciones DROP CONSTRAINT licitaciones_ubicacion_fuente_check;
ALTER TABLE licitaciones ADD CONSTRAINT licitaciones_ubicacion_fuente_check
    CHECK (ubicacion_fuente IN ('mef', 'text', 'ubigeo', 'entity', 'bases', 'unknown'));
