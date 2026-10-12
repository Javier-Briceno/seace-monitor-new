-- Paths written on Windows used backslashes, which Linux reads as part of the file name.
-- Forward slashes work on both.
UPDATE documentos SET ruta_local = replace(ruta_local, E'\', '/') WHERE strpos(ruta_local, E'\') > 0;
