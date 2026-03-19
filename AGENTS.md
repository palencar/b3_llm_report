# AGENTS

## Escopo
Este repositório gera relatórios de ações da B3 combinando dados do `yfinance`, scraping com `crawl4ai` do Fundamentus e análise via LLM local (Ollama/OpenAI compatível).
Fontes canônicas de setup e operação: `README.md` e `PRD - *.md`.

## Regras de trabalho
- Trabalhar em mudanças pequenas e incrementais, com foco em simplicidade e robustez.
- Evitar alterações fora de escopo; não fazer refatoração ou formatação cosmética sem relação direta com o problema.
- Antes de editar código, entender a causa raiz e definir um plano curto de ação.
- Preferir caminhos determinísticos e auditáveis; não introduzir fallbacks automáticos ou silenciosos.
- Quando houver entrada fora de contrato, registrar em log em português brasileiro com o contexto mínimo útil.
- Evitar novas dependências de runtime; tooling adicional deve ficar isolado do fluxo principal.
- Manter mensagens, prompts e logs gerados pelo assistente em português brasileiro claro e direto.

## Configuração e operação
- Variáveis de ambiente no `.env` (ver `README.md`).
- Execução local: `python main.py <TICKER>`.

## Validação
- Não há suíte de testes dedicada.
- Ao alterar código, rode `python -m py_compile` nos arquivos modificados ou execute o fluxo manual relevante.

## Mudanças sensíveis
- Para ajustes em prompts ou regras de análise, seguir: `baseline -> proposta -> benchmark no mesmo corpus -> decisão por métricas`.
