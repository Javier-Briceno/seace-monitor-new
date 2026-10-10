-- A restart lists the earlier obra's files with the same uuid, so a uuid is unique per licitación only.
ALTER TABLE documentos DROP CONSTRAINT documentos_uuid_key;
ALTER TABLE documentos ADD CONSTRAINT documentos_nid_proceso_uuid_key UNIQUE (nid_proceso, uuid);
