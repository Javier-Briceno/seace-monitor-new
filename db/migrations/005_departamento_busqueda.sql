-- The departamento filter of the search that found the licitación ('TODOS' without filter).
-- A ficha only opens from a search that returns its row, so tracking repeats this search.
-- NULL on rows stored before this was recorded.
ALTER TABLE licitaciones ADD COLUMN departamento_busqueda text;
