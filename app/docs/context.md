# Current Technical Context: Freight Event Intelligence Platform

> Revisado em 2026-09-10 contra o código, configuração e testes disponíveis.
> Este documento descreve capacidades implementadas e limites conhecidos.
> O README contém os comandos de execução; ADRs preservam decisões e evolução.

## 1. Estado atual

O monólito modular possui domínio, aplicação, FastAPI, persistência PostgreSQL,
migrations Alembic, ingestão RabbitMQ, retries limitados e DLQ. As capacidades
das Fases 2.5 a 5 estão implementadas; isso não significa cobertura completa
de todas as falhas de produção. A próxima evolução planejada é a
**Fase 6 — Transactional Outbox**, seguida de observabilidade na Fase 7.

Não existem Outbox, tabela de Inbox/processed_events, Redis, replay completo,
logging estruturado, Prometheus ou Grafana.

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
| `app/infra/config.py` | Configuração por ambiente e carregamento de .env |
| `app/workers/shipment_event_worker.py` | Montagem do consumer e transação por evento |
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
`ShipmentEventPublisher`, `publish`.

`CreateShipment` gera UUID e horário UTC, cria entidade e evento histórico
`SHIPMENT_CREATED` com `source = platform`, e salva ambos.
`Shipment.created_at == creation_event.occurred_at`.
O evento não representa uma transição `CREATED -> CREATED`.

`ReceiveShipmentEvent` rejeita criação externa, carrega a shipment, verifica
`event_id`, chama o handler, registra o resultado por `dataclasses.replace`
e salva histórico/projeção. Duplicata sequencial retorna a shipment sem
reaplicar o evento. Não há comparação de payloads para IDs repetidos.

| Endpoint | Comportamento |
| --- | --- |
| `GET /health` | 200 com `{"status": "ok"}`; não verifica banco/broker |
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

Queues/exchanges são duráveis e mensagens publicadas são persistentes, mas
o serviço RabbitMQ no Compose não configura volume de dados persistente.
O HTTP ainda não publica automaticamente: Outbox resolverá a intenção de
publicação junto à transação de banco, sem presumir uma transação distribuída.

## 9. Testes e validação

Em 2026-09-10, executado:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Resultado: **49 passed, 13 deselected**, com uma advertência de depreciação
Starlette/AnyIO. Os 13 testes de integração foram coletados, mas não executados
nesta revisão documental; contagem coletada não comprova integração passando.

`task check` interrompeu na verificação de formatação de `alembic/env.py`.
Uma execução separada de Ruff também identificou I001 nesse arquivo (ordem de
imports). São problemas preexistentes, fora da atualização documental; não há
afirmação de que o gate completo de qualidade passou.

Cobertura disponível:

- Domínio/aplicação: criação, transições, duplicatas sequenciais, eventos
  atrasados, clocks independentes e rejeição de SHIPMENT_CREATED.
- API: health, criação/consulta, recebimento e recuperação de conflito simulado.
- PostgreSQL: repositories, constraints, HTTP integrado, retenção de evento
  atrasado, rollback e corrida com duas sessões.
- Messaging: round-trip versionado, publisher/consumer com doubles,
  classificação, retry e esgotamento; integração com broker para ingestão e DLQ.

Limites de cobertura: não há teste HTTP dedicado de 422 para SHIPMENT_CREATED,
nem corrida HTTP concorrente real (a rota usa conflito simulado no teste).
O teste de ingestão RabbitMQ integrado chama o use case diretamente e faz
commit depois de process_delivery; ele não comprova a ordem commit/ACK do
entry point de produção. O teste de rollback injeta falha de repository antes
de flush, não uma falha de commit após writes confirmados no servidor.

Veja [README](../../README.md#integration-tests) para carregar URLs antes da
coleta. O banco deve se chamar exatamente `freight_events_test`; fixtures
aplicam migrations e limpam tabelas. RabbitMQ usa `TEST_RABBITMQ_URL`.
Não execute esses fixtures no banco de desenvolvimento.

## 10. Próximas decisões

A Fase 6 precisa de um novo ADR sobre persistência atômica da intenção de
publicação, publisher recuperável e duplicatas. Não existe ainda ADR de Outbox.
Considere também confirms/routing, persistência do broker e testes de falhas
antes de declarar garantias de produção. A Fase 7 prevê logs estruturados,
correlation IDs e observabilidade. Adicione complexidade apenas para requisitos
concretos, preservando as camadas existentes.
