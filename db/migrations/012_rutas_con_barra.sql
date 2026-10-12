-- Paths written on Windows used backslashes, which Linux reads as part of the file name.
-- Forward slashes work on both. chr(92) is the backslash.
UPDATE documentos SET ruta_local = replace(ruta_local, chr(92), '/') WHERE strpos(ruta_local, chr(92)) > 0;
