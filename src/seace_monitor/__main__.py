"""Run the search from config.toml and print the first results page.

    python -m seace_monitor [--config config.toml]
"""

import argparse
import sys

from . import config
from .search import SearchError, search


def main() -> int:
    parser = argparse.ArgumentParser(prog="seace_monitor")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()

    for query in config.queries(config.load(args.config)):
        print(f"{query.objeto} / {query.departamento} / {query.desde} to {query.hasta}")
        try:
            result = search(query)
        except SearchError as error:
            print(f"  failed: {error}", file=sys.stderr)
            return 1
        print(f"  portal total {result.total}, rows on this page {len(result.rows)}")
        for row in result.rows:
            print(
                f"  {row['nid_proceso']}  {row['fecha_publicacion']:%d/%m %H:%M}  "
                f"{row['nomenclatura']}  {row['valor_referencial']} {row['moneda']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
