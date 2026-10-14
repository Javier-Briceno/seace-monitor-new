-- Every stage of a licitación's cronograma as its ficha shows it now. Older dates live in historial.
CREATE TABLE cronograma (
    nid_proceso  bigint NOT NULL REFERENCES licitaciones (nid_proceso),
    orden        integer NOT NULL,
    etapa        text NOT NULL,
    lugar        text,
    inicio       text,
    fin          text,
    PRIMARY KEY (nid_proceso, orden)
);
