-- What the vision model's transcriptions cost per calendar month (Lima time), so a monthly cap can stop them.
CREATE TABLE gasto_ia (
    mes date PRIMARY KEY,
    usd numeric(10, 4) NOT NULL DEFAULT 0,
    paginas integer NOT NULL DEFAULT 0
);
