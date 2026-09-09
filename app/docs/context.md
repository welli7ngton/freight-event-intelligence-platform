# Current Technical Context: Freight Event Intelligence Platform

> Este documento descreve o estado real do codigo no repositorio. Funcionalidades futuras sao identificadas explicitamente como planejadas.

## 1. Current phase

O projeto esta na **Fase 2 - API/Persistence, em andamento**.

A Fase 1 foi implementada com entidade `Shipment`, eventos imutaveis, state machine, handler, excecoes de dominio e testes unitarios.

A Fase 2 possui contratos de aplicacao, casos de uso, uma camada FastAPI funcional, SQLAlchemy, PostgreSQL, repositories, mapper e Alembic. A API ja possui rotas e schemas e a aplicacao FastAPI importa corretamente em ambiente local. A parte de integracao com PostgreSQL real continua pendente, mas a camada API e de aplicacao esta operacional no codigo atual.

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

O diretorio `api` possui uma aplicacao FastAPI, rotas, schemas Pydantic e dependencias de banco. O diretorio `workers` possui o worker RabbitMQ, que converte a mensagem versionada e reutiliza `ReceiveShipmentEvent`; ele nao possui regras de dominio.

## 3. Dominio implementado

### Shipment

`Shipment` e uma dataclass mutavel com identidade, dados da carga, status, timestamps e localizacao atual.

`Shipment.create(...)` inicia o status como `CREATED`.

`change_status(event_type, occurred_at)` aplica a state machine e atualiza `updated_at` com o instante do evento.

`update_location(payload, occurred_at)` atualiza latitude, longitude, `last_location_at` e `updated_at`. A shipment tambem preserva `last_lifecycle_at`, separado do tempo da localizacao.

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

`ShipmentEventRepository` define `exists`, `save` e `list_by_shipment`.

### Use cases

- `CreateShipment` gera UUID e timestamp UTC, cria a entidade `Shipment`, cria o evento `SHIPMENT_CREATED` e persiste tanto a shipment quanto o evento no mesmo fluxo de aplicacao.
- `GetShipment` consulta uma shipment pelo ID.
- `GetShipmentEvents` lista eventos de uma shipment.
- `ReceiveShipmentEvent` rejeita `SHIPMENT_CREATED`, busca a shipment, verifica duplicidade por `event_id`, processa o evento pelo handler e salva o evento e a shipment atualizada.

Os casos de uso possuem testes com repositories em memoria para validar os contratos principais. O teste de criacao agora verifica que a `Shipment` e o evento `SHIPMENT_CREATED` sao gerados e persistidos no mesmo caso de uso.

### Fronteira de responsabilidade

A separacao atual continua sendo a seguinte:

- `API/controller`: recebe a request HTTP, valida os schemas, converte DTO em input da application e devolve a resposta. O controller nao cria eventos de dominio diretamente nem implementa regras de negocio.
- `Application/Use Case`: orquestra a operacao de negocio completa. `CreateShipment` e responsavel por criar a entidade, criar o `ShipmentEvent(SHIPMENT_CREATED)`, persistir ambos e devolver a entidade atualizada.
- `Domain`: continua responsavel pela vida da Shipment, transicoes de estado, atualizacao de localizacao, invariantes e validacoes de negocio.
- `Infrastructure`: repositories persistem estado e eventos; nao decidem regras de negocio nem finalizam a transacao.

## 5. API implementada

`app.api.application` cria uma instancia FastAPI com titulo `Freight Event Intelligence Platform`, versao `0.1.0`, e inclui os routers de shipments e events.

A API atual expõe os seguintes contratos:

- `GET /health`: retorna `{"status": "ok"}`;
- `POST /shipments`: recebe `CreateShipmentRequest`, cria a `Shipment`, registra internamente o evento `SHIPMENT_CREATED` e retorna `ShipmentResponse`;
- `GET /shipments/{shipment_id}`: consulta uma shipment e retorna `404` quando nao encontrada;
- `GET /shipments/{shipment_id}/events`: lista eventos da shipment;
- `POST /events`: recebe `ShipmentEventRequest` para eventos do lifecycle de uma shipment ja existente e chama `ReceiveShipmentEvent`.

O contrato de criacao do sistema permanece estritamente orientado a `POST /shipments`. Não existe um fluxo alternativo de criacao via `POST /events`.

Schemas implementados:

- `CreateShipmentRequest`, com limites de tamanho e campos obrigatorios;
- `ShipmentResponse`, incluindo status, timestamps e localizacao;
- `ShipmentEventRequest`, com UUIDs, tipo de evento, timestamp e payload dict;
- `ShipmentEventResponse`.

Os testes de API validam `GET /health`, criacao de shipment, consulta de shipment, consulta de eventos e envio de eventos do lifecycle. O contrato atual reconhece que a criacao de shipment e a criacao do evento `SHIPMENT_CREATED` sao uma mesma operacao de negocio.

`POST /events` nao aceita `SHIPMENT_CREATED`. O use case e o handler rejeitam
esse tipo com `InvalidShipmentEvent`, e a rota traduz a excecao para HTTP 422.
Nao existe teste HTTP especifico para esse status; a rejeicao esta coberta nos
testes do use case e do handler.

## 6. Atomicidade atual da criacao de Shipment

A fronteira transacional atual e definida pela dependencia `get_db()` em `app.api.dependencies`.

Essa dependencia:

- cria a `Session` do SQLAlchemy;
- disponibiliza a mesma sessao para os repositories da request;
- executa `commit()` quando a operacao termina com sucesso;
- executa `rollback()` quando ocorre excecao;
- fecha a sessao ao final.

A implementacao atual usa a mesma `Session` para os dois repositories da criacao:

```text
ShipmentRepository
        |
        +---- mesma Session SQLAlchemy ----+
                                           |
ShipmentEventRepository                   |
        |                                  |
        +----------------------------------+
```

Isso significa que a operacao de criacao de Shipment e registro do evento `SHIPMENT_CREATED` ocorre dentro da mesma transacao da request.

O fluxo conceitual de `POST /shipments` e:

```text
CreateShipment
    |
    +-- cria Shipment
    |
    +-- cria ShipmentEvent(SHIPMENT_CREATED)
    |
    +-- persiste ambos na mesma Session
    |
    +-- commit transacional da request
```

A semantica correta e que a criacao do evento nao e uma segunda request HTTP nem uma operacao separada do controller. Ela e um efeito de negocio interno do use case `CreateShipment`.

### Comportamento esperado

SUCESSO:

```text
Shipment.save()
      +
ShipmentEvent.save()
      |
      v
   COMMIT da request
      |
      v
ambos persistidos
```

FALHA:

```text
Shipment.save()
      +
ShipmentEvent.save()
      |
      v
   EXCEPTION
      |
      v
  ROLLBACK da request
      |
      v
nenhum dos dois deve permanecer persistido
```

Importante: a atomicidade atual nao depende de `commit` individual dentro dos repositories. Os repositories persistem no estado da sessao; a finalizacao transacional e responsabilidade da infraestrutura de sessao/request em `get_db()`.

## 7. SHIPMENT_CREATED e semantica de evento

`SHIPMENT_CREATED` e um evento historico/auditoria de que a shipment foi criada. Ele nao deve ser processado pelo `ShipmentEventHandler` como se fosse uma transicao normal do estado da shipment.

A entidade comeca no estado `CREATED` atraves de `Shipment.create()`. O evento `SHIPMENT_CREATED` registra esse fato, mas nao gera uma transicao artificial:

```text
Shipment.create()
    -> Shipment.status = CREATED

ShipmentEvent(
    event_type = SHIPMENT_CREATED
)
```

A regra correta e que o evento e persistido em paralelo com a criacao da entidade, e nao processado por `ShipmentEventHandler` como `CREATED -> CREATED`.

Os eventos subsequentes do lifecycle, como `PICKUP_SCHEDULED`, `PICKUP_COMPLETED`, `SHIPMENT_DEPARTED`, `DELAY_DETECTED`, `DELIVERED` e `LOCATION_UPDATED`, continuam seguindo o fluxo de processamento normal do `ShipmentEventHandler` e da state machine.

## 8. Timestamps e ordem de eventos

A arquitetura continua distinguindo claramente entre:

- `occurred_at`: quando o fato aconteceu no dominio;
- `received_at`: quando o sistema recebeu/registrou o evento.

Para `SHIPMENT_CREATED`, o valor de `occurred_at` deve coincidir com o momento de criacao da shipment, ou seja:

```text
Shipment.created_at == ShipmentEvent(SHIPMENT_CREATED).occurred_at
```

Essa diferenca e importante para evoluir futuramente a politica de eventos fora de ordem. Hoje o sistema ordena eventos por `occurred_at` em consultas e em alguns fluxos, mas ainda nao define uma politica robusta de aceitacao/reprocessamento de eventos atrasados.

## 9. Persistencia implementada

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

## 10. Idempotencia atual e limites conhecidos

O repositorio de eventos define `exists(event_id)` e a implementacao SQLAlchemy verifica a chave primaria antes do processamento. Isso oferece protecao contra processamento repetido em cenarios sequenciais e e usado por `ReceiveShipmentEvent` antes de aplicar a transicao e salvar o evento. Para uma corrida concorrente, a constraint primaria de `shipment_events.event_id` e o limite final: a rota faz flush, executa rollback quando a constraint e violada e retorna a shipment persistida como resultado idempotente.

Essa estrategia nao cria uma tabela dedicada `processed_events` e nao representa estados intermediarios de processamento. Ela e adequada ao fluxo sincrono atual, no qual o evento e a projecao da shipment pertencem a mesma transacao. Efeitos externos futuros continuam exigindo Outbox e consumidores idempotentes.

## 11. Eventos fora de ordem

A plataforma persiste todo evento valido, inclusive os recebidos fora de ordem. O campo `processing_status` em `shipment_events` registra `APPLIED` quando o evento atualiza a projecao corrente ou `STORED_OUT_OF_ORDER` quando permanece apenas no historico. Localizacoes atrasadas nao sobrescrevem uma localizacao mais recente; lifecycle atrasado nao altera o status corrente. Os dois relogios sao independentes (`last_location_at` e `last_lifecycle_at`), portanto uma localizacao mais nova nao bloqueia uma transicao de lifecycle valida. Nao existe replay historico nesta versao; ele podera ser adicionado quando houver necessidade de reconciliacao.

## 12. Testes e validacao do estado atual

Os testes presentes no repositorio confirmam o contrato atual de criacao e processamento de eventos:

- testes de dominio validam `Shipment`, `ShipmentEvent` e `ShipmentStateMachine`;
- testes de aplicacao validam `CreateShipment` e `ReceiveShipmentEvent` com repositories em memoria;
- testes de API validam health, criacao de shipment, consulta de shipment, consulta de eventos e recebimento de evento do lifecycle;
- o teste de infraestrutura verifica rollback quando a persistencia do evento de criacao falha;
- os testes de aplicacao verificam a rejeicao de `SHIPMENT_CREATED` no use case e no handler;
- o teste mais importante para a semantica atual verifica que a criacao de shipment inclui o registro do evento `SHIPMENT_CREATED` no mesmo fluxo do use case.

Validacao atual do repositorio: a suite unitária e de API executa com sucesso em ambiente local (`41 passed` em pytest, com integracao excluida por padrao), confirmando que a aplicacao FastAPI e os contratos principais estao funcionando no estado atual do codigo. Houve uma advertencia de deprecacao do Starlette/AnyIO, sem falha de teste.

Acoes de integracao com PostgreSQL ainda sao pendentes para validar com banco real:

- commit e rollback em fluxo de request;
- persistencia real de shipment e eventos;
- violacao de constraint;
- concorrencia;
- integracao de endpoints com banco.

## 13. Funcionalidades planejadas

Ainda nao estao implementados:

- Redis;
- idempotencia completa concorrente;
- politica formal de eventos fora de ordem;
- Transactional Outbox;
- logging estruturado;
- metricas Prometheus;
- dashboards Grafana.

Esses itens continuam sendo evolucoes futuras e nao representam capacidades atuais do sistema.

## 14. Resumo

O dominio e os contratos principais da aplicacao estao implementados e consistentes com a estrutura atual do codigo. A API expõe o contrato real de criacao, consulta e processamento de eventos, e a operacao de criacao de Shipment agora inclui o registro do evento `SHIPMENT_CREATED` dentro do mesmo `CreateShipment`. A aplicacao foi validada em contexto de teste e importa corretamente, sem erros de montagem da FastAPI no estado atual do repositorio.

A transacao atual e tratada na infraestrutura de sessao por request (`get_db()`), que executa `commit` em caso de sucesso e `rollback` em caso de excecao. Essa fronteira e a responsavel por manter `Shipment` e `SHIPMENT_CREATED` consistentes no mesmo ciclo transacional. O restante da arquitetura continua alinhado com a separacao entre dominio, aplicacao, persistencia e API, sem mover regras de negocio para controllers ou repositories.
