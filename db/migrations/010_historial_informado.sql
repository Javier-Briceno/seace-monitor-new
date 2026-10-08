-- When a change went out in the daily report; NULL until the mail server accepted it.
ALTER TABLE historial ADD COLUMN informado_en timestamptz;
