"""Persistencia atomica de relatorios e estados."""

import os
import tempfile
from pathlib import Path


def write_report_file_atomic(target_path: Path | str, content: str) -> Path:
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, target)
        temp_path = None
        return target
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
