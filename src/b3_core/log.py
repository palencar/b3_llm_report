import json
import sys
from datetime import datetime


def _emit(level: str, job: str, **fields) -> None:
    payload = {
        "level": level,
        "job": job,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False), file=sys.stdout)


def log_info(job: str, **fields) -> None:
    _emit("info", job, **fields)


def log_error(job: str, **fields) -> None:
    _emit("error", job, **fields)
