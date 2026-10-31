from types import SimpleNamespace
from datetime import datetime
from unittest.mock import patch

import httpx
import pytest

from b3_report.llm import (
    LLMConfigurationError,
    LLMRequestError,
    LLMResponseError,
    LLMResponse,
    get_investment_analysis,
    validate_llm_config,
)


@pytest.mark.parametrize("openai_url,ollama_url", [
    ("", ""),
    ("http://openai/v1", "http://ollama"),
])
def test_urls_ausentes_ou_ambiguas_nao_fazem_chamada(openai_url, ollama_url):
    with patch("b3_report.llm.OpenAI") as openai, patch("b3_report.llm.httpx.Client") as ollama:
        with pytest.raises(LLMConfigurationError, match="exatamente uma"):
            get_investment_analysis("prompt", "modelo", openai_url, ollama_url)
    openai.assert_not_called()
    ollama.assert_not_called()


def test_modelo_obrigatorio():
    with pytest.raises(LLMConfigurationError, match="LLM_MODEL"):
        validate_llm_config(" ", "http://servidor/v1", "")


@pytest.mark.parametrize("openai_url,ollama_url", [
    ("http://servidor/v1", ""), ("", "http://servidor"),
])
def test_relatorio_encaminha_configuracao_ao_cliente(tmp_path, monkeypatch, openai_url, ollama_url):
    from b3_report.cli import run_report

    monkeypatch.chdir(tmp_path)
    config = SimpleNamespace(llm_api_key="chave-simulada", llm_model="modelo-simulado",
                             openai_url_base=openai_url, ollama_url_base=ollama_url,
                             db_path=str(tmp_path / "ausente.duckdb"), fund_ttl=86400,
                             report_history_n=4, corporate_events_file="", raw_dir=str(tmp_path / "raw"))
    text = ("#### Identificação\n- Empresa: Empresa simulada\n- Data da Análise: "
            + datetime.now().strftime("%Y-%m-%d")
            + "\n#### Resumo\n##### Curtíssimo Prazo\n##### Curto Prazo\n##### Médio Prazo\n")
    with patch("b3_report.cli.load_dotenv"), \
         patch("b3_report.cli.load_config", return_value=config), \
         patch("b3_report.cli.get_yfinance_data", return_value=""), \
         patch("b3_report.cli.get_complementary_data", return_value=""), \
         patch("b3_report.cli.get_cvm_data", return_value=""), \
         patch("b3_report.cli.prepare_llm_investment_analysis_request", return_value="PROMPT"), \
         patch("b3_report.cli.get_investment_analysis", return_value=text) as sender:
        assert run_report("petr4") == text
    sender.assert_called_once_with("PROMPT", api_key="chave-simulada",
                                   model="modelo-simulado", openai_url_base=openai_url,
                                   ollama_url_base=ollama_url)
    assert (tmp_path / "reports" / "PETR4.md").read_text(encoding="utf-8") == text


def test_relatorio_rejeita_configuracao_ambigua_antes_da_coleta():
    from b3_report.cli import run_report

    config = SimpleNamespace(llm_model="modelo", openai_url_base="http://servidor/v1",
                             ollama_url_base="http://servidor")
    with patch("b3_report.cli.load_dotenv"), \
         patch("b3_report.cli.load_config", return_value=config), \
         patch("b3_report.cli.get_yfinance_data") as source:
        with pytest.raises(LLMConfigurationError, match="exatamente uma"):
            run_report("PETR4")
    source.assert_not_called()


def test_ollama_envia_esquema_e_preserva_metadados_sem_mudar_texto(capsys):
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    payload = {"model": "modelo", "message": {"content": '{"ok":true}'},
               "done": True, "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 5}
    with patch("b3_report.llm.httpx.Client") as factory:
        factory.return_value.post.return_value = httpx.Response(
            200, json=payload, request=httpx.Request("POST", "http://servidor/api/chat"))
        result = get_investment_analysis("prompt", "modelo", ollama_url_base="http://servidor",
                                         response_schema=schema, with_metadata=True)
    body = factory.return_value.post.call_args.kwargs["json"]
    assert body["format"] == schema
    assert isinstance(result, LLMResponse)
    assert result.content == '{"ok":true}'
    assert result.metadata == {"provider": "Ollama", **{k: v for k, v in payload.items() if k != "message"}}
    factory.return_value.close.assert_called_once()
    assert "entrada=12; saida=5; total=17" in capsys.readouterr().out


def test_openai_envia_response_format_e_preserva_encerramento(capsys):
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    with patch("b3_report.llm.OpenAI") as factory:
        client = factory.return_value
        client.chat.completions.create.return_value = SimpleNamespace(
            model="modelo-retornado", choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"ok":true}'), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5, total_tokens=17))
        result = get_investment_analysis("prompt", "modelo", openai_url_base="http://servidor/v1",
                                         response_schema=schema, with_metadata=True)
    assert client.chat.completions.create.call_args.kwargs["response_format"] == {
        "type": "json_schema", "json_schema": {"name": "b3_assessment", "strict": True, "schema": schema}}
    assert result.content == '{"ok":true}'
    assert result.metadata["finish_reason"] == "stop"
    assert result.metadata["usage"]["total_tokens"] == 17
    assert "entrada=12; saida=5; total=17" in capsys.readouterr().out


def test_tokens_ollama_impressos_mesmo_sem_texto_valido(capsys):
    with patch("b3_report.llm.httpx.Client") as factory:
        factory.return_value.post.return_value = httpx.Response(
            200, json={"message": {"content": ""}, "prompt_eval_count": 8, "eval_count": 0},
            request=httpx.Request("POST", "http://servidor/api/chat"))
        with pytest.raises(LLMResponseError):
            get_investment_analysis("prompt", "modelo", ollama_url_base="http://servidor")
    assert "entrada=8; saida=0; total=8" in capsys.readouterr().out


def test_rejeicao_de_format_nao_refaz_chamada_sem_esquema(capsys):
    with patch("b3_report.llm.httpx.Client") as factory:
        factory.return_value.post.return_value = httpx.Response(
            400, json={"error": "format nao suportado"},
            request=httpx.Request("POST", "http://servidor/api/chat"))
        with pytest.raises(LLMRequestError, match="format nao suportado"):
            get_investment_analysis("prompt", "modelo", ollama_url_base="http://servidor",
                                    response_schema={"type": "object"})
    factory.return_value.post.assert_called_once()
    assert factory.return_value.post.call_args.kwargs["json"]["format"] == {"type": "object"}
    out = capsys.readouterr().out
    assert out.count("Tokens da chamada") == 1
    assert "total=indisponivel" in out


@pytest.mark.parametrize("schema", [[], "json", {}])
def test_esquema_invalido_falha_antes_da_chamada(schema):
    with patch("b3_report.llm.httpx.Client") as factory:
        with pytest.raises(LLMConfigurationError, match="JSON Schema"):
            get_investment_analysis("prompt", "modelo", ollama_url_base="http://servidor",
                                    response_schema=schema)
    factory.assert_not_called()


def test_openai_usa_chat_completions_e_fecha_cliente():
    with patch("b3_report.llm.OpenAI") as factory, patch("b3_report.llm.httpx.Client") as ollama:
        client = factory.return_value
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="relatorio"))]
        )
        result = get_investment_analysis(
            "prompt", "modelo", openai_url_base="http://servidor/v1", api_key="chave",
        )
    assert result == "relatorio"
    assert factory.call_args.kwargs["api_key"] == "chave"
    assert factory.call_args.kwargs["max_retries"] == 0
    client.chat.completions.create.assert_called_once_with(
        model="modelo", messages=[{"role": "user", "content": "prompt"}],
        temperature=0.2, stream=False,
    )
    client.close.assert_called_once()
    ollama.assert_not_called()


@pytest.mark.parametrize("key", ["", "chave"])
def test_ollama_usa_endpoint_nativo_e_autenticacao_opcional(key):
    with patch("b3_report.llm.httpx.Client") as factory, patch("b3_report.llm.OpenAI") as openai:
        client = factory.return_value
        client.post.return_value = httpx.Response(
            200, json={"message": {"content": "relatorio", "thinking": "raciocinio"}},
            request=httpx.Request("POST", "http://servidor/api/chat"),
        )
        result = get_investment_analysis(
            "prompt", "modelo", ollama_url_base="http://servidor/", api_key=key,
        )
    assert result == "relatorio"
    assert factory.call_args.kwargs["headers"] == ({"Authorization": f"Bearer {key}"} if key else {})
    client.post.assert_called_once_with("http://servidor/api/chat", json={
        "model": "modelo", "messages": [{"role": "user", "content": "prompt"}],
        "stream": False, "options": {"temperature": 0.2},
    })
    client.close.assert_called_once()
    openai.assert_not_called()


@pytest.mark.parametrize("payload", [[], {}, {"message": None}, {"message": {}}, {"message": {"content": " "}}])
def test_ollama_rejeita_resposta_invalida(payload):
    with patch("b3_report.llm.httpx.Client") as factory:
        client = factory.return_value
        client.post.return_value = httpx.Response(
            200, json=payload, request=httpx.Request("POST", "http://servidor/api/chat"),
        )
        with pytest.raises(LLMResponseError):
            get_investment_analysis("prompt", "modelo", ollama_url_base="http://servidor")
    client.close.assert_called_once()


def test_ollama_erro_http_nao_tenta_openai():
    with patch("b3_report.llm.httpx.Client") as factory, patch("b3_report.llm.OpenAI") as openai:
        client = factory.return_value
        client.post.return_value = httpx.Response(
            404, json={"error": "modelo ausente"},
            request=httpx.Request("POST", "http://servidor/api/chat"),
        )
        with pytest.raises(LLMRequestError, match="endpoint Ollama: HTTP 404.*modelo ausente"):
            get_investment_analysis("prompt", "modelo", ollama_url_base="http://servidor")
    client.close.assert_called_once()
    openai.assert_not_called()


@pytest.mark.parametrize("payload, expected", [
    ({"error": {"message": "Modelo nao encontrado."}}, "Modelo nao encontrado."),
    ({"error": ""}, "sem mensagem"),
    ({"outro": "campo"}, "sem mensagem reconhecida"),
])
def test_ollama_detalhe_http_json(payload, expected):
    with patch("b3_report.llm.httpx.Client") as factory:
        client = factory.return_value
        client.post.return_value = httpx.Response(
            404, json=payload, request=httpx.Request("POST", "http://servidor/api/chat"))
        with pytest.raises(LLMRequestError, match=expected):
            get_investment_analysis("prompt", "modelo", ollama_url_base="http://servidor")
    client.post.assert_called_once()
    client.close.assert_called_once()


def test_ollama_detalhe_http_texto_limitado_sem_chave():
    secret = "segredo-simulado"
    with patch("b3_report.llm.httpx.Client") as factory:
        client = factory.return_value
        client.post.return_value = httpx.Response(
            404, text=f"Falha\n{secret} " + "x" * 1000,
            request=httpx.Request("POST", "http://servidor/api/chat"))
        with pytest.raises(LLMRequestError) as caught:
            get_investment_analysis("prompt", "modelo", ollama_url_base="http://servidor", api_key=secret)
    assert secret not in str(caught.value)
    assert "[chave omitida]" in str(caught.value)
    assert "\n" not in str(caught.value)
    assert str(caught.value).endswith("...")
    assert len(str(caught.value)) < 650
    client.close.assert_called_once()
