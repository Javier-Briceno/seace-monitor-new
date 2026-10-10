-- When a re-read ficha last differed from what was stored; tracking stops after 60 days without a change.
-- NULL until the first change: the publication date counts instead.
ALTER TABLE licitaciones ADD COLUMN ultimo_cambio_en timestamptz;
