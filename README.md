# b3_llm_report

> **Projeto experimental.** Relatorios e classificacoes nao constituem recomendacao de investimento nem orientacao financeira personalizada. Leia o [aviso de uso e limitacoes](AVISO.md) antes de usar os resultados.

Projeto experimental para análise de ações da B3 com duas frentes complementares:

- pipeline de relatorio com yfinance, Fundamentus, dados CVM disponiveis no banco e LLM via API compativel com OpenAI ou Ollama, local ou remoto;
- ETL de yfinance/Fundamentus e ingestao separada de demonstrativos CVM em DuckDB, com brutos e snapshots Parquet. BRAPI esta desabilitada no ETL atual.

## Estrutura atual

- `main.py`: comando do relatorio unificado, com classificacoes e frontmatter.
- `relatorio`: consulta de Markdown publicado e solicitacao pela fila, sem executar o modelo.
- `init_db.py`: inicializa o schema DuckDB local.
- `ingest.py`: ETL de yfinance e Fundamentus.
- `ingest_cvm.py`: ingestao de cadastro e demonstrativos CVM (DFP/ITR).
- `src/b3_report/`: pipeline de relatório.
- `src/b3_etl/`: ingestao de fontes e demonstrativos.
- `src/b3_storage/`: schema e acesso ao DuckDB.
- `scripts/`: scripts de demo e validação.

## Ambiente

Use um ambiente virtual Python:

```bash
python -m venv venv
source venv/bin/activate
```

Instale o conjunto unico de dependencias de relatorio e ETL:

```bash
pip install -r requirements.txt
```

`requirements.txt` e a fonte comum das dependencias de runtime. `requirements-docker.txt` inclui esse arquivo e fixa versoes adicionais para a imagem; `requirements-dev.txt` inclui o perfil Docker e acrescenta pytest. O antigo requirements-etl.txt foi consolidado no principal.

O yfinance esta fixado em 1.2.0, alinhado ao ambiente do host em que a coleta funcionou. A imagem anterior usava 0.2.49. A atualizacao exige reconstruir a imagem e recriar o container; nao garante eliminar limites HTTP 429 do Yahoo.

DuckDB esta fixado em 1.5.3, tambem alinhado ao host. Ao compartilhar o mesmo banco entre host e container, mantenha as versoes alinhadas: um leitor antigo pode falhar ao abrir um arquivo gravado por uma versao mais nova. Antes de usar uma imagem atualizada com dados existentes, pare os processos que acessam o banco e faca backup dos dados com o banco fechado. Erros de desserializacao nao devem ser tratados apagando ou reinicializando o banco automaticamente.

Copie `.env.example` para `.env` e ajuste apenas o que for necessario para o fluxo que vai executar. O exemplo rastreado contem somente `OLLAMA_URL_BASE`, `LLM_MODEL` e `LLM_API_KEY`, sem endereco ou modelo padrao e sem credenciais reais. As demais configuracoes opcionais e seus padroes estao documentados abaixo.

## Consultar um relatorio existente

A consulta usa apenas Python 3 e o arquivo publicado, sem carregar `.env`, dependencias do gerador, banco ou Docker. Funciona com o container parado:

```bash
./relatorio consultar WEGE3
./relatorio consultar WEGE3 --somente-conteudo
./relatorio consultar WEGE3 --somente-caminho
./relatorio consultar WEGE3 --diretorio-relatorios ./dados-compartilhados/reports
```

O diretorio padrao e `reports/` relativo ao diretorio atual do host. O caminho alternativo deve ser o do host, nao o caminho interno do container. Por padrao, o Markdown completo, incluindo frontmatter, vai para stdout e o caminho absoluto vai para stderr. `--somente-conteudo` suprime o caminho; `--somente-caminho` imprime apenas o caminho em stdout. As duas opcoes sao mutuamente exclusivas. Ausencia ou falha de leitura retorna codigo 1, sem gerar um relatorio.

Consultar nao altera a fila ou o estado do gerador.

## Solicitar atualizacao pela fila

No host Linux, com o checkout do projeto e Python 3, use:

```bash
./relatorio gerar WEGE3
./relatorio gerar WEGE3 --diretorio-fila ./dados-compartilhados/queue
```

O comando usa apenas a biblioteca padrao, nao le `.env` nem chama Docker, fontes ou modelo. O diretorio padrao e `queue/` no diretorio atual; informe `--diretorio-fila` quando necessario para apontar ao mesmo mount do watcher. A consulta pode ser usada isoladamente; gerar tambem precisa dos modulos em `src/` que acompanham o executavel neste checkout.

Gerar registra uma atualizacao obrigatoria e retorna imediatamente, sem imprimir um relatorio antigo como resposta ao pedido. O watcher ignora a idade minima do relatorio e a expiracao de alertas para esse pedido, mas mantem ordem circular, intervalos e cooldown. Alertas automaticos mantem as regras anteriores. Com o container parado, o pedido continua persistido ate o watcher processa-lo; o comando nao verifica nem inicia o servico, e informa essa limitacao.

Pedidos repetidos antes do processamento sao agrupados por ativo. O comando aguarda o controle curto de registro e elegibilidade; essa espera nao abrange coleta ou chamada ao modelo. Se a geracao ja estiver reservada ou em andamento, informa o processamento e nao cria outra solicitacao. O watcher reserva a geracao antes de liberar o controle curto, evitando perder pedidos na transicao. Os bloqueios sao liberados pelo sistema operacional ao encerrar o processo, inclusive se ficar um estado JSON pendente. Uma pendencia anterior e retomada no snapshot preservado, sem recoleta ou descarte silencioso; configuracao incompativel continua exigindo intervencao.

O pedido fica em `queue/.requests/<ATIVO>.json` e so e removido apos sucesso ou confirmacao de que ja foi atendido. Falhas preservam pedido e relatorio anterior. O identificador no estado evita repetir uma geracao concluida se houver interrupcao antes de remover o pedido. `queue/.locks/<ATIVO>` coordena a geracao e `queue/.locks/<ATIVO>.request` coordena o controle curto; sao arquivos vazios e nao devem ser removidos enquanto houver processos usando a fila. Isso exige filesystem local com suporte a `flock`, compartilhado pelos containers, e permissao de escrita nesses subdiretorios para ambos os usuarios. Atualize o comando do host e o watcher para a mesma revisao.

Codigo 0 indica pedido registrado, ja pendente ou ativo em processamento (conforme a mensagem), nao conclusao de geracao; falhas de registro retornam 1. A geracao direta permanece em `python main.py ATIVO` e continua exigindo parar o watcher se usar os mesmos dados, conforme o procedimento Docker abaixo. Nao execute multiplos watchers sobre a mesma instalacao.

## Docker

A imagem unica inclui relatorios, fila e ETL. O comando padrao e `python watch_queue.py`. O endpoint LLM e externo ao gerador e deve estar acessivel de dentro do container, nao apenas pelo host de destino.

Construa a imagem na raiz do projeto:

```bash
docker build -t b3-llm-report:local .
```

Para transferir a imagem sem registry:

```bash
docker save -o b3-llm-report.tar b3-llm-report:local
scp b3-llm-report.tar usuario@host-destino:/tmp/
```

No host de destino:

```bash
docker load -i /tmp/b3-llm-report.tar
mkdir -p data reports queue
```

A arquitetura da imagem precisa corresponder a do host de destino. O build acima usa a arquitetura local; para outra arquitetura, use um builder com suporte a ela e informe, por exemplo, `--platform linux/arm64` no build.

Prepare `.env` no host de destino a partir de `.env.example`. Informe `OPENAI_URL_BASE` com o endereco real da API compativel com OpenAI, incluindo `/v1`, ou `OLLAMA_URL_BASE` com o endereco da API nativa Ollama, sem `/api/chat`. Na API nativa, nao acrescente `/v1`: o cliente adiciona `/api/chat`. Defina apenas uma URL e informe `LLM_MODEL` com o nome do modelo disponivel no servidor escolhido. Se exigir autenticacao, use `LLM_API_KEY`, enviada como Bearer token; o projeto nao le `OLLAMA_API_KEY`.

### Acesso ao servidor de modelos

Nao existe nome de rede, container Ollama ou host obrigatorio para este projeto. Escolha a URL e as opcoes do `docker run` conforme a instalacao:

| Onde esta o servidor | Exemplo de `OLLAMA_URL_BASE` | Opcoes e requisitos |
| --- | --- | --- |
| Outro container na mesma rede Docker definida pelo usuario | `http://servico-ollama:11434` | Acrescente `--network NOME_DA_REDE_EXISTENTE`; ambos precisam estar nessa rede. Use nome/alias do servidor e porta interna, sem exigir publicacao no host. |
| No host Docker, acessivel por endereco roteavel | `http://host-modelos.exemplo:11434` | Use DNS/IP e porta acessiveis pelo container; nao exige uma rede Docker de nome especifico. |
| No host Docker, via alias do host Linux | `http://host.docker.internal:11434` | Opcao especifica desse cenario: acrescente `--add-host host.docker.internal:host-gateway`. O servidor ou porta publicada precisa aceitar conexoes pela interface alcancada. |
| Em outro host, VPN ou endpoint remoto | `https://modelos.exemplo` | Exige DNS, rota, firewall, TLS e autenticacao conforme esse endpoint; uma rede Docker local nao resolve nomes internos de containers em outro host. |

Os nomes, protocolos e portas da tabela sao ilustrativos; substitua pelos do seu ambiente. Em rede Docker definida pelo usuario, nomes/aliases sao resolvidos entre containers da mesma rede. Nao e necessario publicar a porta do Ollama no host para esse acesso direto. Veja a [documentacao de redes bridge do Docker](https://docs.docker.com/engine/network/drivers/bridge/).

Em rede bridge, `localhost` dentro do gerador identifica o proprio container, nao o host nem outro container. Acesso que funciona no terminal do host nao comprova conectividade de dentro do container. Se o Ollama so escuta no loopback do host, adicionar um alias de DNS nao muda essa restricao. Nao exponha a API publicamente sem controle de acesso; configure a conectividade manualmente.

No comando base da fila e nas execucoes pontuais abaixo, acrescente as opcoes da linha escolhida antes do nome da imagem. `--network` configura o Docker e nao e uma variavel a colocar no arquivo `--env-file`. Nao ha autodeteccao, criacao automatica de rede ou tentativa de outro endpoint pelo projeto.

### Ambiente e dados persistentes

Use valores simples `CHAVE=valor`, sem aspas, comentarios na mesma linha ou interpolacao de variaveis. O arquivo e lido pelo Docker no host e nao precisa ser montado no container. Os caminhos padrao de dados, relatorios e fila sao relativos ao diretorio `/app` da imagem e ja correspondem aos mounts abaixo, mesmo com apenas as tres variaveis LLM no arquivo de ambiente. Se precisar explicita-los ou personaliza-los, os valores internos equivalentes sao os seguintes; `TZ` e opcional e o padrao da imagem e UTC:

```dotenv
DB_PATH=/app/data/duckdb/b3_fundamentals.duckdb
RAW_DIR=/app/data/raw
SNAPSHOT_DIR=/app/data/snapshots
QUEUE_DIR=/app/queue
TZ=America/Campo_Grande
```

Esses caminhos sao internos ao container. Definir `DB_PATH` ou `RAW_DIR` nao monta volumes: a persistencia no host depende dos mounts do `docker run`. Com os mounts usados abaixo, o mapeamento e:

| Uso | Caminho no container | Caminho no host |
| --- | --- | --- |
| Banco (`DB_PATH`) | `/app/data/duckdb/b3_fundamentals.duckdb` | `$(pwd)/data/duckdb/b3_fundamentals.duckdb` |
| Estados e dados brutos (`RAW_DIR`) | `/app/data/raw` | `$(pwd)/data/raw` |
| Snapshots do ETL (`SNAPSHOT_DIR`) | `/app/data/snapshots` | `$(pwd)/data/snapshots` |
| Relatorios | `/app/reports` | `$(pwd)/reports` |
| Fila (`QUEUE_DIR`) | `/app/queue` | `$(pwd)/queue` |

`$(pwd)` representa o diretorio do host onde o comando e executado, nao uma variavel a colocar no `.env`. Use sempre o mesmo diretorio ou caminhos absolutos para nao iniciar outro container com um conjunto diferente de dados. Alterar um caminho interno exige conferir se ele continua coberto pelo mount. Sem mount nesse caminho, os arquivos ficam na camada gravavel do container e nao sao preservados ao remove-lo. `docker save` transfere apenas a imagem, nao o banco, os estados ou os relatorios mantidos nos mounts; copie esses dados separadamente ao migrar uma instalacao existente para outro host.

O relatorio e publicado em `reports/<ATIVO>.md`, com frontmatter. Os arquivos `data/raw/assessments/<ATIVO>.queue.json` e `.manual.json` guardam o estado de execucao e os snapshots necessarios a retomada; `data/raw/event-observations/` guarda as observacoes de eventos do Yahoo. Sao dados persistentes internos, nao temporarios descartaveis. O banco tambem pode receber escritas do cache Fundamentus durante a geracao. Para integrar outro sistema, compartilhe somente fila e relatorios quando suficiente, mantendo banco e estados sob controle do gerador e um unico watcher escritor.

O watcher nao oferece servidor HTTP nem exige publicar portas (`-p`). Ele precisa de acesso de saida as fontes de dados e a API do modelo. Compartilhar arquivos entre containers no mesmo host nao elimina essas conexoes de saida.

Inicialize o banco explicitamente:

```bash
docker run --rm --init --env-file .env \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$(pwd)/data,dst=/app/data" \
  b3-llm-report:local python init_db.py
```

Execute a fila a partir do diretorio escolhido no host, contendo `.env`, `data/`, `reports/` e `queue/`. Nao e necessario usar um caminho fixo como `/srv/b3-report`; `$(pwd)` resolve os mounts para o diretorio atual:

```bash
docker run -d \
  --name b3-report \
  --init \
  --restart unless-stopped \
  --env-file .env \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$(pwd)/data,dst=/app/data" \
  --mount "type=bind,src=$(pwd)/reports,dst=/app/reports" \
  --mount "type=bind,src=$(pwd)/queue,dst=/app/queue" \
  b3-llm-report:local
docker logs -f b3-report
```

Esse e o comando base, sem assumir rede Docker ou endereco do servidor de modelos. Se o acesso exigir `--network` ou `--add-host`, inclua essas opcoes antes de `b3-llm-report:local`, conforme a tabela acima. Nao e necessario publicar portas do gerador. Para integrar outro container, monte os mesmos diretorios do host: `queue/` com escrita para criar alertas e `reports/` somente para leitura; mantenha `data/` privado do gerador.

Os exemplos usam o UID/GID do usuario do host para permitir escrita nos diretorios montados. A imagem usa UID/GID 1000 por padrao. Todos os diretorios montados precisam permitir escrita ao usuario escolhido.

Solicite um relatorio com `touch queue/PETR4`. A fila considera a idade do trigger e do relatorio existente; ajuste `QUEUE_MAX_TRIGGER_AGE_HOURS` e `REPORT_MIN_AGE_HOURS` no `.env` conforme a operacao.

A fila faz no maximo uma tentativa de relatorio por varredura e espera `QUEUE_REQUEST_INTERVAL_SECONDS` (padrao: 60 segundos) apos cada sucesso. Depois de qualquer erro, pausa todas as tentativas por `QUEUE_ERROR_COOLDOWN_SECONDS` (padrao: 900 segundos), respeitando tambem o intervalo minimo. O proximo item segue a ordem alfabetica circular, permitindo avancar mesmo se um ticker falhar. As pausas contam a partir do fim da tentativa e sao verificadas a cada `QUEUE_POLL_SECONDS`. Os controles ficam em memoria; recriar ou reiniciar o processo zera a pausa. Esses intervalos reduzem rajadas, mas nao garantem que o Yahoo libere um IP ja limitado. Uma tentativa de relatorio pode fazer varias consultas Yahoo.

No modo unificado descrito abaixo, a unidade da varredura e um ticker. As etapas elegiveis sao sequenciais; o intervalo/cooldown comeca depois da tentativa.

Com filas grandes, ajuste `QUEUE_MAX_TRIGGER_AGE_HOURS` para cobrir o tempo de processamento: triggers que ultrapassarem essa idade serao ignorados, inclusive apos pausas. Alterar o `.env` exige recriar o container com `--env-file`; `docker restart` conserva o ambiente original.

Reconstruir ou carregar uma imagem nao atualiza containers ja criados: `docker start` e `docker restart` conservam a imagem original. Depois de validar uma nova imagem isoladamente, para promove-la pare e remova o container de producao e recrie-o com o comando da fila, os mesmos mounts, ambiente e opcoes de rede. Banco, estados e relatorios devem continuar nos diretorios persistentes do host. Reiniciar o container antigo apenas restaura a versao anterior; nao promove a imagem testada.

Para uma execucao pontual, pare a fila e utilize a mesma imagem. Acrescente ao `docker run` as mesmas opcoes de rede usadas pelo watcher, se houver. O `docker start` no final deste exemplo retoma o container existente, nao o atualiza:

```bash
docker stop --time 60 b3-report
docker run --rm --init --env-file .env \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$(pwd)/data,dst=/app/data" \
  --mount "type=bind,src=$(pwd)/reports,dst=/app/reports" \
  b3-llm-report:local python main.py PETR4
docker start b3-report
```

Outros comandos podem substituir `python main.py PETR4`, como `python ingest.py --tickers PETR4,ITUB4,VALE3`, `python build_ticker_map.py` e `python ingest_cvm.py --help`. O schema vazio nao fornece os dados CVM: carregue o mapeamento e os demonstrativos separadamente quando necessario.

Coordene o ETL e a fila para evitar acessos simultaneos de processos distintos enquanto o DuckDB estiver aberto para escrita; o relatorio tambem grava cache no banco.

Os dados persistem nos diretorios do host. Para migrar dados existentes, copie esses diretorios com os processos parados. `.env`, bancos e relatorios nao fazem parte da imagem. O fuso horario e configurado por `TZ`; as chamadas externas continuam dependendo da rede do host de destino.

## Variáveis de ambiente

As variáveis abaixo são lidas pelo projeto. Quando houver default, ele já está embutido no código.

### Relatório LLM

- `LLM_API_KEY`: chave opcional, compartilhada pelos dois protocolos.
- `LLM_MODEL`: nome obrigatorio do modelo.
- `OPENAI_URL_BASE`: base da API compativel com OpenAI, incluindo `/v1` quando exigido pelo servidor.
- `OLLAMA_URL_BASE`: base da API nativa Ollama, sem `/v1` ou `/api/chat`.

Nos dois casos, use um endereco acessivel pelo processo: no host pode ser localhost; no Docker, consulte a secao de acesso ao servidor de modelos acima.

Para gerar relatorios ou iniciar a fila, defina exatamente uma das duas URLs e `LLM_MODEL`. Configuracao ausente ou ambigua interrompe a execucao antes de coletar dados. Comandos de ETL e consulta nao exigem configurar LLM. `OPENAI_API_KEY` e `OPENAI_MODEL_NAME` foram substituidas por `LLM_API_KEY` e `LLM_MODEL`; migre o ambiente existente. Nao ha selecao automatica de protocolo nem tentativa de outro endpoint apos falha. `REPORT_HISTORY_N` nao e mais lida: o relatorio legado e a geracao de historico por versao foram removidos. Valores antigos podem ser retirados manualmente.

No protocolo OpenAI, o cliente usa Chat Completions. No Ollama nativo, usa `POST /api/chat`, com `stream=false`, e extrai `message.content`. Quando `LLM_API_KEY` estiver preenchida, ela e enviada como Bearer token.

### ETL e storage

- `DB_PATH` default: `data/duckdb/b3_fundamentals.duckdb`
- `SNAPSHOT_DIR` default: `data/snapshots`
- `RAW_DIR` default: `data/raw`
- `BRAPI_KEY` default: vazio
- `BRAPI_BASE_URL` default: `https://brapi.dev/api`

### Cache e logs

- `FUND_TTL` default: `86400`
- `LOG_LEVEL` default: `INFO`

O servidor MCP foi descontinuado. `AUTH_TOKEN`, `CACHE_TYPE` e `PRICE_TTL` nao sao mais lidos; valores antigos no ambiente podem ser removidos manualmente. `FUND_TTL` continua controlando o cache do Fundamentus usado pelos relatorios.

## Fluxos principais

### 1. Gerar relatório com LLM

Pré-requisitos:
- Ollama ou endpoint OpenAI compatível acessível.

Execução:

```bash
python main.py PETR4
```

Saída:
- relatorio atual com frontmatter em `reports/PETR4.md`;
- snapshot e resultado em `RAW_DIR/assessments/PETR4.manual.json`, sem historico por versao.

### Relatorio unificado

O unificado e o unico fluxo, inclusive sem flags: o mesmo LLM produz as classificacoes de investimento e risco e suas justificativas por horizonte. `--unified` permanece aceito como alias de compatibilidade, sem alterar o fluxo. Prompts e criterios atuais do unificado foram preservados. Nao ha mais geracao legada, reaproveitamento de relatorios anteriores no prompt ou gravacao de historico de Markdown. Arquivos ja existentes nao sao apagados ou convertidos. Um Markdown anterior nunca e usado como entrada para uma nova analise. A retomada apos falha reutiliza o snapshot de dados no estado JSON, nao o texto do relatorio anterior, que permanece publicado ate uma nova geracao ter sucesso. Nao ha modelo dedicado nem chamadas a `/v1/systemone`. Os argumentos `--decision-model`, `--with-report` e `--decision-report` foram removidos; se usados, o comando falha explicitamente, sem escolher outro modo.

```bash
OLLAMA_URL_BASE=http://localhost:11434 OPENAI_URL_BASE='' \
LLM_MODEL='deepseek-v4.1-flash:cloud' \
python main.py WEGE3 --structured-output off
```

Esse exemplo executa Python no host e pressupoe Ollama acessivel no loopback desse host. Ajuste a URL para outro endereco ou servidor remoto; no Docker, use o endereco e as opcoes de rede do cenario escolhido na secao Docker.

Investimento e risco continuam em etapas separadas: uma chamada por etapa elegivel, e nao necessariamente uma chamada por execucao. Neutro significa ficar sem posicao, com risco nao aplicavel. Dados insuficientes e erros nao sao classes financeiras. Os criterios e prompts nao mudaram nesta remocao; a qualidade permanece experimental, sem aprovacao financeira.

### Structured outputs no chat

`--structured-output on|off` esta disponivel sem exigir outra flag; padrao `off`. Em `on`, o Ollama recebe `format` com JSON Schema e o cliente OpenAI compativel recebe `response_format` estrito. A validacao local e obrigatoria em ambos. Nao ha deteccao automatica de suporte, reparo, retry ou fallback para `off`. O usuario deve selecionar o parametro conforme a capacidade de seu endpoint. Respostas incompletas (`done: false`, `length` ou `max_tokens`) geram erro; resposta e metadados recebidos sao preservados no estado interno.

### Tokens na saida padrao

Cada chamada aos clientes de chat imprime entrada, saida e total de tokens, usando apenas as contagens retornadas pelo servidor. Exemplo ilustrativo:

```text
Tokens da chamada (Ollama modelo=qwen3.8:80k): entrada=1200; saida=80; total=1280
```

Se houver mais de uma chamada em uma execucao de relatorio, imprime tambem o total dessa execucao. No watcher, a soma e por tentativa do ticker, nao por toda a vida do processo. Resultados retomados e skips nao contam como chamadas novas. Contagens ausentes ou invalidas aparecem como `indisponivel`, nunca como zero estimado; uma soma incompleta e marcada como indisponivel com o subtotal conhecido. Zero informado e preservado. Contagens recebidas sao impressas mesmo quando a resposta textual e invalida; falhas sem contagens ficam indisponiveis. Nao representa custo monetario. Sem parametro novo, mudanca de prompt ou nova chamada: basta reiniciar o watcher para carregar o codigo atualizado.

### Fila de relatorios

Exemplo de execucao direta no host, supondo Ollama acessivel em localhost. Para outros ambientes, ajuste a URL; para container, use o docker run da secao Docker com as opcoes de rede correspondentes.

```bash
OLLAMA_URL_BASE=http://localhost:11434 OPENAI_URL_BASE='' \
LLM_MODEL='deepseek-v4.1-flash:cloud' QUEUE_DIR=queue \
python watch_queue.py --structured-output off
```

O modelo pode ser local ou cloud conforme `LLM_MODEL` e o servidor configurado. Nao ha login, download ou customizacao automatica do servidor. O watcher processa um ticker por tentativa e preserva os arquivos da fila. Idade maxima dos alertas, intervalo entre tentativas e cooldown seguem a configuracao existente. Manter um unico watcher sobre a mesma instalacao. O bloqueio por ativo coordena pedidos manuais e processamento; nao serializa escritas de ativos diferentes no banco nem substitui essa restricao operacional. Trocar modelo, instrucoes ou structured output nao cria um novo alerta para um estado unificado concluido. Novo trigger respeita a idade minima; atualizacao do calendario/fase segue a politica de eventos. Configuracao alterada com execucao pendente bloqueia retomada para evitar misturar resultados. Execucao manual pode reprocessar um ativo sem alterar o controle da fila. O watcher sem flags usa o mesmo fluxo. Marcadores legados em `RAW_DIR/queue-completions/` nao sao mais usados nem apagados. Um ticker sem estado unificado sera avaliado quando tiver alerta elegivel, mesmo que exista um relatorio legado. Estados unificados existentes continuam sendo retomados.

### Publicacao e retomada do unificado

```text
reports/<TICKER>.md
RAW_DIR/assessments/<TICKER>.queue.json
RAW_DIR/assessments/<TICKER>.manual.json
```

A publicacao e um unico Markdown com frontmatter em portugues: `simbolo`, `data_analise`, `modelo` e `horizontes`, com `investimento` e `risco` contendo `estado`, `classe`, `direcao` e `motivo` quando aplicaveis. Narrativas e eventos ficam no corpo. O contrato atual nao solicita nem grava probabilidades, confianca ou sua origem. Registros tecnicos ficam apenas no estado interno. A escrita do Markdown e atomica; JSON publicado antigo do ticker e removido apos sucesso. Erros preservam a publicacao anterior. Sem conversao em lote.

O estado atual `assessment-state-v2` inclui configuracao, snapshot e uma unica secao `execution`, com status, resultado, hash e eventual erro. O resultado contem relatorio e classificacoes, sem projecao duplicada nem mapas de modelos/modos. Na configuracao nao ha mais `decision_model` ou `decision_endpoint`. Estados unificados `assessment-state-v1` sao validados e adaptados em memoria, sem repetir o chat concluido na fila. Se faltava apenas a projecao antiga, o horario do checkpoint serve como referencia de conclusao. A leitura nao regrava arquivos: somente novos checkpoints usam v2, nos mesmos caminhos por ticker. Mudar de modelo nao reprocessa alertas concluidos e continua bloqueado com execucao pendente. Estados antigos do par com modelo dedicado nao sao retomados ou migrados: geram erro de controle. Com o watcher parado, preserve ou remova manualmente esse estado para reiniciar. Dados antigos nao sao apagados automaticamente. Uma interrupcao entre a resposta e o checkpoint ainda pode repetir chamadas; nao ha garantia de execucao unica.

Novos resultados usam `assessment-v3`: classe e justificativa, sem `probabilities`, `confidence` ou `probability_source`. O leitor aceita `assessment-v2` apenas como formato anterior, sem interpretar essas estimativas nem regravar arquivos na consulta; o frontmatter nunca as publica. As versoes dos prompts foram atualizadas. Alertas concluidos nao sao reprocessados apenas por essa mudanca; execucoes pendentes com configuracao antiga continuam bloqueadas para evitar misturar contratos. Revise essas pendencias com o watcher parado antes de retomar. Nao ha conversao ou fallback automatico de respostas.

Para reproduzir uma entrada, use `--snapshot`, sem precisar de `--unified`. O nome antigo `--decision-snapshot` continua aceito como alias. Aceita snapshot avulso ou estado autocontido v1/v2, verifica simbolo/hash e conserva a data original. Replay pode chamar o LLM; nao e offline.

```bash
python main.py WEGE3 --snapshot CAMINHO_DO_SNAPSHOT
```

O frontmatter e uma apresentacao, nao substitui o estado de retomada. Regra de Neutro explicada uma vez no texto; avisos de aluguel aparecem apenas para direcao vendida. Sem HTML nem hashes tecnicos no corpo do relatorio. As instrucoes atuais reforcam a direcao do risco e a comparabilidade de fontes; nao implementam conciliacao automatica nem comprovam qualidade financeira.

O motor textual tem somente o contrato de resposta `relatorio` do unificado; nao oferece mais um prompt ou parser paralelo `baseline/rationale`. A leitura de `rationale` permanece apenas para apresentar resultados antigos, sem converte-los ou regrava-los. Identificadores tecnicos antigos nos estados foram preservados; essa limpeza nao muda o prompt ou a identidade de execucao.

#### Risco qualitativo (experimental)

A rubrica `rubrica-comum-v2-risco-qualitativo-experimental` vale para o relatorio unificado. Investimento mantem os criterios anteriores; risco usa as classes abaixo, sem faixas de perda:

| Classe | Orientacao |
| --- | --- |
| Baixo | Evidencias afirmativas de liquidez e saude financeira adequadas, com exposicao limitada a fatores adversos relevantes |
| Moderado | Vulnerabilidades materiais, mas capacidade de absorcao e saida sem fragilidade severa identificada |
| Alto | Fator severo sustentado pelos dados, com exposicao a perdas expressivas ou dificuldade importante de saida |

Os dados obrigatorios para risco comprado ou vendido sao preco, liquidez e saude financeira, com as mesmas verificacoes de fonte, datas e conflitos. O horizonte e a direcao continuam explicitos. Neutro continua sem posicao, com risco nao aplicavel. Ausencia de noticias negativas nao significa Baixo risco; confianca, atratividade e risco permanecem separados.

Cenario quantitativo previamente elaborado, disponibilidade, custo e condicoes de aluguel deixam de ser requisitos de suficiencia. Informacoes opcionais ja presentes podem ser consideradas se forem atuais, identificadas e pertinentes; noticias tambem sao opcionais, mas nenhuma coleta nova foi implementada. Nao completar fatos, custos, disponibilidade nem percentuais de perda ausentes.

O estado JSON registra `risk_scope`; as apresentacoes publicadas mostram o aviso pertinente a direcao: risco qualitativo de uma posicao hipotetica, sem confirmar viabilidade ou custos efetivos de aluguel. Nao e uma avaliacao operacional completa da venda. Os antigos limites de 10% e 25% nao sao usados para as classes atuais.

A nova rubrica muda a identidade da configuracao, sem criar novo alerta na fila: estados concluidos sao substituidos somente na proxima execucao elegivel; pendencias antigas bloqueiam a troca e exigem reinicio manual consciente com o watcher parado. Nao ha migracao de resultados antigos nem chamadas automaticas extras de teste. A etapa de risco agora pode executar onde antes era bloqueada, aumentando chamadas/tokens. Comparacoes de qualidade exigem corpus revisado e resultados sobre os mesmos dados; a remocao dos limites numericos nao implica aprovacao financeira.

#### Eventos corporativos (experimental)

O extrator yfinance preserva automaticamente, em `Event Metadata`, os campos de resultados que ja vierem em `Ticker.info`: timestamps pontuais/de intervalo, earnings call, flag de estimativa e fuso declarado. Dados brutos e conversao UTC seguem para o snapshot compartilhado e para o contexto enviado aos modelos, sem requisicao adicional. Datas de resultados agora geram avisos automaticamente, sem exigir arquivo manual, pela politica `eventos-yahoo-v2-experimental-7d`. Cobertura por ticker ainda exige validacao: foi observada pelo usuario em WEGE3. Ausencia em info significa desconhecimento, nao ausencia de evento.

No Markdown, a secao de eventos apresenta uma linha por evento, com data, situacao e fonte, mais ressalvas curtas de cobertura e descontinuidade quando aplicaveis. Estimativas, intervalos e divergencias continuam explicitos; horarios de coleta, disponibilidade e demais metadados ficam no estado interno, sem repetir o bloco tecnico no relatorio. Versao de apresentacao: `relatorio-markdown-v7-aviso-experimental` (frontmatter em portugues, aviso de uso experimental no corpo, resumo por horizonte e motivos legiveis, sem HTML; versao tecnica registrada somente no estado). Essa apresentacao nao altera prompts, politica de proximidade, gates ou classificacoes, nem reescreve relatorios antigos. A saida padrao mostra o mesmo Markdown publicado, sem uma tabela de decisao separada.

Intervalo completo de `earningsTimestampStart/End` e preservado; na ausencia dos dois, usa-se `earningsTimestamp`. Intervalo incompleto nao vira data pontual; earnings call nao e tratada como divulgacao de resultados. Divergencia entre timestamp pontual e intervalo e sinalizada para verificacao, sem conciliacao silenciosa. Flag de estimativa falsa nao confirma horario no RI. Fuso ausente mantem representacao UTC explicita, sem presumir fuso da bolsa.

Ao atingir o horario/fim do intervalo, o aviso passa para data prevista atingida com confirmacao pendente. Nao afirma divulgacao realizada ou dados incorporados. Na politica v2, a pendencia e recente ate sete dias corridos depois da data prevista/fim do intervalo, inclusive, no fuso do evento. A partir do oitavo dia, a fase e `evento_antigo_verificacao_pendente`: preserva datas e metadados, mas nao emite alerta ativo de proximidade nem torna o ticker elegivel apenas por esse aviso. Uma data pontual divergente recente/futura impede ocultar o conflito como antigo. Cancelamento e incorporacao confirmados conservam suas fases. A expiracao do aviso nao confirma divulgacao/incorporacao nem supre dados de risco. As observacoes recentes ficam em `RAW_DIR/event-observations/<TICKER>.json`; esse e um cache operacional substituivel, enquanto snapshots/resultados preservam suas entradas. A fila recalcula a fase dessa observacao sem consultar o Yahoo a cada polling; so descobre novas datas quando ocorre nova coleta normal. Somente mudar o horario da coleta, sem alterar evento/fase, nao provoca repeticao. Estados unificados preservam a politica de eventos usada. Controles antigos nao sao apagados.

Como complemento opcional, defina `CORPORATE_EVENTS_FILE` para um calendario JSON local. Nao ha consulta automatica a RI/CVM nem inferencia de datas pelo ticker nesta versao. Os dois contextos sao preservados sem conciliacao automatica; um registro manual nao cancela silenciosamente a previsao Yahoo. IDs com prefixo `yahoo-info-` sao reservados para a origem automatica. Exemplo de formato, com **dados ficticios, nao usar como evento real**:

```json
{
  "version": "corporate-events-v1",
  "events": [{
    "id": "resultado-trimestre-exemplo",
    "ticker": "TEST3",
    "type": "resultados",
    "event_date": "2026-10-22",
    "event_time": null,
    "timezone": "America/Sao_Paulo",
    "source": "https://ri.exemplo.test/calendario",
    "available_at": "2026-10-19T10:00:00-03:00",
    "checked_at": "2026-10-21T09:00:00-03:00",
    "status": "previsto",
    "incorporation": "nao_verificado",
    "incorporated_at": null
  }]
}
```

`event_date` exige YYYY-MM-DD; `event_time` e HH:MM ou null quando desconhecido. Use fuso IANA e timestamps com offset em `available_at`/`checked_at`. A disponibilidade refere-se a informacao da revisao atual do registro: ao confirmar divulgacao/cancelamento, atualizar a procedencia temporal, sem reutilizar a data antiga de anuncio como se o novo status ja fosse conhecido. IDs devem ser unicos por ticker. Arquivo configurado ausente/invalido falha explicitamente; nao e ignorado como se nao houvesse evento.

Politica manual `eventos-v2-experimental-7d`: proximidade de ate sete dias corridos, calculados no fuso do evento. No dia sem horario conhecido, o sistema avisa essa incerteza. A mesma janela posterior de sete dias limita a pendencia ativa, inclusive para divulgacao confirmada sem incorporacao verificada; o status original continua preservado, mesmo quando o aviso fica antigo. Passar a data prevista nao confirma divulgacao. Status aceitos: `previsto`, `divulgado`, `cancelado`. Incorporacao: `dados_anteriores`, `nao_verificado`, `atualizados`. Este ultimo exige status divulgado e `incorporated_at` com cronologia valida; e uma **atestacao manual** de que os dados usados incorporam a divulgacao, nao uma verificacao automatica das fontes. Nao marcar atualizado apenas por coletar novamente ou esperar o evento passar.

Os avisos aparecem no relatorio unificado. Investimento e risco recebem o mesmo contexto, com instante de corte UTC, fonte, disponibilidade e consulta preservados no snapshot. Revisoes conhecidas apenas depois desse corte nao entram. Replay conserva o contexto original, sem ler o calendario/cache atual nem introduzir informacao futura. O contexto fica no snapshot do estado autocontido; os arquivos de eventos do legado nao sao mais produzidos. Snapshots de politica v1 continuam validos e conservam suas fases e avisos originais no replay; nao sao reclassificados pela data atual. A politica v2 inclui `pending_days: 7` no contexto. Aplicar a regra nova exige contexto novo, sem editar snapshots antigos. A janela e experimental, nao aprovacao financeira.

Evento proximo ou pendencia recente de divulgacao/incorporacao sinaliza possivel descontinuidade de preco, mas nao determina Compra/Venda, magnitude de perda ou risco Alto. Nao substitui os dados essenciais de preco, liquidez e saude financeira. O aviso pode importar tambem para posicoes longas mantidas atraves do evento e aparece mesmo com Neutro. Calendario vazio nao comprova ausencia de eventos. A janela e as instrucoes adicionais sao experimentais e exigem benchmark antes de aprovacao financeira.

Na fila, mudanca do calendario/fase pode reavaliar o mesmo trigger sem esperar a idade minima do relatorio. Evento ativo pode tornar elegivel um ticker ja presente com alerta antigo; cancelamento, incorporacao ou remocao de um evento registrado tambem invalidam o controle anterior. Nao cria tickers na fila e nao reprocessa a cada polling: o controle usa conteudo/fase, nao o relogio de consulta. Relatorio unificado pendente termina primeiro no snapshot preservado; depois pode iniciar nova execucao com o calendario atualizado. Cooldowns continuam. Desativar a variavel nao e equivalente a cancelar/remover um evento: use uma revisao explicita do calendario para atualizar os avisos anteriores.

#### Fontes e representacao do contexto

A politica unica `yfinance-primary-fundamentus-valuation-v2` usa yfinance como fonte primaria dos grupos de suficiencia, sem parametros por tipo de simbolo. Somente quando o grupo inteiro de valuation estiver vazio, seleciona P/L e/ou P/VP numericos do Fundamentus, com fonte registrada no snapshot e no log. Nao mescla indicadores de fontes distintas nem substitui um grupo primario preenchido. A data da ultima cotacao do Fundamentus e a data original da coleta sao preservadas; as mesmas checagens de atualizacao continuam obrigatorias. Datas ausentes nao sao substituidas pela data da analise.

Novos snapshots preservam texto, indicadores brutos e horario de coleta do Fundamentus, alem do `quoteType` declarado pelo yfinance (quando disponivel). Esse campo nao e uma classificacao completa de fundos ou holdings. O cache guarda uma coleta inteira por ticker, sem misturar campos de coletas antigas. CVM permanece como contexto; crescimento de cinco anos nao e convertido automaticamente em crescimento de outro periodo. Snapshots textuais antigos continuam legiveis, sem reinterpretacao ou alteracao dos arquivos preservados. O relatorio unificado usa esta politica no snapshot preservado. Existe um utilitario reversivel `cvm-table-v1` para representar demonstrativos CVM homogeneos por `columns` e `rows`, preservando todas as linhas e valores. Ele ainda nao e usado pelo prompt unificado: o fluxo atual envia o snapshot completo, com os demonstrativos como lista de objetos. A integracao dessa compactacao e sua comparacao de qualidade continuam pendentes. `available_at` registra a observacao do dado neste snapshot, nao comprova sua data original de publicacao. A coleta atual nao fornece cenarios adversos por direcao/horizonte nem todos os dados de aluguel. Na rubrica v2, isso e uma limitacao, nao bloqueio automatico do risco qualitativo. Anotacoes externas podem ser incluidas em `risk_evidence` no snapshot, mantendo fonte e datas explicitas. Essa politica ainda exige avaliacao de conflitos entre fontes complementares e casos humanos antes da adocao. A validacao real do relatorio permanece a cargo do usuario.

### 2. Inicializar o DuckDB

```bash
python init_db.py
```

Ou:

```bash
bash scripts/demo_init_db.sh
```

### 3. Rodar o ETL de mercado e indicadores

O fluxo atual coleta yfinance e complementa com Fundamentus. Nao exige BRAPI_KEY; a chamada BRAPI permanece desabilitada no codigo. Inicialize o schema antes de gravar no banco.

Execução:

```bash
python ingest.py --tickers PETR4,ITUB4,VALE3
```

Ou:

```bash
bash scripts/demo_ingest.sh PETR4,ITUB4,VALE3
```

Saídas:
- DuckDB em `data/duckdb/`
- brutos yfinance em `data/raw/yfinance/<TICKER>/` e HTML Fundamentus em `data/raw/fundamentus/<TICKER>/`
- snapshots Parquet em `data/snapshots/AAAAMMDD/`

Observação:
- o ETL não cria tabelas automaticamente; execute `init_db.py` antes.

Demonstrativos oficiais sao carregados separadamente com `ingest_cvm.py`, por ano, com ITR opcional. Consulte `python ingest_cvm.py --help`; o cadastro, DFP e ITR brutos ficam sob `data/raw/cvm/`. O mapeamento de tickers e empresas tambem precisa estar disponivel para consultar esses demonstrativos por ativo.

## Validação mínima

Validação sintática dos arquivos Python principais:

```bash
bash scripts/validate_python.sh
```

Há também testes automatizados no diretório `tests/`, cobrindo ETL, configuração, relatórios, decisões e fila.

Para instalar as dependencias de desenvolvimento e executar a suite:

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

### Validacao manual da interface

Use um unico ativo e diretorios de fila, estados e relatorios separados dos de producao. Se copiar um banco existente, pare antes todos os processos que o utilizam e copie-o fechado. As chamadas reais devem ser executadas pelo operador quando houver disponibilidade.

1. Consulte um relatorio existente e confira conteudo, caminho e as opcoes de saida isoladas, sem depender do watcher ativo.
2. Registre um pedido na fila isolada com o container parado. Repita o comando antes de iniciar: deve informar que o pedido ja existe. Inicie o watcher de teste com os mounts e a conectividade corretos e aguarde a conclusao.
3. Confira o Markdown com aviso experimental, `execution.status=done` no estado e a retirada do pedido. Isso valida a geracao inicial, nao o desvio da idade minima.
4. Solicite novamente o mesmo ativo apos a conclusao, sem reduzir `REPORT_MIN_AGE_HOURS`. Aguarde a nova conclusao e confira um novo `request_id` e `completed_at` no estado, mesmo que dados e classificacoes nao mudem. Essa segunda execucao valida a atualizacao obrigatoria de um relatorio recente.
5. Durante uma geracao ativa, outro comando gerar para o mesmo ativo deve informar processamento sem criar pedido adicional. Teste interrupcao/retomada em uma rodada separada, preservando estado e snapshot.

Ao encerrar, escolha explicitamente entre restaurar o container anterior ou promover a nova imagem conforme a secao Docker. Nao interprete `docker start` como atualizacao.

## Limitações atuais

- Cobertura, atualizacao e disponibilidade das fontes variam por ativo; dados CVM dependem de ingestao e mapeamento previamente preparados.
- O pipeline de relatório continua dependente de chamadas externas em tempo de execução.
- A suíte de testes atual cobre partes críticas, mas ainda não valida todo o fluxo end-to-end com dependências externas reais.
- Classificacoes e risco sao experimentais; validade de formato e testes de software nao comprovam qualidade financeira ou desempenho de investimento.

## Alerta

Este projeto e experimental e nao constitui recomendacao de investimento. Veja [AVISO.md](AVISO.md) para finalidade, limitacoes e uso dos resultados. Novos relatorios gerados ou renderizados incluem um aviso curto no corpo; arquivos ja publicados nao sao reescritos automaticamente.

## Licenca

O codigo e disponibilizado sob a [licenca MIT](LICENSE). Consulte tambem os termos das fontes de dados e dos provedores de modelos utilizados.
