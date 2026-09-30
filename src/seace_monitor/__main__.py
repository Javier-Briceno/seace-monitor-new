"""Run the search from config.toml and store new licitaciones.

    python -m seace_monitor [--config config.toml]
"""

import argparse
import sys

from . import config, db
from .locate import locate
from .search import SearchError, make_session, search
from .store import save_new_licitaciones


def main() -> int:
    parser = argparse.ArgumentParser(prog="seace_monitor")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()

    cfg = config.load(args.config)
    proxy = config.proxy(cfg)
    session = make_session(proxy)
    print(f"route: {'VPN proxy ' + proxy if proxy else 'direct'}")
    conn = db.connect()
    for query in config.queries(cfg):
        print(f"{query.objeto} / {query.departamento} / {query.desde} to {query.hasta}")
        try:
            result = search(query, session)
        except SearchError as error:
            print(f"  failed: {error}", file=sys.stderr)
            return 1
        print(f"  portal total {result.total}, rows on this page {len(result.rows)}")
        if result.total > len(result.rows):
            print(f"  warning: only the first page is read, {result.total - len(result.rows)} rows not collected")
        for row in result.rows:
            row["departamentos"], row["ubicacion_fuente"] = locate(row["descripcion"])
        new = set(save_new_licitaciones(conn, result.rows))
        print(f"  new: {len(new)}, already stored: {len(result.rows) - len(new)}")
        for row in result.rows:
            mark = "new" if row["nid_proceso"] in new else "   "
            print(
                f"  {mark} {row['nid_proceso']}  {row['fecha_publicacion']:%d/%m %H:%M}  "
                f"{row['nomenclatura']}  {row['valor_referencial']} {row['moneda']}  "
                f"{'/'.join(row['departamentos']) or '?'}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
