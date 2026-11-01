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
