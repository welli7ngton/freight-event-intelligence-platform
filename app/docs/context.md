# Current Technical Context: Freight Event Intelligence Platform

> Revisado em 2026-09-10 contra o código, configuração e testes disponíveis.
> Este documento descreve capacidades implementadas e limites conhecidos.
> O README contém os comandos de execução; ADRs preservam decisões e evolução.

## 1. Estado atual

O monólito modular possui domínio, aplicação, FastAPI, persistência PostgreSQL,
migrations Alembic, ingestão RabbitMQ, retries limitados, DLQ, Transactional
Outbox e observabilidade (Fases 6 e 7). Isso não significa cobertura completa
de todas as falhas de produção. Logs JSON, correlation IDs e métricas estão
nos processos; Prometheus/Grafana são opcionais no Compose local.

Não existem Inbox/processed_events, Redis, replay completo, tracing distribuído,
agregação central de logs ou entrega de alertas de produção.

## 2. Estrutura e dependências

| Diretório | Responsabilidade |
| --- | --- |
| `app/domain/shipment/` | Entidade, eventos, state machine, handler e exceções |
| `app/application/ports/` | Protocols de repositories e publisher |
| `app/application/use_cases/` | Criação, consultas e recebimento de eventos |
| `app/application/messaging/` | Contrato versionado e serialização |
| `app/api/` | FastAPI, rotas, schemas Pydantic e dependências |
| `app/infra/database/` | SQLAlchemy, models, mappers, repositories e sessão |
| `app/infra/messaging/` | RabbitMQ e classificação de falhas |
| `app/infra/observability/` | Contexto, logs JSON, métricas e backlog |
| `app/infra/config.py` | Configuração por ambiente e carregamento de .env |
| `app/workers/shipment_event_worker.py` | Montagem do consumer e transação por evento |
| `app/workers/outbox_worker.py` | Relay confirmado e endpoint de métricas |
| `monitoring/` | Prometheus e provisioning do Grafana |
| `alembic/versions/` | Evolução do schema |
| `tests/` | Testes de domínio, aplicação, API, infraestrutura e integração |

Python 3.12+, FastAPI/Pydantic, SQLAlchemy 2 com psycopg, PostgreSQL 17 e Pika
formam a stack. As versões exatas e tarefas ficam em
[pyproject.toml](../../pyproject.toml). O domínio não depende de frameworks,
banco ou broker. Casos de uso recebem ports por injeção; adapters reutilizam
as mesmas regras. Repositories persistem e mappers convertem ORM/domínio.

## 3. Domínio e eventos

`Shipment` é uma dataclass mutável. `Shipment.create()` inicia em `CREATED`.
`ShipmentEvent` é uma dataclass `frozen=True, slots=True`, contendo
`event_id`, `shipment_id`, `event_type`, `source`, `occurred_at`,
`received_at`, `payload` e `processing_status`. O congelamento impede
reatribuir campos, mas não congela recursivamente um payload dict.
`LocationUpdatedPayload` é uma dataclass imutável de latitude/longitude.

```text
CREATED --PICKUP_SCHEDULED--> SCHEDULED
SCHEDULED --PICKUP_COMPLETED--> PICKED_UP
PICKED_UP --SHIPMENT_DEPARTED--> IN_TRANSIT
IN_TRANSIT --DELAY_DETECTED--> DELAYED
IN_TRANSIT --DELIVERED--> DELIVERED
DELAYED --SHIPMENT_DEPARTED--> IN_TRANSIT
DELAYED --DELIVERED--> DELIVERED
```

`ShipmentEventHandler` verifica a identidade da shipment, rejeita
`SHIPMENT_CREATED`, normaliza localização e aplica a política temporal.
`change_status()` consulta a state machine; `update_location()` altera
coordenadas sem mudar status. Não há transição de lifecycle saindo de
`DELIVERED`; localização é tratada separadamente pelo handler.

`occurred_at` representa o instante do fato; `received_at`, o registro na
plataforma. A aplicação gera timestamps UTC. Envie timestamps com timezone:
os contratos atuais não impõem timezone em todos os caminhos de entrada.

## 4. Política temporal

- Localização usa `last_location_at`; lifecycle usa `last_lifecycle_at`.
- Eventos estritamente anteriores ao relógio correspondente recebem
  `STORED_OUT_OF_ORDER` e permanecem no histórico sem alterar a projeção.
- Timestamps iguais não são considerados atrasados.
- Eventos não atrasados seguem atualização normal e recebem `APPLIED`.
  Transições não cadastradas lançam `InvalidStateTransition`.
- Lifecycle atrasado é classificado antes da state machine. Não existe
  reconstrução do estado histórico para validar a transição no passado.
- `updated_at` recebe `occurred_at` do último evento aplicado. Os dois
  relógios são independentes; portanto `updated_at` não é um watermark
  global monotônico.
- Não há replay ou reconciliação de eventos posteriores.

O handler não persiste, não deduplica, não controla transações e não publica.

## 5. Aplicação e HTTP

Ports: `ShipmentRepository` oferece `get/save`;
`ShipmentEventRepository`, `exists/save/list_by_shipment`;
`ShipmentEventPublisher`, `publish`; `OutboxRepository` registra e seleciona
intents; `RecordedEventPublisher` publica notificações de fatos registrados.

`CreateShipment` gera UUID e horário UTC, cria entidade e evento histórico
`SHIPMENT_CREATED` com `source = platform`, e salva ambos.
`Shipment.created_at == creation_event.occurred_at`.
O evento não representa uma transição `CREATED -> CREATED`. Criação e ingestão
também registram um intent de publicação na mesma transação, com correlation ID
opcional passado explicitamente pelos adapters. O domínio não recebe metadados
de observabilidade.

`ReceiveShipmentEvent` rejeita criação externa, carrega a shipment, verifica
`event_id`, chama o handler, registra o resultado por `dataclasses.replace`
e salva histórico/projeção. Duplicata sequencial retorna a shipment sem
reaplicar o evento. Não há comparação de payloads para IDs repetidos.

| Endpoint | Comportamento |
| --- | --- |
| `GET /health` | 200 com `{"status": "ok"}`; não verifica banco/broker |
| `GET /metrics` | Métricas Prometheus do processo da API |
| `POST /shipments` | 201 com ShipmentResponse; única criação pública |
| `GET /shipments/{shipment_id}` | 200 ou 404 |
| `GET /shipments/{shipment_id}/events` | 200, lista por occurred_at; ID inexistente retorna [] |
| `POST /events` | Síncrono, 200 com ShipmentResponse; não publica no broker |

No recebimento HTTP, shipment inexistente retorna 404, transição inválida 409
e `SHIPMENT_CREATED` 422. Schemas validam UUIDs, tipos e campos obrigatórios;
localização exige números, excluindo booleanos. Não há validação geográfica
de limites de latitude/longitude. DTOs HTTP são convertidos para inputs da
aplicação. Histórico expõe `processing_status`.

## 6. Persistência e atomicidade

`DATABASE_URL` é obrigatório; não há fallback de URL na aplicação.
`SessionLocal` usa `autoflush=False` e `expire_on_commit=False`.
`get_db()` fornece a mesma sessão aos repositories da request, faz commit no
sucesso, rollback na exceção e fecha a sessão. Repositories não fazem commit.
Não existe uma abstração dedicada de Unit of Work.

`shipments` armazena a projeção, referência única, status, timestamps,
coordenadas, `last_location_at` e `last_lifecycle_at`.
`shipment_events` tem PK `event_id`, FK para shipment, payload JSONB,
timestamps e `processing_status`. Mappers preservam enums e payloads.

Migrations existentes, em ordem:

1. `34fe2111c108`: cria shipments e shipment_events, constraints e índices.
2. `6f8e4c7a1b2d`: adiciona localização.
3. `8b7c3d2e1f0a`: adiciona last_lifecycle_at e processing_status.
4. `9c8d7e6f5a4b`: adiciona outbox_events e índice parcial de pendências.
5. `a1b2c3d4e5f6`: adiciona correlation_id nullable à outbox, sem alterar bodies.

Alembic utiliza a configuração de ambiente. Revise migrations autogeradas.
O fluxo de criação mantém entidade e histórico na mesma transação.

## 7. Idempotência e concorrência

O check `exists(event_id)` não é atômico. A PK PostgreSQL impede duas linhas
com a mesma identidade. A rota HTTP executa flush e, especificamente para
`shipment_events_pkey`, faz rollback e retorna a projeção recarregada.
Outros `IntegrityError` são propagados.

O worker não implementa essa recuperação HTTP: uma colisão na persistência
entra na classificação/retry de falhas; nova entrega pode encontrar o evento
já persistido. A deduplicação não serializa eventos distintos de uma shipment,
não impede lost updates em geral e não garante execução única do handler.
Por isso o handler deve continuar sem efeitos externos.

## 8. RabbitMQ e recuperação

`ShipmentEventMessage` serializa JSON determinístico com
`contract_version = v1`, message_id, event_id, shipment_id, event_type,
source, occurred_at, received_at e payload dict. A routing key é
`shipment.event.received.v1` e a exchange principal padrão é
`freight.shipment-events`. `event_id` continua sendo a identidade de negócio.

O worker declara a topologia, usa prefetch 1, desserializa a mensagem e chama
`ReceiveShipmentEvent` em uma sessão. O callback retorna após commit; então
o consumer envia ACK. O publisher declara a exchange, mas não a fila principal:
a topologia deve existir antes da publicação.

`ShipmentEventFailureClassifier` envia ValueError e exceções de negócio à
DLQ. OperationalError, OSError, TimeoutError e exceções desconhecidas recebem
retry limitado. TTL da fila de retry retorna à exchange principal.
Defaults: 5000 ms de espera e três tentativas totais.

O corpo original é preservado. Headers incluem `x-attempt-count`,
`x-first-failed-at`, `x-last-error-type` e `x-last-error-message` (até 500
caracteres). O consumer envia ACK após `basic_publish` retornar. Não há
publisher confirms nem mandatory routing; esse retorno não comprova aceitação
durável ou roteamento. Falhas entre publish e ACK também permitem duplicatas.
Não se deve afirmar entrega exatamente uma vez ou ausência de perda.

O Compose configura volume RabbitMQ e identidade estável. Isso não migra dados
de containers antigos. A limitação de confirms acima se refere ao fluxo inbound;
o relay outbound usa confirmações e mandatory routing.

### Transactional Outbox (ADR-008)

Criação, eventos aplicados e atrasados produzem um intent por evento/tipo,
independentemente de HTTP ou RabbitMQ. Duplicatas não criam outro; histórico
anterior não é backfilled. O repository faz flush ordenado dos pais para que
conflitos de event_id continuem surgindo antes da constraint da outbox.

O relay seleciona uma linha devida com FOR UPDATE SKIP LOCKED e mantém a
transação durante I/O limitado no broker. Publica o envelope armazenado
`shipment.event.recorded.v1` com ID estável, confirmações e mandatory routing;
depois grava published_at e faz commit. Falhas ficam pendentes com atraso fixo.
Falha após confirmação e antes de commit permite republicação idêntica. Não
há garantia de exactly-once ou ordenação por shipment. Attempts conta operações
registradas duravelmente, não todas as tentativas interrompidas.

A exchange `freight.shipment-notifications` e fila
`freight.shipment-event-notifications` são separadas da ingestão. Sem consumidor
downstream incluído. Repositories não fazem commit; limites transacionais
existentes continuam donos do commit/rollback.

### Observabilidade (ADR-009)

Middleware ASGI mantém correlation ID isolado por request, inclusive nos handlers
síncronos. X-Correlation-ID aceita 1–64 caracteres ASCII alfanuméricos, ponto,
hífen e underscore; outros valores geram UUID. A resposta retorna o ID. Outbox
persiste o metadado numa coluna nullable, enviado como AMQP correlation_id.
Retries/DLQ preservam o ID. Outbox antiga usa message_id como fallback; inbound
sem correlation usa message_id válido ou um UUID. Bodies v1 não mudam.

Logs JSON usam allowlist: timestamp UTC, component, operation, outcome, duração,
IDs disponíveis e classe de erro. Não renderizam mensagens livres, SQL, URLs,
payloads ou strings de exceção. Bibliotecas perdem detalhes da mensagem; logger,
nível e classe de erro continuam disponíveis.

API /metrics e workers 9101/9102 possuem registries de processo. Labels limitados
usam templates de rota, método normalizado, status e outcomes; nunca IDs.
Counters resetam no restart e contam observações, não eventos únicos.
`broker_confirmed` não significa `published_committed`. Ingestion `committed`
inclui duplicatas bem-sucedidas; `publish_returned` de retry/DLQ não é confirmação.

Backlog é consultado em sessão independente com pool pequeno, connect timeout e
statement timeout; conta também retries futuros. Falha emite collection_success=0
e omite gauges, sem inventar fila vazia. Use max, não sum, ao agregar backlog de
vários relays. Um processo por target/porta; multiprocess Uvicorn não é agregado.
Monitoring profile opcional fornece Prometheus e dashboard Grafana local.

## 9. Testes e validação

Validação executada em 2026-09-10:

- Baseline da Fase 6: 65 testes default e 29 de integração passaram. O gate
  inicial encontrou formatação em recorded_event_message.py, corrigida nesta fase.
- `task check`: formatação, lint e **79 testes default passaram**; 32 testes de
  integração excluídos por configuração. `task compile` passou.
- Integração PostgreSQL/RabbitMQ: **32 passaram**, carregando `.env` antes da
  coleta e usando exclusivamente `freight_events_test` e recursos isolados.
- Migration revalidada após ampliar cobertura: upgrade/downgrade da coluna de
  correlação preserva outbox populada; downgrade da outbox preserva histórico.
- `docker compose --profile monitoring config --quiet` e `promtool check config`
  passaram. Grafana carregou o dashboard provisionado com 10 painéis.
- Smoke com entry points reais, banco de testes e filas isoladas: três targets
  Prometheus UP, correlation header na API e coleta de backlog saudável. Processos
  temporários foram encerrados e recursos de broker do smoke removidos.

Cobertura inclui rollback após flush, corrida HTTP concorrente real, locks de
relay, confirmação seguida de falha de commit, republicação com identidade/body
e correlation ID estáveis, 422 para criação externa, commit antes de ACK no
callback de produção, deadlines de broker, isolamento de contextos concorrentes,
logs sem strings sensíveis, métricas de falha e propagação HTTP → banco → broker.

Advertências não bloqueantes: depreciações Starlette/AnyIO e constante HTTP 422;
o sandbox também impediu escrita do cache opcional do pytest no `task check`.
Integração foi executada com `-p no:cacheprovider`. Um conflito inicial entre
nomes de módulos de teste foi corrigido antes da execução completa.

Veja [README](../../README.md#integration-tests) para carregar URLs antes da
coleta. O banco deve se chamar exatamente `freight_events_test`; fixtures
aplicam migrations e limpam tabelas. RabbitMQ usa `TEST_RABBITMQ_URL`.
Não execute esses fixtures no banco de desenvolvimento.

## 10. Próximas decisões

ADR-008 e ADR-009 registram as Fases 6 e 7. Próximas decisões dependem de
requisitos: confirms/routing no retry/DLQ inbound, retenção da outbox, alertas,
agregação de logs ou tracing. Monitoramento não altera garantias de entrega.
Sem migrations aplicadas ao banco de desenvolvimento nesta implementação.
