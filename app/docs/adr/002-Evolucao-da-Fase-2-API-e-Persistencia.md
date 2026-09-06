# ADR-002 - Evolucao da Fase 2: API e Persistencia

- Status: Em andamento
- Date: 2026-09-06
- Relacionado: ADR-001 - Core Domain e State Machine da Shipment

## 1. Contexto

A Fase 1 estabeleceu o dominio da Freight Event Intelligence Platform com a entidade `Shipment`, eventos imutaveis, state machine, regras de transicao e testes unitarios.

A evolucao seguinte introduziu a base da Fase 2, com Application Layer, persistencia PostgreSQL e uma camada HTTP FastAPI. Esta ADR registra o que foi efetivamente implementado ate o momento, as correcoes realizadas nos contratos entre camadas e as pendencias que ainda impedem considerar a Fase 2 concluida.

O codigo do repositorio e a fonte de verdade desta ADR. Funcionalidades descritas como planejadas ainda nao fazem parte da implementacao atual.

## 2. Estado da decisao

O projeto permanece na **Fase 2 - API/Persistence, em andamento**.

A base de dominio esta implementada. A Application Layer, a infraestrutura de persistencia e a montagem da camada FastAPI possuem uma primeira integracao validada. A Fase 2 ainda nao esta concluida porque faltam testes HTTP executados no ambiente, testes de integracao com PostgreSQL e politicas mais amplas de processamento.

## 3. Alteracoes implementadas

### 3.1 Dominio

O dominio possui:

- entidade `Shipment`;
- `ShipmentEvent` imutavel com `event_id`, `shipment_id`, tipo, origem e timestamps;
- `ShipmentEventType`;
- `ShipmentStatus`;
- `ShipmentStateMachine`;
- `InvalidStateTransition`;
- `ShipmentEventHandler`.

As transicoes implementadas sao:

```text
CREATED --PICKUP_SCHEDULED--> SCHEDULED
SCHEDULED --PICKUP_COMPLETED--> PICKED_UP
PICKED_UP --SHIPMENT_DEPARTED--> IN_TRANSIT
IN_TRANSIT --DELAY_DETECTED--> DELAYED
IN_TRANSIT --DELIVERED--> DELIVERED
DELAYED --SHIPMENT_DEPARTED--> IN_TRANSIT
DELAYED --DELIVERED--> DELIVERED
```

O handler valida se o evento pertence a shipment correta. Eventos `LOCATION_UPDATED` atualizam a localizacao; os demais eventos passam pela state machine.

### 3.2 Timestamps e localizacao

Os contratos do dominio foram alinhados para usar `event.occurred_at` como timestamp da alteracao causada pelo evento.

`change_status` e `update_location` agora atualizam `updated_at`.

A entidade `Shipment` possui:

- `current_latitude`;
- `current_longitude`;
- `last_location_at`.

O handler aceita payload de localizacao como `LocationUpdatedPayload` ou como dicionario compativel com o payload recebido pela API, convertendo o dicionario antes de chamar a entidade.

### 3.3 Application Layer

Foram definidos ports com `Protocol`:

- `ShipmentRepository` com `get` e `save`;
- `ShipmentEventRepository` com `save` e `list_by_shipment`.

Foram implementados os casos de uso:

- `CreateShipment`;
- `GetShipment`;
- `GetShipmentEvents`;
- `ReceiveShipmentEvent`.

`CreateShipment` gera o UUID e o timestamp UTC da nova shipment.

`ReceiveShipmentEvent` busca a shipment, processa o evento pelo handler e solicita o salvamento do evento e da shipment.

### 3.4 Persistencia

Foi adicionada infraestrutura SQLAlchemy com psycopg:

- `Base` declarativa;
- engine configurada por `DATABASE_URL`;
- `SessionLocal`;
- modelo `ShipmentModel`;
- modelo `ShipmentEventModel`;
- mapper entre entidade e ORM;
- `SQLAlchemyShipmentRepository`;
- `SQLAlchemyShipmentEventRepository`.

A tabela `shipments` armazena o estado atual da shipment. A tabela `shipment_events` armazena o historico de eventos, com foreign key para `shipments.id` e payload em JSONB.

O mapper converte o status armazenado como string para `ShipmentStatus` e preserva os campos de localizacao.

O repository de eventos converte payloads dataclass para dicionarios antes de grava-los no JSONB.

### 3.5 Migrations

A migration inicial cria:

- `shipments`;
- `shipment_events`;
- chaves primarias;
- foreign key do evento;
- indice unico de `reference_number`;
- indices de status, shipment, tipo de evento e `occurred_at`.

Uma segunda migration adiciona a `shipments`:

- `current_latitude`;
- `current_longitude`;
- `last_location_at`.

A migration de localizacao foi aplicada com sucesso por `alembic upgrade head` contra o PostgreSQL local.

### 3.6 API HTTP

Foi adicionada uma aplicacao FastAPI em `app/api/application.py`, com routers de shipments e eventos.

Rotas declaradas:

- `POST /shipments`;
- `GET /shipments/{shipment_id}`;
- `GET /shipments/{shipment_id}/events`;
- `POST /events`.

Schemas Pydantic implementados:

- `CreateShipmentRequest`;
- `ShipmentResponse`;
- `ShipmentEventRequest`;
- `ShipmentEventResponse`.

Os schemas validam campos obrigatorios, limites de tamanho, UUIDs, timestamps e tipos de evento.

As dependencias da API criam sessoes SQLAlchemy, repositories e casos de uso.

## 4. Testes implementados

A cobertura adicionada inclui:

- testes de entidade e state machine;
- imutabilidade de `ShipmentEvent`;
- rejeicao de evento de outra shipment;
- casos de uso com repositories em memoria;
- geracao de identidade e timestamp em `CreateShipment`;
- recebimento de evento e atualizacao da shipment;
- conversao do mapper com status e localizacao;
- validacao dos schemas de shipment;
- validacao dos schemas de evento;
- teste da aplicacao FastAPI.

A validacao anterior ao surgimento da camada API indicava 19 testes passando. Depois das correcoes da API, 25 testes das camadas de dominio, aplicacao, infraestrutura e schemas passam. Os testes HTTP ainda dependem da instalacao local do `httpx2`.

## 5. Problemas e inconsistencias atuais

### 5.1 Injecao de dependencia FastAPI

Corrigido. `get_receive_shipment_event_use_case` agora fornece `ShipmentEventHandler` e usa o nome correto do argumento `shipment_event_repository`.

As factories agora declaram `Depends(get_db)`. A aplicacao FastAPI pode ser importada e o OpenAPI confirma as rotas de shipments, eventos e health.

### 5.2 Dependencia do TestClient

O teste de aplicacao usa `fastapi.testclient.TestClient`, e a versao instalada do Starlette exige `httpx2`.

Corrigido no manifesto: `httpx2==2.12.0` foi adicionado a `requirements.txt`. A instalacao no ambiente virtual ainda nao foi executada, portanto a suite HTTP continua pendente de validacao local.

### 5.3 Health check inconsistente

Corrigido. `GET /health` agora retorna `{"status": "ok"}`.

O endpoint passou a fazer parte do contrato minimo da API.

### 5.4 Limite entre API e Application

Corrigido. A rota `POST /shipments` agora converte explicitamente `CreateShipmentRequest` para `CreateShipmentInput`.

Os contratos HTTP e de aplicacao permanecem separados.

### 5.5 Transacao

O ciclo da dependencia `get_db` agora faz `commit` quando a requisicao termina com sucesso, `rollback` quando ocorre uma excecao e sempre fecha a sessao.

Ainda nao existe Unit of Work dedicado, mas o recebimento do evento ocorre dentro da mesma sessao e do mesmo commit da requisicao.

### 5.6 Idempotencia

Foi implementada uma primeira politica de idempotencia no caso de uso:

- o port `ShipmentEventRepository` expoe `exists(event_id)`;
- o repository SQLAlchemy consulta a chave primaria antes do processamento;
- um evento ja persistido retorna a shipment sem reaplicar a transicao ou salvar duplicata.

Ainda nao existe tabela `processed_events` nem uma garantia completa contra corridas concorrentes entre consumidores.

### 5.7 Eventos fora de ordem

Eventos sao consultados ordenados por `occurred_at`, mas ainda nao existe politica de aceitacao, rejeicao, armazenamento ou reprocessamento de eventos recebidos fora de ordem.

### 5.8 Payloads por tipo de evento

O schema HTTP agora valida que `LOCATION_UPDATED` possua latitude e longitude numericas. O handler tambem normaliza o dicionario para `LocationUpdatedPayload`.

`ShipmentEvent.payload` permanece tipado como `object` no dominio e como `dict` no schema HTTP. Ainda nao existem schemas especificos para cada tipo de evento.

## 6. O que continua planejado

As seguintes funcionalidades ainda nao estao implementadas nesta etapa:

- RabbitMQ;
- producers e consumers;
- workers;
- retries;
- dead-letter queue;
- Redis;
- idempotencia completa para concorrencia e tabela dedicada;
- tratamento de eventos fora de ordem;
- Transactional Outbox;
- tabelas `processed_events` e `outbox_events`;
- logging estruturado;
- metricas Prometheus;
- dashboards Grafana;
- testes de integracao completos.

## 7. Consequencias

### Positivas

- O dominio continua independente de FastAPI, SQLAlchemy e PostgreSQL.
- A Application Layer possui contratos explicitos para repositories.
- O estado atual e o historico de eventos possuem modelos persistentes separados.
- A API possui schemas que validam a entrada antes do processamento.
- A migration permite evoluir o schema sem recriar as tabelas.
- Os principais contratos de dominio e aplicacao possuem testes unitarios.

### Negativas

- A Fase 2 ainda possui integracao incompleta entre API, casos de uso e banco em testes automatizados.
- A ausencia de Unit of Work dedicado limita a evolucao de operacoes atomicas mais complexas.
- A idempotencia atual nao cobre corridas concorrentes nem possui tabela dedicada.
- O tratamento de payloads ainda e pouco tipado.
- A suite HTTP ainda nao foi executada neste ambiente porque o pacote `httpx2` nao foi instalado no ambiente virtual.

## 8. Proximos passos

1. Instalar `httpx2==2.12.0` no ambiente virtual e executar a suite HTTP.
2. Adicionar testes funcionais para health, criacao, consulta e recebimento de eventos.
3. Adicionar testes de integracao dos endpoints e repositories com PostgreSQL.
4. Introduzir Unit of Work quando a atomicidade entre evento e shipment for necessaria.
5. Fortalecer idempotencia contra corridas concorrentes e avaliar tabela `processed_events`.
6. Definir politica de eventos fora de ordem.
7. Implementar RabbitMQ, retries, DLQ e Outbox em fases posteriores.

## 9. Decisao

A evolucao para a Fase 2 deve continuar com a separacao entre dominio, aplicacao, infraestrutura e API. A camada API pode orquestrar entrada e saida HTTP, mas nao deve absorver regras de negocio nem acessar o ORM diretamente fora das dependencias de infraestrutura.

A Fase 2 somente sera considerada concluida quando a suite HTTP puder ser executada no ambiente, os endpoints tiverem testes funcionais, as operacoes tiverem ciclo transacional definido e os repositories estiverem cobertos por testes de integracao.
