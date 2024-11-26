import argparse
import os
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from get_info_yfinance import get_yfinance_data
from get_info_crawl4ai import get_complementary_data
from prepare_request import prepare_llm_investment_analysis_request


def get_investment_analysis(prompt, model="llama3.1", base_url="http://localhost:11434/v1", api_key="api_key"):
    """
    Faz uma chamada ao Ollama local usando o cliente OpenAI

    Args:
        prompt (str): Prompt completo para análise
        model (str): Nome do modelo no Ollama (default: "llama3.1")
        base_url (str): URL base do Ollama (default: "http://localhost:11434/v1")
        api_key (str): API key (default: "api_key" para Ollama local)

    Returns:
        str: Resposta do modelo
    """
    client = None
    try:
        # Inicializa o cliente OpenAI apontando para Ollama
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=300.0
        )

        # Faz a chamada
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,  # Ajuste conforme necessidade
            stream=False
        )

        # Retorna o conteúdo da resposta
        return response.choices[0].message.content

    except Exception as e:
        return f"Erro ao fazer chamada ao Ollama: {str(e)}"

    finally:
        if client:
            client.close()  # Fecha a conexão

if __name__ == '__main__':
    # Prepara a data no formato ISO 8601
    analysis_date = datetime.now().strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description='Script para processar símbolos de negociação.')
    parser.add_argument('symbol', type=str, help='Símbolo de negociação (exemplo: PETR4, VALE3)')

    args = parser.parse_args()
    symbol = args.symbol.upper()

    print(f"Processando símbolo: {symbol}")
    # Aqui você pode adicionar sua lógica de processamento
    print(f"Símbolo processado com sucesso: {symbol}")

    load_dotenv()

    yfinance_report = get_yfinance_data(f'{symbol}.SA')
    complementary_report = get_complementary_data(symbol)

    # Prepara o prompt completo para o LLM
    llm_prompt = prepare_llm_investment_analysis_request(
        yfinance_report,
        complementary_report,
        analysis_date
    )

    analysis = get_investment_analysis(llm_prompt,
                                       api_key=os.getenv('OPENAI_API_KEY'),
                                       base_url=os.getenv('OPENAI_URL_BASE'),
                                       model=os.getenv('OPENAI_MODEL_NAME'))

    print(analysis)

    os.makedirs(f"reports", exist_ok=True)

    with open(os.path.join("reports", f"{symbol}.md"), 'w') as file:
        file.write(analysis)
