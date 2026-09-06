# Contexto tecnico atual: Freight Event Intelligence Platform

> Este documento descreve o estado real do codigo no repositorio. Funcionalidades futuras sao identificadas explicitamente como planejadas.

## 1. Etapa atual

O projeto esta na **Fase 2 - API/Persistence, em andamento**.

A Fase 1 foi implementada com entidade `Shipment`, eventos imutaveis, state machine, handler, excecoes de dominio e testes unitarios.

A Fase 2 possui contratos de aplicacao, casos de uso, uma camada FastAPI parcial, SQLAlchemy, PostgreSQL, repositories, mapper e Alembic. A API ja possui rotas e schemas, mas ainda nao esta operacional porque a montagem das dependencias FastAPI falha durante a importacao da aplicacao.

## 2. Estrutura real

```text
app/
├── api/
│   ├── application.py
│   ├── dependencies.py
│   ├── routes/
│   │   ├── events.py
│   │   └── shipments.py
│   └── schemas/
│       ├── event.py
│       └── shipment.py
├── application/
│   ├── ports/
│   │   ├── shipment_repository.py
│   │   └── shipment_event_repository.py
│   └── use_cases/
│       ├── create_shipment.py
│       ├── get_shipment.py
│       ├── get_shipment_events.py
│       └── receive_shipment_events.py
├── domain/
│   └── shipment/
│       ├── entities.py
│       ├── events.py
│       ├── event_handler.py
│       ├── exceptions.py
│       └── state_machine.py
├── infra/
│   └── database/
│       ├── base.py
│       ├── session.py
│       ├── mappers/shipment_mapper.py
│       ├── models/
│       │   ├── shipment.py
│       │   └── shipment_event.py
│       └── repositories/
│           ├── shipment.py
│           └── event.py
└── workers/
    └── __init__.py

alembic/
├── env.py
└── versions/
    ├── 34fe2111c108_create_shipment_tables.py
    └── 6f8e4c7a1b2d_add_shipment_location_fields.py

tests/
├── application/use_cases/test_shipment_use_cases.py
├── domain/shipment/
│   ├── test_entities.py
│   ├── test_events.py
│   └── test_state_machine.py
└── infra/database/test_shipment_mapper.py
```

O diretorio `api` possui uma aplicacao FastAPI, rotas, schemas Pydantic e dependencias de banco. O diretorio `workers` ainda contem apenas inicializacao e nao possui consumers, producers ou workers funcionais.

## 3. Dominio implementado

### Shipment

`Shipment` e uma dataclass mutavel com identidade, dados da carga, status, timestamps e localizacao atual.

`Shipment.create(...)` inicia o status como `CREATED`.

`change_status(event_type, occurred_at)` aplica a state machine e atualiza `updated_at` com o instante do evento.

`update_location(payload, occurred_at)` atualiza latitude, longitude, `last_location_at` e `updated_at`.

Ainda nao existem na entidade:

- idempotencia;
- processamento de eventos fora de ordem;
- controle de concorrencia;
- emissao de eventos de dominio.

### Eventos

`ShipmentEvent` e uma dataclass `frozen=True, slots=True` com:

- `event_id`;
- `shipment_id`;
- `event_type`;
- `source`;
- `occurred_at`;
- `received_at`;
- `payload`.

`LocationUpdatedPayload` e imutavel e possui `latitude` e `longitude`.

Tipos implementados:

- `SHIPMENT_CREATED`;
- `PICKUP_SCHEDULED`;
- `PICKUP_COMPLETED`;
- `SHIPMENT_DEPARTED`;
- `LOCATION_UPDATED`;
- `DELAY_DETECTED`;
- `DELIVERED`.

`SHIPMENT_CREATED` esta no catalogo, mas nao e uma transicao da state machine.

### State machine

```text
CREATED --PICKUP_SCHEDULED--> SCHEDULED
SCHEDULED --PICKUP_COMPLETED--> PICKED_UP
PICKED_UP --SHIPMENT_DEPARTED--> IN_TRANSIT
IN_TRANSIT --DELAY_DETECTED--> DELAYED
IN_TRANSIT --DELIVERED--> DELIVERED
DELAYED --SHIPMENT_DEPARTED--> IN_TRANSIT
DELAYED --DELIVERED--> DELIVERED
```

Transicoes nao cadastradas lancam `InvalidStateTransition`.

### Event handler

`ShipmentEventHandler.handle(shipment, event)`:

1. valida se `event.shipment_id` pertence a shipment;
2. normaliza payload `dict` de `LOCATION_UPDATED` para `LocationUpdatedPayload`;
3. atualiza localizacao ou aplica a transicao correspondente;
4. usa `event.occurred_at` como timestamp da alteracao.

O handler nao persiste, nao faz commit, nao deduplica e nao reprocessa eventos atrasados.

## 4. Application Layer

### Ports

`ShipmentRepository` define `get` e `save`.

`ShipmentEventRepository` define `save` e `list_by_shipment`.

### Use cases

- `CreateShipment` gera UUID e timestamp UTC, cria a entidade e chama o repository.
- `GetShipment` consulta uma shipment pelo ID.
- `GetShipmentEvents` lista eventos de uma shipment.
- `ReceiveShipmentEvent` busca a shipment, processa o evento pelo handler e salva evento e shipment.

Os casos de uso possuem testes com repositories em memoria para validar os contratos principais.

## 5. API implementada

`app.api.application` cria uma instancia FastAPI com titulo `Freight Event Intelligence Platform`, versao `0.1.0`, e inclui os routers de shipments e events.

Rotas declaradas:

- `POST /shipments`: recebe `CreateShipmentRequest` e retorna `ShipmentResponse`;
- `GET /shipments/{shipment_id}`: consulta uma shipment e retorna `404` quando nao encontrada;
- `GET /shipments/{shipment_id}/events`: lista eventos da shipment;
- `POST /events`: cria um `ShipmentEvent` a partir de `ShipmentEventRequest` e chama `ReceiveShipmentEvent`.

Schemas implementados:

- `CreateShipmentRequest`, com limites de tamanho e campos obrigatorios;
- `ShipmentResponse`, incluindo status, timestamps e localizacao;
- `ShipmentEventRequest`, com UUIDs, tipo de evento, timestamp e payload dict;
- `ShipmentEventResponse`.

Existem testes de validacao dos schemas e um teste de aplicacao que espera `GET /health` e validacao HTTP `422` para payload invalido. No entanto, a rota `/health` nao esta registrada no codigo atual.

As dependencias de API criam sessoes e repositories SQLAlchemy, mas a configuracao atual ainda nao injeta corretamente todas as dependencias necessarias no FastAPI.

## 6. Persistencia implementada

### Banco e sessao

- PostgreSQL 17 e definido no Docker Compose.
- SQLAlchemy usa psycopg.
- `DATABASE_URL` configura a conexao; existe uma URL padrao local.
- `SessionLocal` usa `autoflush=False` e `expire_on_commit=False`.

### Modelos

`ShipmentModel` representa `shipments` com UUID, referencia unica, dados da carga, status, timestamps e:

- `current_latitude`;
- `current_longitude`;
- `last_location_at`.

`ShipmentEventModel` representa `shipment_events` com chave primaria `event_id`, foreign key para shipment, tipo, source, timestamps e payload JSONB.

O repository de eventos converte dataclasses de payload para dicionarios antes de persistir.

O mapper converte status ORM para `ShipmentStatus` e preserva os campos de localizacao.

### Alembic

Existem duas migrations:

1. cria `shipments` e `shipment_events`;
2. adiciona os campos de localizacao em `shipments`.

A migration de localizacao foi aplicada com sucesso usando `alembic upgrade head` contra o PostgreSQL local.

Ainda nao existem tabelas `processed_events` ou `outbox_events`.

## 7. Pontos ainda pendentes ou que precisam de decisao

### Transacao

Os repositories alteram a sessao, mas nao fazem `commit` ou `rollback`. Tambem nao existe Unit of Work. O responsavel pelo ciclo transacional ainda precisa ser definido antes de expor o fluxo como operacao persistente de producao.

### Idempotencia

`event_id` e chave primaria de `shipment_events`, mas nao existe tratamento completo para evento duplicado, tabela `processed_events` ou politica de conflito.

### Eventos fora de ordem

A consulta de eventos ordena por `occurred_at`, mas ainda nao existe politica de aceitacao, rejeicao, armazenamento ou reprocessamento de eventos atrasados.

### Payloads

O dominio usa `object` para `payload`. O handler valida apenas o payload de localizacao. Schemas especificos por tipo de evento ainda nao existem.

### Testes de infraestrutura

Ainda faltam testes de:

- repositories SQLAlchemy;
- commit e rollback;
- migration contra banco;
- persistencia e leitura de eventos;
- falhas de constraint;
- concorrencia.

## 8. Funcionalidades planejadas

Ainda nao estao implementados:

- RabbitMQ;
- producer, consumer e workers;
- retries e dead-letter queue;
- Redis;
- idempotencia completa;
- tratamento de eventos fora de ordem;
- Transactional Outbox;
- logging estruturado;
- metricas Prometheus;
- dashboards Grafana;
- health check HTTP.

Esses itens continuam sendo evolucoes futuras e nao representam capacidades atuais do sistema.

## 9. Validacao atual

A validacao do estado atual apresentou:

- `pytest -q`: falha durante a coleta dos testes de API porque `starlette.testclient` exige o pacote `httpx2`, que nao esta em `requirements.txt`;
- importar `app.api.application` falha durante o registro das rotas, pois a dependencia `get_db` usa `Session` sem ser declarada com `Depends`, fazendo o FastAPI tentar trata-la como campo de resposta;
- o teste de API espera `GET /health`, mas essa rota nao existe;
- os testes de schemas da API estao presentes;
- os testes de dominio, aplicacao e mapper existiam e estavam verdes antes da introducao da camada API;
- `alembic upgrade head` ja aplicou a migration de localizacao com sucesso no PostgreSQL.

Neste momento, a aplicacao FastAPI nao pode ser importada ou testada de ponta a ponta. A camada de persistencia ainda precisa de testes de integracao.

## 10. Diferencas e problemas arquiteturais atuais

1. A API foi adicionada ao codigo, mas o contexto anterior ainda a descrevia como planejada.
2. `get_receive_shipment_event_use_case` instancia `ReceiveShipmentEvent` sem fornecer o `event_handler` obrigatorio.
3. `get_db` e usado como dependencia indireta sem `Depends(get_db)` nas funcoes de factory; isso quebra a montagem das rotas no FastAPI.
4. A rota `POST /shipments` passa o schema Pydantic diretamente ao caso de uso, embora o caso de uso espere `CreateShipmentInput`. Hoje os atributos possuem nomes compativeis, mas o limite entre API e Application nao esta explicito.
5. A rota `POST /events` passa `request.payload` como dict. O handler agora normaliza payload de localizacao, mas outros tipos de payload ainda nao possuem schemas especificos.
6. Nao existe commit ou rollback explicito depois das operacoes HTTP. Mesmo com a dependencia corrigida, a API nao garante persistencia efetiva sem um responsavel transacional.
7. O teste de health expressa um contrato que nao esta implementado.
8. `httpx2` nao esta declarado nas dependencias, impedindo a coleta do teste com `TestClient` neste ambiente.

## 11. Proximos passos

1. Corrigir a montagem das dependencias FastAPI, incluindo `Depends(get_db)` e a injecao de `ShipmentEventHandler`.
2. Decidir se `/health` faz parte do contrato atual; se sim, implementar a rota e seu teste.
3. Adicionar a dependencia de teste compativel com a versao instalada do Starlette ou ajustar a estrategia de testes HTTP.
4. Criar conversoes explicitas entre schemas HTTP e inputs da Application Layer.
5. Definir o responsavel por `commit` e `rollback` nas requisicoes.
6. Introduzir Unit of Work quando for necessario garantir atomicidade entre shipment e evento.
7. Criar testes de integracao dos endpoints e repositories com PostgreSQL.
8. Definir schemas e validacao de payload por tipo de evento.
9. Definir e implementar idempotencia antes de adotar mensageria.
10. Implementar RabbitMQ, consumers, retries, DLQ e Outbox em fases separadas.

## 12. Resumo

O dominio e os contratos principais da aplicacao estao implementados. A camada FastAPI foi adicionada com rotas, schemas e dependencias, mas ainda esta quebrada na inicializacao por problemas de injecao de dependencias e possui um teste de health sem rota correspondente. O projeto esta no meio da Fase 2: a API existe estruturalmente, porem ainda precisa ser corrigida e integrada de forma operacional antes de ser considerada concluida.
