-- Daily report: when a licitación was first reported, and its offer deadline from the ficha.
ALTER TABLE licitaciones ADD COLUMN informado_en timestamptz;
ALTER TABLE licitaciones ADD COLUMN fecha_limite_ofertas timestamptz;

-- Rows stored before the report existed are not news anymore.
UPDATE licitaciones SET informado_en = now();
