import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from b3_core.log import log_info, log_error


def test_log_info_campos_fixos(capsys):
    log_info("test_job", ticker="PETR4")
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["level"] == "info"
    assert data["job"] == "test_job"
    assert "ts" in data
    assert data["ticker"] == "PETR4"


def test_log_error_campos_fixos(capsys):
    log_error("test_job", error="algo falhou")
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["level"] == "error"
    assert data["job"] == "test_job"
    assert data["error"] == "algo falhou"


def test_log_info_sem_campos_extras(capsys):
    log_info("job_simples")
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["level"] == "info"
    assert data["job"] == "job_simples"
    assert "ts" in data
