from datetime import datetime

from b3_report.reports import (
    get_recent_reports_history,
    save_report_snapshot,
    write_report_file_atomic,
)


def test_get_recent_reports_history_retorna_mais_recentes(tmp_path):
    report_dir = tmp_path / "reports"
    history_dir = report_dir / "PETR4"
    history_dir.mkdir(parents=True)
    (history_dir / "2026-03-20_090000.md").write_text("Relatorio 20", encoding="utf-8")
    (history_dir / "2026-03-21_090000.md").write_text("Relatorio 21", encoding="utf-8")
    (history_dir / "2026-03-22_090000.md").write_text("Relatorio 22", encoding="utf-8")

    result = get_recent_reports_history("PETR4", report_dir=str(report_dir), n=2)

    assert "Relatorio 22" in result
    assert "Relatorio 21" in result
    assert "Relatorio 20" not in result
    assert result.index("Relatorio 22") < result.index("Relatorio 21")


def test_get_recent_reports_history_ignora_nome_fora_do_contrato(tmp_path, caplog):
    report_dir = tmp_path / "reports"
    history_dir = report_dir / "PETR4"
    history_dir.mkdir(parents=True)
    (history_dir / "invalido.md").write_text("conteudo", encoding="utf-8")

    result = get_recent_reports_history("PETR4", report_dir=str(report_dir), n=2)

    assert result == ""
    assert "Arquivo de historico ignorado por nome fora do contrato" in caplog.text


def test_save_report_snapshot_cria_arquivo_versionado(tmp_path):
    report_dir = tmp_path / "reports"

    snapshot_path = save_report_snapshot(
        ticker="PETR4",
        content="relatorio",
        analysis_timestamp=datetime(2026, 3, 26, 8, 15, 0),
        report_dir=str(report_dir),
    )

    assert snapshot_path == report_dir / "_history" / "PETR4" / "2026-03-26_081500.md"
    assert snapshot_path.read_text(encoding="utf-8") == "relatorio"


def test_write_report_file_atomic_sobrescreve_arquivo_final(tmp_path):
    target_path = tmp_path / "reports" / "PETR4.md"
    target_path.parent.mkdir(parents=True)
    target_path.write_text("conteudo antigo", encoding="utf-8")

    write_report_file_atomic(target_path, "conteudo novo")

    assert target_path.read_text(encoding="utf-8") == "conteudo novo"


def test_save_report_snapshot_usa_diretorio_alternativo_quando_arquivo_legado_existe(tmp_path, caplog):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "MXRF11").write_text("legado", encoding="utf-8")

    snapshot_path = save_report_snapshot(
        ticker="MXRF11",
        content="relatorio",
        analysis_timestamp=datetime(2026, 4, 21, 11, 39, 11),
        report_dir=str(report_dir),
    )

    assert snapshot_path == report_dir / "_history" / "MXRF11" / "2026-04-21_113911.md"
    assert "conflita com arquivo existente" in caplog.text


def test_get_recent_reports_history_usa_arquivo_corrente_quando_nao_ha_snapshots(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "MXRF11.md").write_text("relatorio corrente", encoding="utf-8")

    result = get_recent_reports_history("MXRF11", report_dir=str(report_dir), n=4)

    assert "relatorio corrente" in result
    assert "MXRF11.md" in result
