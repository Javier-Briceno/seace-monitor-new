-- The obra this one restarts: the latest earlier licitación with the same entidad and nomenclatura.
-- Linked by store.link_restarts; the earlier one stops being tracked.
ALTER TABLE licitaciones ADD COLUMN reinicio_de bigint UNIQUE REFERENCES licitaciones (nid_proceso);
CREATE INDEX ON licitaciones (entidad, nomenclatura);
