-- An extraction is reported on its own, days after its obra: it needs its own report mark.
ALTER TABLE extracciones ADD COLUMN informado_en timestamptz;
