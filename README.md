# Freight Event Intelligence Platform

Backend orientado a eventos para receber e processar eventos do ciclo de vida de
shipments. O projeto e um Modular Monolith em Python, construido para estudar
DDD, separacao de camadas, persistencia e evolucao para processamento
assincrono.

## Estado atual

O projeto esta na Fase 2, com o dominio, casos de uso, persistencia SQLAlchemy,
migrations Alembic e uma API FastAPI inicial implementados.

Ja existem:

- entidade `Shipment` e eventos imutaveis;
- state machine para transicoes de status;
- validacao de eventos da shipment correta;
- idempotencia inicial por `event_id`;
- repositories definidos por ports da Application Layer;
- PostgreSQL via Docker Compose;
- API para criar e consultar shipments e receber eventos;
- testes unitarios de dominio, aplicacao, schemas e mapper;
- Ruff, pytest e Taskipy centralizados no `pyproject.toml`.

Ainda nao fazem parte do sistema:

- RabbitMQ e consumers;
- workers, retries e dead-letter queue;
- Redis;
- tratamento completo de eventos fora de ordem;
- Transactional Outbox;
- observabilidade com Prometheus e Grafana.

## Arquitetura

```text
app/
├── api/                  # FastAPI, rotas, schemas e dependencias
├── application/          # ports e casos de uso
├── domain/               # entidades, eventos e regras de negocio
├── infra/database/       # SQLAlchemy, repositories, mappers e sessao
└── workers/              # reservado para processamento assincrono

alembic/                  # migrations do banco
tests/                    # testes por camada
```

O dominio nao depende de FastAPI, SQLAlchemy ou PostgreSQL. A Application Layer
orquestra os casos de uso por meio de contratos, enquanto a infraestrutura
implementa esses contratos.

## Requisitos

- Python 3.12 ou superior;
- Docker Desktop com Docker Compose;
- PostgreSQL local ou o servico PostgreSQL fornecido pelo Compose.

## Setup local

No PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Suba o PostgreSQL e aplique as migrations:

```powershell
task setup
```

O banco local usa estes valores padrao:

```text
Host: localhost
Port: 5432
Database: freight_events
User: postgres
Password: postgres
```

Para usar outra conexao, defina `DATABASE_URL` antes de executar a API ou as
migrations:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://usuario:senha@host:5432/banco"
```

## Executar a API

```powershell
task api
```

A API fica disponivel em `http://127.0.0.1:8000`.

Documentacao interativa:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Health check: `GET /health`

## Endpoints

### Criar shipment

```http
POST /shipments
Content-Type: application/json
```

```json
{
  "reference_number": "SHIP-001",
  "origin": "Fortaleza",
  "destination": "Sao Paulo",
  "carrier": "Carrier A"
}
```

### Consultar shipment

```http
GET /shipments/{shipment_id}
```

Retorna `404` quando a shipment nao existe.

### Consultar eventos

```http
GET /shipments/{shipment_id}/events
```

Os eventos sao retornados ordenados por `occurred_at`.

### Receber evento

```http
POST /events
Content-Type: application/json
```

```json
{
  "event_id": "11111111-1111-1111-1111-111111111111",
  "shipment_id": "22222222-2222-2222-2222-222222222222",
  "event_type": "PICKUP_SCHEDULED",
  "source": "carrier_api",
  "occurred_at": "2026-09-06T12:00:00Z",
  "payload": {}
}
```

Para `LOCATION_UPDATED`, o payload deve conter latitude e longitude numericas:

```json
{
  "latitude": -3.7319,
  "longitude": -38.5267
}
```

Transicoes invalidas retornam `409`. Shipment inexistente retorna `404`.

## Estados da shipment

```text
CREATED --PICKUP_SCHEDULED--> SCHEDULED
SCHEDULED --PICKUP_COMPLETED--> PICKED_UP
PICKED_UP --SHIPMENT_DEPARTED--> IN_TRANSIT
IN_TRANSIT --DELAY_DETECTED--> DELAYED
IN_TRANSIT --DELIVERED--> DELIVERED
DELAYED --SHIPMENT_DEPARTED--> IN_TRANSIT
DELAYED --DELIVERED--> DELIVERED
```

O dominio usa `occurred_at` para atualizar `updated_at` quando um evento altera
o estado ou a localizacao. `received_at` registra quando o sistema recebeu o
evento.

## Testes e qualidade

```powershell
task test-fast       # testes em modo resumido
task test            # testes completos
task test-api        # testes da camada API
task lint            # Ruff lint
task lint-fix        # corrige lint automaticamente
task format          # formata com Ruff
task format-check    # verifica formatacao
task check           # formatacao, lint e testes
task compile         # compila app e testes
```

O comando recomendado antes de abrir uma alteracao e:

```powershell
task check
```

## Banco e migrations

```powershell
task db-up          # inicia PostgreSQL
task db-down        # para os servicos
task db-logs        # acompanha os logs
task db-migrate     # aplica migrations
task db-current     # mostra a revision atual
task db-history     # mostra o historico
task db-rollback    # desfaz a ultima migration
```

Para criar uma migration autogerada:

```powershell
task db-revision -- "descricao da alteracao"
```

Revise sempre uma migration autogerada antes de aplica-la.

## Decisoes e documentacao

As decisoes arquiteturais ficam em [app/docs/adr](app/docs/adr):

- [ADR-001 - Core Domain e State Machine da Shipment](app/docs/adr/001-Core-Domain-e-State%20Machine-da-Shipment.md)
- [ADR-002 - Evolucao da Fase 2: API e Persistencia](app/docs/adr/002-Evolucao-da-Fase-2-API-e-Persistencia.md)

## Proximos passos

1. Adicionar testes de integracao dos repositories e endpoints com PostgreSQL.
2. Definir uma Unit of Work quando a atomicidade exigir mais do que o ciclo atual da sessao.
3. Fortalecer idempotencia contra concorrencia.
4. Definir a politica de eventos fora de ordem.
5. Introduzir RabbitMQ, workers, retries, DLQ e Outbox em fases separadas.
