"""Testes para src/b3_etl/cvm.py."""
import hashlib
import io
import os
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from b3_etl.cvm import parse_companies

# ---------------------------------------------------------------------------
# Helpers para gerar fixtures ZIP em memória
# ---------------------------------------------------------------------------

_CADASTRO_CSV = (
    "CNPJ_CIA;DENOM_SOCIAL;CD_CVM\n"
    "33.000.167/0001-01;PETROBRAS S.A.;9512\n"
    "60.746.948/0001-12;ITAU UNIBANCO HOLDING S.A.;7617\n"
    "33.592.510/0001-03;VALE S.A.;4170\n"
)

_DFP_BPA_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;100000;REAL;MIL\n"
    "33.000.167/0001-01;2024-12-31;PENÚLTIMO;1;Ativo Total;90000;REAL;MIL\n"
    "60.746.948/0001-12;2024-12-31;ÚLTIMO;1;Ativo Total;200000;REAL;MIL\n"
    "33.592.510/0001-03;2024-12-31;ÚLTIMO;1;Ativo Total;150000;REAL;MIL\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1.01;Ativo Circulante;20000;REAL;MIL\n"
)

_ITR_BPA_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;99000;REAL;MIL\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1.02;Novo Campo ITR;5000;REAL;MIL\n"
)


def _zip_bytes(files: dict) -> bytes:
    """Create a ZIP in memory. files: {filename: content_str (latin-1 encoded)}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content.encode("latin-1"))
    return buf.getvalue()


def _make_cadastro_zip(tmp_path: str) -> str:
    path = os.path.join(tmp_path, "cia_aberta.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({"cia_aberta.csv": _CADASTRO_CSV}))
    return path


def _make_dfp_zip(tmp_path: str) -> str:
    path = os.path.join(tmp_path, "dfp_sample.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({"dfp_cia_aberta_2024_BPA.csv": _DFP_BPA_CSV}))
    return path


def _make_itr_zip(tmp_path: str) -> str:
    path = os.path.join(tmp_path, "itr_sample.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({"itr_cia_aberta_2024_BPA.csv": _ITR_BPA_CSV}))
    return path


def _init_db(db_path: str) -> None:
    from b3_storage.schema import SCHEMA_SQL
    from b3_storage.db import connect
    con = connect(db_path, read_only=False)
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            con.execute(stmt)
    con.close()


# ---------------------------------------------------------------------------
# Task 1: parse_companies
# ---------------------------------------------------------------------------

def test_parse_companies(tmp_path):
    zip_path = _make_cadastro_zip(str(tmp_path))
    result = parse_companies(zip_path)
    assert len(result) == 3
    cnpjs = {r["cnpj"] for r in result}
    assert "33.000.167/0001-01" in cnpjs
    assert "60.746.948/0001-12" in cnpjs
    assert "33.592.510/0001-03" in cnpjs
    petr = next(r for r in result if r["cnpj"] == "33.000.167/0001-01")
    assert petr["name"] == "PETROBRAS S.A."
    assert petr["cd_cvm"] == "9512"


# ---------------------------------------------------------------------------
# Task 2: parse_statements
# ---------------------------------------------------------------------------

from b3_etl.cvm import parse_statements
from datetime import date


def test_parse_statements_dfp(tmp_path):
    """Extrai registros DFP, normaliza ESCALA_MOEDA=MIL e filtra PENÚLTIMO."""
    zip_path = _make_dfp_zip(str(tmp_path))
    result = parse_statements(zip_path, "cvm_dfp")

    # Apenas ÚLTIMO: PETR4(1), PETR4(1.01), ITUB4(1), VALE3(1)  — sem PENÚLTIMO
    assert len(result) == 4
    petr_ativo = next(
        r for r in result
        if r["cnpj"] == "33.000.167/0001-01" and r["account_code"] == "1"
    )
    assert petr_ativo["report_type"] == "BPA"
    assert petr_ativo["period"] == date(2024, 12, 31)
    # 100000 × 1000 (MIL) = 100_000_000
    assert petr_ativo["value"] == 100_000_000.0
    assert petr_ativo["currency"] == "REAL"
    assert petr_ativo["source"] == "cvm_dfp"
    assert petr_ativo["account_name"] == "Ativo Total"


def test_parse_statements_filtra_penultimo(tmp_path):
    """ORDEM_EXERC='PENÚLTIMO' não é incluído no resultado."""
    zip_path = _make_dfp_zip(str(tmp_path))
    result = parse_statements(zip_path, "cvm_dfp")
    # O CSV tem 5 linhas ÚLTIMO e 1 PENÚLTIMO → resultado deve ter 4 (1 PETR4 account_code=1,
    # 1 PETR4 account_code=1.01, 1 ITUB4, 1 VALE3)
    penultimos = [r for r in result if r["account_code"] == "1" and r["cnpj"] == "33.000.167/0001-01"]
    # Deve haver exatamente 1 (o ÚLTIMO), não 2
    assert len(penultimos) == 1
    assert penultimos[0]["value"] == 100_000_000.0


_DFP_BPA_IND_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;50000;REAL;MIL\n"
)

_DFP_BPA_CON_CSV = (
    "CNPJ_CIA;DT_REFER;ORDEM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;MOEDA;ESCALA_MOEDA\n"
    "33.000.167/0001-01;2024-12-31;ÚLTIMO;1;Ativo Total;100000;REAL;MIL\n"
)


def test_parse_statements_prefere_con_sobre_ind(tmp_path):
    """Con (consolidado) deve prevalecer sobre ind (individual) para mesma PK."""
    path = os.path.join(str(tmp_path), "dfp_con_ind.zip")
    with open(path, "wb") as f:
        f.write(_zip_bytes({
            "dfp_cia_aberta_BPA_ind_2024.csv": _DFP_BPA_IND_CSV,
            "dfp_cia_aberta_BPA_con_2024.csv": _DFP_BPA_CON_CSV,
        }))
    result = parse_statements(path, "cvm_dfp")
    # Deve haver apenas 1 row (dedup por PK), com o valor do _con (100_000_000)
    assert len(result) == 1
    assert result[0]["value"] == 100_000_000.0


# ---------------------------------------------------------------------------
# Task 3: download_zip, _download_or_skip, run_ingest_cvm
# ---------------------------------------------------------------------------

from b3_etl.cvm import run_ingest_cvm
from b3_core.config import load_config
from b3_storage.db import connect


def _fake_download_factory(tmp_path: str):
    """Returns a fake download_zip that writes fixture ZIPs based on URL."""
    def _fake(url, dest_path, timeout=60):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        if "CAD" in url:
            content = _zip_bytes({"cia_aberta.csv": _CADASTRO_CSV})
        elif "DFP" in url:
            content = _zip_bytes({"dfp_cia_aberta_2024_BPA.csv": _DFP_BPA_CSV})
        else:  # ITR
            content = _zip_bytes({"itr_cia_aberta_2024_BPA.csv": _ITR_BPA_CSV})
        with open(dest_path, "wb") as f:
            f.write(content)
        return hashlib.sha256(content).hexdigest(), len(content)
    return _fake


def _make_config(tmp_path: str):
    config = load_config()
    db_path = os.path.join(tmp_path, "test.duckdb")
    _init_db(db_path)
    return config.__class__(
        **{
            **config.__dict__,
            "db_path": db_path,
            "raw_dir": os.path.join(tmp_path, "raw"),
        }
    )


def test_run_ingest_cvm_popula_tabelas(tmp_path):
    """run_ingest_cvm deve gravar cvm_companies e cvm_statements no DuckDB."""
    config = _make_config(str(tmp_path))
    with patch("b3_etl.cvm.download_zip", side_effect=_fake_download_factory(str(tmp_path))):
        rc = run_ingest_cvm(year=2024, include_itr=False, config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    companies = con.execute("SELECT COUNT(*) FROM cvm_companies").fetchone()[0]
    statements = con.execute("SELECT COUNT(*) FROM cvm_statements").fetchone()[0]
    raw = con.execute("SELECT COUNT(*) FROM raw_files WHERE source IN ('cvm_cadastro','cvm_dfp')").fetchone()[0]
    con.close()

    assert companies == 3
    assert statements == 4   # 4 linhas ÚLTIMO no DFP fixture
    assert raw == 2           # 1 cadastro + 1 dfp


def test_precedencia_dfp_sobre_itr(tmp_path):
    """ITR não deve sobrescrever registros DFP para o mesmo período."""
    config = _make_config(str(tmp_path))
    with patch("b3_etl.cvm.download_zip", side_effect=_fake_download_factory(str(tmp_path))):
        rc = run_ingest_cvm(year=2024, include_itr=True, config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    # DFP value para PETR4, BPA, conta 1 = 100_000_000
    row = con.execute(
        "SELECT value, source FROM cvm_statements "
        "WHERE cnpj = '33.000.167/0001-01' AND account_code = '1' AND report_type = 'BPA'"
    ).fetchall()
    con.close()

    # Deve haver apenas 1 registro (o DFP); o ITR para o mesmo (cnpj,period,report_type,account_code)
    # deve ter sido filtrado, mas o campo novo (1.02) do ITR pode estar presente
    dfp_rows = [r for r in row if r[1] == "cvm_dfp"]
    itr_rows_conta1 = [r for r in row if r[1] == "cvm_itr" and r[0] == 99_000_000.0]
    assert len(dfp_rows) == 1
    assert dfp_rows[0][0] == 100_000_000.0
    assert len(itr_rows_conta1) == 0  # ITR para conta_code=1 não inserido


def test_run_ingest_cvm_skip_download(tmp_path):
    """Segunda execução não deve chamar download_zip se checksum bate."""
    config = _make_config(str(tmp_path))
    fake = _fake_download_factory(str(tmp_path))
    call_count = {"n": 0}

    def counting_fake(url, dest_path, timeout=60):
        call_count["n"] += 1
        return fake(url, dest_path, timeout)

    with patch("b3_etl.cvm.download_zip", side_effect=counting_fake):
        run_ingest_cvm(year=2024, include_itr=False, config=config)
        first_calls = call_count["n"]
        run_ingest_cvm(year=2024, include_itr=False, config=config)
        second_calls = call_count["n"] - first_calls

    assert first_calls == 2    # cadastro + dfp
    assert second_calls == 0   # ambos pulados (checksum idêntico)


def test_run_ingest_cvm_falha_rede(tmp_path):
    """OSError no download → rc=0, erro logado, banco intacto."""
    config = _make_config(str(tmp_path))
    with patch("b3_etl.cvm.download_zip", side_effect=OSError("timeout")):
        rc = run_ingest_cvm(year=2024, include_itr=False, config=config)
    assert rc == 0

    con = connect(config.db_path, read_only=True)
    companies = con.execute("SELECT COUNT(*) FROM cvm_companies").fetchone()[0]
    con.close()
    assert companies == 0  # nada gravado, mas sem crash
