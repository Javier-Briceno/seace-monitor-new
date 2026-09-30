from seace_monitor.locate import locate


def test_marked_departamento():
    text = "PUENTE PEATONAL ..., DISTRITO DE JILILI, PROVINCIA DE AYABACA, DEPARTAMENTO DE PIURA"
    assert locate(text) == (["PIURA"], "text")


def test_marker_without_de_and_with_accents():
    assert locate("DISTRITO DE SAN MARCOS, PROVINCIA HUARI, DEPARTAMENTO ÁNCASH")[0] == ["ANCASH"]


def test_road_between_two_departamentos_keeps_both():
    text = "CARRETERA ENTRE CACHICADAN, DEPARTAMENTO DE LA LIBERTAD Y CAJABAMBA, DEPARTAMENTO DE CAJAMARCA"
    assert locate(text) == (["CAJAMARCA", "LA LIBERTAD"], "text")


def test_marker_wins_over_street_name():
    text = "PISTAS EN EL JR. LA LIBERTAD, DISTRITO DE HUARAZ, PROVINCIA DE HUARAZ, DEPARTAMENTO DE ANCASH"
    assert locate(text)[0] == ["ANCASH"]


def test_bare_mention_used_when_no_marker():
    assert locate("MEJORAMIENTO DEL CAMINO VECINAL EN OTUZCO - LA LIBERTAD")[0] == ["LA LIBERTAD"]


def test_bare_street_name_is_skipped():
    assert locate("VEREDAS DEL JR. LA LIBERTAD Y AV. SAN MARTIN, DISTRITO DE HUARAZ") == ([], "unknown")


def test_names_match_whole_words_only():
    # "ICA" inside PUBLICA, "LIMA" inside CLIMA
    assert locate("INFRAESTRUCTURA PUBLICA RESISTENTE AL CLIMA") == ([], "unknown")


def test_multi_word_name():
    assert locate("DEPARTAMENTO DE MADRE DE DIOS")[0] == ["MADRE DE DIOS"]
