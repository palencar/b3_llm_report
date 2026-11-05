from contextlib import contextmanager
from tempfile import NamedTemporaryFile
from unittest.mock import patch

import pytest

from b3_report.reports import write_report_file_atomic


def test_escrita_atomica_cria_diretorio_e_publica(tmp_path):
    path = tmp_path / "reports" / "WEGE3.md"
    assert write_report_file_atomic(path, "Novo relatorio") == path
    assert path.read_text(encoding="utf-8") == "Novo relatorio"
    assert list(path.parent.iterdir()) == [path]


def test_escrita_atomica_sobrescreve_publicacao(tmp_path):
    path = tmp_path / "WEGE3.md"
    path.write_text("Anterior", encoding="utf-8")
    write_report_file_atomic(path, "Atual")
    assert path.read_text(encoding="utf-8") == "Atual"


def test_falha_na_substituicao_preserva_publicacao_e_limpa_temporario(tmp_path):
    path = tmp_path / "WEGE3.md"
    path.write_text("Anterior", encoding="utf-8")
    with patch("b3_report.reports.os.replace", side_effect=OSError("Falha simulada")):
        with pytest.raises(OSError, match="Falha simulada"):
            write_report_file_atomic(path, "Atual")
    assert path.read_text(encoding="utf-8") == "Anterior"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("stage", ["write", "flush", "fsync"])
@pytest.mark.parametrize("existing", [False, True])
def test_falha_durante_escrita_limpa_temporario(tmp_path, monkeypatch, stage, existing):
    path = tmp_path / "WEGE3.md"
    if existing:
        path.write_text("Anterior", encoding="utf-8")
    def fail(*args):
        raise OSError("Falha simulada em " + stage)
    @contextmanager
    def temporary(*args, **kwargs):
        with NamedTemporaryFile(*args, **kwargs) as handle:
            if stage in ("write", "flush"):
                monkeypatch.setattr(handle, stage, fail)
            yield handle
    monkeypatch.setattr("b3_report.reports.tempfile.NamedTemporaryFile", temporary)
    if stage == "fsync":
        monkeypatch.setattr("b3_report.reports.os.fsync", fail)
    with pytest.raises(OSError, match="Falha simulada"):
        write_report_file_atomic(path, "Atual")
    if existing:
        assert path.read_text(encoding="utf-8") == "Anterior"
    else:
        assert not path.exists()
    assert list(tmp_path.iterdir()) == ([path] if existing else [])
