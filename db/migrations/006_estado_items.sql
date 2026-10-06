-- Estado of each item as the ficha showed it at its last reading (Convocado, Adjudicado, Nulo, ...).
-- An obra usually has one item; a few have several, each with its own estado.
ALTER TABLE licitaciones ADD COLUMN estado_items text[];
