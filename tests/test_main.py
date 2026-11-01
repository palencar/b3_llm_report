from unittest.mock import patch

import pytest

import main


@pytest.mark.parametrize("flags", [[], ["--unified"]])
@pytest.mark.parametrize("failed", [[], ["unified"]])
def test_comando_sempre_imprime_unificado_uma_vez(flags, failed, capsys):
    result = {"results": {"unified": {}}, "failed_modes": failed}
    with patch("sys.argv", ["main.py", "wege3", *flags]), \
         patch("main.run_aligned", return_value=result) as run, \
         patch("main.format_report_markdown", return_value="Relatorio unico."):
        assert main.main() == bool(failed)
    run.assert_called_once_with("WEGE3", snapshot_path=None)
    assert capsys.readouterr().out.count("Relatorio unico.") == 1


@pytest.mark.parametrize("flags", [[], ["--unified"]])
@pytest.mark.parametrize("snapshot_flag", ["--snapshot", "--decision-snapshot"])
def test_snapshot_e_structured_output_nao_exigem_flag_unified(flags, snapshot_flag):
    with patch("sys.argv", ["main.py", "WEGE3", *flags, "--structured-output", "on",
                            snapshot_flag, "snapshot.json"]), \
         patch("main.run_aligned", return_value={"results": {}, "failed_modes": []}) as run:
        assert main.main() == 0
    run.assert_called_once_with("WEGE3", snapshot_path="snapshot.json", structured_output=True)


@pytest.mark.parametrize("args", [
    ["--decision-model", "modelo"], ["--with-report"], ["--decision-report", "relatorio.md"],
    ["--structured-output", "invalido"],
])
def test_flags_removidas_ou_invalidas_nao_executam(args):
    with patch("sys.argv", ["main.py", "WEGE3", *args]), patch("main.run_aligned") as run:
        with pytest.raises(SystemExit) as exc:
            main.main()
    assert exc.value.code == 2
    run.assert_not_called()
