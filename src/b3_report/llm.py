from openai import OpenAI


def get_investment_analysis(
    prompt: str,
    model: str = "llama3.1",
    base_url: str = "http://localhost:11434/v1",
    api_key: str = "api_key",
) -> str:
    client = None
    try:
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=300.0,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            stream=False,
        )
        return response.choices[0].message.content
    except Exception as exc:
        return f"Erro ao fazer chamada ao Ollama: {exc}"
    finally:
        if client:
            client.close()
