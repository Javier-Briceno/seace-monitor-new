-- Whether tracking still re-reads the licitación's ficha, and since when it stopped.
-- cerrada: no item Convocado, or offers / calificación published (track.closes).
-- reiniciada: a restart of the same obra appeared. parada: 60 days without any change.
ALTER TABLE licitaciones
    ADD COLUMN seguimiento text NOT NULL DEFAULT 'abierta'
        CHECK (seguimiento IN ('abierta', 'cerrada', 'reiniciada', 'parada')),
    ADD COLUMN seguimiento_hasta timestamptz;

-- The same rule as track.closes, applied once to the obras stored so far.
UPDATE licitaciones l
SET seguimiento = 'cerrada', seguimiento_hasta = now()
WHERE (l.estado_items IS NOT NULL AND cardinality(l.estado_items) > 0 AND NOT 'Convocado' = ANY (l.estado_items))
   OR EXISTS (
       SELECT 1 FROM documentos d
       WHERE d.nid_proceso = l.nid_proceso
         AND (translate(lower(d.tipo), 'áéíóú', 'aeiou') LIKE '%presentacion de propuestas%'
              OR translate(lower(d.tipo), 'áéíóú', 'aeiou') LIKE '%calificacion y evaluacion%')
   );
