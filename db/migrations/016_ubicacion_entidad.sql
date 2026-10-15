-- Obras of a municipalidad or gobierno regional whose description names no departamento sit in the
-- departamento their search ran in (see locate.place); obras stored before that rule get it here.
UPDATE licitaciones SET departamentos = ARRAY[departamento_busqueda], ubicacion_fuente = 'entity'
WHERE departamentos = '{}' AND departamento_busqueda IS NOT NULL AND departamento_busqueda <> 'TODOS'
  AND entidad ~* '^(MUNICIPALIDAD\s+(DISTRITAL|PROVINCIAL|DEL\s+CENTRO\s+POBLADO)|GOBIERNO\s+REGIONAL)';
