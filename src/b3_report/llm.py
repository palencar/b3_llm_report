from openai import OpenAI
import httpx
from urllib.parse import urlsplit
from dataclasses import dataclass
from b3_report.token_usage import report_token_usage


@dataclass(frozen=True)
class LLMResponse:
    content: str
    metadata: dict


class LLMError(RuntimeError):
    """Erro base do fluxo de chamada ao LLM."""


class LLMRequestError(LLMError):
    """Erro operacional ao chamar o endpoint do LLM."""


class LLMResponseError(LLMError):
    """Erro de resposta estrutural do endpoint do LLM."""


class LLMConfigurationError(LLMError):
    """Configuracao ausente ou ambigua do endpoint LLM."""


def validate_llm_config(model: str, openai_url_base: str, ollama_url_base: str) -> None:
    if bool(openai_url_base.strip()) == bool(ollama_url_base.strip()):
        raise LLMConfigurationError(
            "Defina exatamente uma URL: OPENAI_URL_BASE ou OLLAMA_URL_BASE."
        )
    if not model.strip():
        raise LLMConfigurationError("Defina LLM_MODEL com o nome do modelo.")
    url = urlsplit((openai_url_base or ollama_url_base).strip())
    if url.scheme not in ("http", "https") or not url.hostname or url.query or url.fragment:
        raise LLMConfigurationError("A URL base do LLM deve ser HTTP ou HTTPS, sem query ou fragmento.")


def get_investment_analysis(
    prompt: str,
    model: str,
    openai_url_base: str = "",
    ollama_url_base: str = "",
    api_key: str = "",
    *,
    response_schema: dict | None = None,
    with_metadata: bool = False,
) -> str | LLMResponse:
    validate_llm_config(model, openai_url_base, ollama_url_base)
    if response_schema is not None and (not isinstance(response_schema, dict) or not response_schema):
        raise LLMConfigurationError("Structured output exige um JSON Schema nao vazio.")
    provider = "OpenAI" if openai_url_base.strip() else "Ollama"
    client = None
    attempted = False
    tokens = {}
    try:
        messages = [{"role": "user", "content": prompt}]
        metadata = {"provider": provider}
        if provider == "OpenAI":
            # O SDK exige uma chave mesmo para endpoints locais sem autenticacao.
            client = OpenAI(
                base_url=openai_url_base.strip(),
                api_key=api_key or "sem-chave",
                timeout=7200.0,
                max_retries=0,
            )
            extra = {}
            if response_schema is not None:
                extra["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "b3_assessment", "strict": True, "schema": response_schema}}
            attempted = True
            response = client.chat.completions.create(
                model=model, messages=messages, temperature=0.2, stream=False,
                **extra,
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                tokens = {"input_tokens": getattr(usage, "prompt_tokens", None),
                          "output_tokens": getattr(usage, "completion_tokens", None),
                          "total_tokens": getattr(usage, "total_tokens", None)}
            if not response.choices:
                raise LLMResponseError("Resposta OpenAI sem alternativas de resposta.")
            content = response.choices[0].message.content
            if with_metadata:
                metadata["model"] = getattr(response, "model", None)
                metadata["finish_reason"] = getattr(response.choices[0], "finish_reason", None)
                if usage is not None:
                    metadata["usage"] = {key: getattr(usage, key, None) for key in
                                         ("prompt_tokens", "completion_tokens", "total_tokens")}
        else:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            client = httpx.Client(timeout=7200.0, headers=headers)
            body = {"model": model, "messages": messages, "stream": False,
                    "options": {"temperature": 0.2}}
            if response_schema is not None:
                body["format"] = response_schema
            attempted = True
            response = client.post(
                f"{ollama_url_base.strip().rstrip('/')}/api/chat",
                json=body,
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise LLMResponseError("Resposta Ollama com JSON invalido.") from exc
            if isinstance(payload, dict):
                tokens = {"input_tokens": payload.get("prompt_eval_count"),
                          "output_tokens": payload.get("eval_count")}
            if not isinstance(payload, dict) or not isinstance(payload.get("message"), dict):
                raise LLMResponseError("Resposta Ollama sem campo message valido.")
            if payload.get("error"):
                raise LLMResponseError("Ollama retornou um erro na resposta.")
            content = payload["message"].get("content")
            if with_metadata:
                metadata.update({key: payload[key] for key in (
                    "model", "done", "done_reason", "prompt_eval_count", "eval_count",
                    "total_duration", "load_duration", "prompt_eval_duration", "eval_duration",
                ) if key in payload})
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError(f"Resposta {provider} sem conteudo textual valido.")
        return LLMResponse(content, metadata) if with_metadata else content
    except LLMError:
        raise
    except httpx.HTTPStatusError as exc:
        try:
            payload = exc.response.json()
        except ValueError:
            detail = exc.response.text
        else:
            error = payload.get("error") if isinstance(payload, dict) else None
            detail = error.get("message") if isinstance(error, dict) else error
            if not isinstance(detail, str):
                detail = "Resposta de erro sem mensagem reconhecida."
        if api_key:
            detail = detail.replace(api_key, "[chave omitida]")
        detail = " ".join(detail.split()) or "Resposta de erro sem mensagem."
        detail = detail[:512] + ("..." if len(detail) > 512 else "")
        raise LLMRequestError(
            f"Erro ao fazer chamada ao endpoint {provider}: HTTP {exc.response.status_code}. "
            f"Detalhe do servidor: {detail}"
        ) from exc
    except Exception as exc:
        raise LLMRequestError(f"Erro ao fazer chamada ao endpoint {provider}: {exc}") from exc
    finally:
        if attempted:
            report_token_usage(provider, model, **tokens)
        if client:
            client.close()
