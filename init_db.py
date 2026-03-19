import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from b3_core.config import load_config
from b3_storage.db import connect
from b3_storage.schema import SCHEMA_SQL


def main() -> int:
    config = load_config()
    db_path = config.db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = connect(db_path)
    for statement in SCHEMA_SQL.split(";"):
        stmt = statement.strip()
        if stmt:
            con.execute(stmt)
    con.close()
    print(f"Schema inicializado em: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
