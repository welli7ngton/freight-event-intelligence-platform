# Freight Event Intelligence Platform — Plano de Implementação

> **Objetivo:** evoluir o estado atual do projeto de forma incremental, guiada por problemas reais de engenharia, preservando a arquitetura existente e evitando complexidade prematura.
>
> **Formato deste documento:** instruções operacionais otimizadas para execução por uma IA assistente de desenvolvimento.

---

# 1. Regras globais de execução

## 1.1 Fonte de verdade

Antes de implementar qualquer item:

1. Inspecione o código existente.
2. Compare o estado real do repositório com este plano.
3. Não assuma que funcionalidades planejadas já foram implementadas.
4. Preserve as decisões arquiteturais existentes, salvo quando uma mudança for explicitamente necessária e justificada.
5. Não mova regras de negócio para controllers, repositories ou workers.

## 1.2 Princípios obrigatórios

- Implementar uma fase por vez.
- Não iniciar a próxima fase antes de validar a atual.
- Preferir mudanças pequenas e testáveis.
- Criar testes para comportamentos novos e cenários de falha relevantes.
- Não introduzir tecnologias sem um problema concreto que elas resolvam.
- Não implementar microservices, Kafka, Redis, Kubernetes, CQRS completo ou Event Sourcing fora de um requisito futuro explícito.
- Documentar decisões arquiteturais relevantes usando ADRs.
- Não realizar refactors amplos sem necessidade funcional ou arquitetural.
- Preservar a separação atual entre `domain`, `application`, `api`, `infra` e `workers`.

## 1.3 Ordem de trabalho

Para cada tarefa:

```text
INSPECIONAR
    ↓
ENTENDER O ESTADO ATUAL
    ↓
DEFINIR A MUDANÇA MÍNIMA
    ↓
IMPLEMENTAR
    ↓
TESTAR
    ↓
VALIDAR
    ↓
ATUALIZAR DOCUMENTAÇÃO
```

## 1.4 Definition of Done

Uma tarefa só está concluída quando:

- o código está implementado;
- os testes relevantes foram criados ou atualizados;
- a suíte existente continua funcionando;
- o comportamento foi validado no nível adequado;
- não existem responsabilidades arquiteturais deslocadas;
- a documentação relevante foi atualizada.

---

# 2. Estado inicial assumido

O plano parte do seguinte estado:

- Fase 1 concluída.
- Fase 2 — API/Persistence em andamento.
- Domínio de `Shipment` implementado.
- Eventos imutáveis implementados.
- State machine implementada.
- Event handler implementado.
- Casos de uso implementados.
- FastAPI funcional.
- SQLAlchemy e PostgreSQL configurados.
- Repositories e mapper implementados.
- Alembic configurado.
- Fluxo de criação de shipment registra `SHIPMENT_CREATED` na mesma transação da request.
- A persistência contra PostgreSQL real ainda precisa de validação de integração mais abrangente.
- A idempotência atual é apenas parcialmente defensiva.
- Não existe política formal para eventos fora de ordem.
- RabbitMQ, workers, retries, DLQ, Outbox e observabilidade ainda não foram implementados.

---

# 3. Roadmap

```text
ESTADO ATUAL
    │
    ▼
FASE 2.5 — Persistence Validation
    │
    ▼
FASE 2.6 — Transaction & Concurrency Validation
    │
    ▼
FASE 3 — Reliable Event Ingestion
    │
    ├── Idempotência concorrente
    └── Eventos fora de ordem
    │
    ▼
FASE 4 — Asynchronous Processing
    │
    └── RabbitMQ + Workers
    │
    ▼
FASE 5 — Failure Recovery
    │
    ├── Retries
    └── Dead Letter Queue
    │
    ▼
FASE 6 — Transactional Outbox
    │
    ▼
FASE 7 — Observability & Production Readiness
```

---

# FASE 2.5 — Persistence Validation

## Objetivo

Validar que a camada de infraestrutura funciona corretamente contra um PostgreSQL real.

A prioridade desta fase é testar a arquitetura existente antes de adicionar novas camadas de complexidade.

## Não fazer nesta fase

- Não adicionar RabbitMQ.
- Não adicionar workers.
- Não implementar Outbox.
- Não criar uma nova estratégia completa de idempotência.
- Não alterar regras do domínio sem que os testes revelem um problema real.

---

## Tarefa 2.5.1 — Criar infraestrutura para testes de integração

### Objetivo

Criar um ambiente reproduzível para testes contra PostgreSQL.

### Ações

- Inspecionar a configuração atual de banco.
- Definir como o banco de testes será isolado.
- Garantir limpeza previsível entre testes.
- Garantir que migrations sejam aplicadas antes da execução dos testes, quando necessário.
- Separar claramente testes unitários e testes de integração.

### Estrutura sugerida

```text
tests/
├── domain/
├── application/
├── api/
└── integration/
    ├── database/
    └── api/
```

### Critérios de aceite

- [ ] É possível executar testes de integração de forma isolada.
- [ ] Os testes não dependem do banco de desenvolvimento.
- [ ] O estado do banco é previsível entre execuções.
- [ ] Falhas de infraestrutura são claramente identificáveis.

---

## Tarefa 2.5.2 — Testar ShipmentRepository com PostgreSQL real

### Cenários

- [ ] Persistir uma shipment.
- [ ] Buscar uma shipment existente.
- [ ] Retornar `None` ou comportamento equivalente para shipment inexistente.
- [ ] Validar reconstrução da entidade de domínio.
- [ ] Validar status.
- [ ] Validar timestamps.
- [ ] Validar latitude e longitude.
- [ ] Validar `last_location_at`.

### Fluxo

```text
Domain Shipment
      ↓
Repository.save()
      ↓
PostgreSQL
      ↓
Repository.get()
      ↓
Domain Shipment
```

### Critério de aceite

A entidade recuperada deve preservar corretamente o estado relevante da entidade persistida.

---

## Tarefa 2.5.3 — Testar ShipmentEventRepository com PostgreSQL real

### Cenários

- [ ] Persistir evento.
- [ ] Consultar existência por `event_id`.
- [ ] Listar eventos por shipment.
- [ ] Validar ordenação.
- [ ] Validar `occurred_at`.
- [ ] Validar `received_at`.
- [ ] Validar payload JSON.
- [ ] Validar reconstrução de payload de localização.

### Atenção

Não modificar a semântica atual de eventos apenas para facilitar os testes.

Os testes devem validar o contrato existente.

---

## Tarefa 2.5.4 — Testar constraints reais do banco

### Cenários mínimos

#### Duplicate shipment reference

```text
Create Shipment A
        ↓
reference_number = X

Create Shipment B
        ↓
reference_number = X

Expected:
Constraint violation
```

#### Duplicate event ID

```text
Save Event A
      ↓
event_id = X

Save Event B
      ↓
event_id = X

Expected:
Constraint violation or defined duplicate behavior
```

#### Invalid shipment reference

```text
Save Event
    ↓
shipment_id inexistente

Expected:
Foreign key violation
```

### Objetivo arquitetural

Determinar quais garantias são:

```text
Application responsibility
```

e quais são:

```text
Database responsibility
```

---

## Tarefa 2.5.5 — Testar atomicidade real de criação

### Cenário

```text
Shipment.save()
      ↓
SUCCESS
      ↓
ShipmentEvent.save()
      ↓
FORCED FAILURE
      ↓
ROLLBACK
```

### Resultado esperado

```text
Shipment inexistente
AND
ShipmentEvent inexistente
```

### Critério de aceite

A atomicidade deve ser comprovada contra PostgreSQL real.

---

## Tarefa 2.5.6 — Testar fluxo HTTP completo

Validar:

```text
HTTP Request
    ↓
FastAPI
    ↓
Use Case
    ↓
Repository
    ↓
PostgreSQL
```

### Cenários

- [ ] Criar shipment.
- [ ] Consultar shipment.
- [ ] Consultar eventos.
- [ ] Enviar evento de lifecycle.
- [ ] Consultar estado atualizado.
- [ ] Validar resposta para shipment inexistente.

### Definition of Done da Fase 2.5

- [ ] Repositories validados contra PostgreSQL.
- [ ] Constraints importantes testadas.
- [ ] Rollback validado.
- [ ] Fluxo HTTP integrado validado.
- [ ] Suíte unitária continua funcionando.
- [ ] Suíte de integração documentada.

---

# FASE 2.6 — Transaction & Concurrency Validation

## Objetivo

Descobrir e reproduzir os limites da arquitetura transacional atual antes de implementar soluções.

## Regra obrigatória

**Primeiro reproduzir o problema. Depois projetar a solução.**

---

## Tarefa 2.6.1 — Simular processamento concorrente do mesmo evento

### Cenário

```text
Request A ──────┐
                │
                ▼
            Event X
                ▲
                │
Request B ──────┘
```

Ambos tentam processar o mesmo `event_id`.

### Objetivo

Verificar se o fluxo atual:

```text
exists()
   ↓
process()
   ↓
save()
```

é seguro sob concorrência.

### Testar

- [ ] Duas transações independentes.
- [ ] Mesmo `event_id`.
- [ ] Mesmo shipment.
- [ ] Diferentes ordens de execução.
- [ ] Comportamento da constraint do banco.

### Resultado esperado

Não assumir o resultado antes da execução.

Documentar o comportamento real encontrado.

---

## Tarefa 2.6.2 — Criar ADR sobre concorrência e idempotência

Criar um ADR com:

1. Contexto.
2. Problema reproduzido.
3. Estratégia atual.
4. Limitações.
5. Alternativas.
6. Decisão futura.
7. Trade-offs.

### Alternativas a analisar

- Constraint + tratamento de conflito.
- Tabela dedicada de eventos processados.
- Inbox Pattern.
- Lock pessimista.
- Lock otimista.
- Serialização por shipment.

Não implementar todas.

---

## Definition of Done da Fase 2.6

- [ ] Race condition ou comportamento concorrente reproduzido.
- [ ] Resultado documentado.
- [ ] ADR criado.
- [ ] Estratégia para Fase 3 escolhida.

---

# FASE 3 — Reliable Event Ingestion

## Objetivo

Fortalecer o recebimento de eventos antes de introduzir processamento assíncrono.

A fase possui dois problemas principais:

1. Idempotência concorrente.
2. Eventos fora de ordem.

---

# FASE 3A — Idempotência concorrente

## Objetivo

Garantir que eventos duplicados não produzam efeitos de domínio duplicados mesmo sob concorrência.

## Tarefa 3A.1 — Escolher estratégia

A escolha deve ser baseada nos resultados da Fase 2.6.

### Possível arquitetura

```text
Receive Event
      ↓
Claim Event Identity
      │
      ├── Already claimed
      │        ↓
      │     Duplicate
      │
      └── New event
               ↓
          Process domain
```

### Possível evolução

Criar uma tabela:

```text
processed_events
├── event_id
├── shipment_id
├── status
├── received_at
└── processed_at
```

Estados possíveis:

```text
RECEIVED
PROCESSING
PROCESSED
FAILED
```

### Regra

Não criar essa tabela se a solução mais simples atender corretamente aos requisitos da fase.

---

## Tarefa 3A.2 — Implementar e testar a estratégia

Criar testes para:

- [ ] Evento duplicado sequencial.
- [ ] Evento duplicado concorrente.
- [ ] Reenvio após falha.
- [ ] Evento já processado.
- [ ] Integridade do estado da shipment.

### Critério principal

Dois processamentos do mesmo evento não podem produzir duas mudanças de domínio.

---

# FASE 3B — Eventos fora de ordem

## Objetivo

Definir explicitamente uma política de negócio e persistência.

---

## Tarefa 3B.1 — Classificar eventos

Separar conceitualmente:

### Eventos de estado

```text
PICKUP_SCHEDULED
PICKUP_COMPLETED
SHIPMENT_DEPARTED
DELAY_DETECTED
DELIVERED
```

### Eventos de localização

```text
LOCATION_UPDATED
```

Essa classificação pode orientar políticas diferentes.

---

## Tarefa 3B.2 — Implementar política para localização atrasada

### Cenário

```text
10:00 LOCATION_UPDATED
10:05 LOCATION_UPDATED
09:55 LOCATION_UPDATED arrives late
```

### Comportamento recomendado

```text
Persist historical event
        ↓
Compare occurred_at
        ↓
Older than last_location_at?
        │
       YES
        ↓
Do not overwrite current location
```

### Garantias

O evento continua disponível no histórico.

A localização atual não retrocede no tempo.

---

## Tarefa 3B.3 — Definir política para lifecycle atrasado

### Cenário

```text
Occurred:
PICKUP_COMPLETED
SHIPMENT_DEPARTED

Received:
SHIPMENT_DEPARTED
PICKUP_COMPLETED
```

### Alternativas

#### A — Rejeitar

Simples, porém pode perder informação operacional.

#### B — Persistir como pendente

Requer processamento posterior.

#### C — Reprocessar histórico

Maior consistência temporal, porém maior complexidade.

### Implementação recomendada para a primeira versão

Definir uma política explícita e conservadora.

Não implementar replay completo sem necessidade demonstrada.

Criar ADR documentando:

- política escolhida;
- eventos afetados;
- comportamento de eventos atrasados;
- limitações;
- evolução futura.

---

## Definition of Done da Fase 3

- [ ] Idempotência concorrente validada.
- [ ] Política de eventos fora de ordem implementada.
- [ ] Localização atual não retrocede temporalmente.
- [ ] Eventos históricos continuam rastreáveis.
- [ ] ADRs atualizados.
- [ ] Testes de cenários críticos implementados.

---

# FASE 4 — Asynchronous Processing

## Objetivo

Introduzir processamento assíncrono usando RabbitMQ.

## Princípio

Workers são adapters de infraestrutura.

Workers não devem conter regras de negócio.

---

## Tarefa 4.1 — Adicionar RabbitMQ ao ambiente

Atualizar o ambiente local.

Validar:

- [ ] Broker disponível.
- [ ] API consegue conectar.
- [ ] Worker consegue conectar.
- [ ] Configuração via ambiente.

Não adicionar Redis nesta fase.

---

## Tarefa 4.2 — Criar contrato de mensagem

Definir um formato explícito.

Exemplo conceitual:

```json
{
  "message_id": "...",
  "event_id": "...",
  "event_type": "...",
  "shipment_id": "...",
  "occurred_at": "...",
  "payload": {}
}
```

### Requisitos

- serialização determinística;
- versão do contrato, se necessário;
- validação ao consumir;
- nenhuma dependência direta do ORM.

---

## Tarefa 4.3 — Criar publisher

Responsabilidade:

```text
Application / Adapter
       ↓
Serialize message
       ↓
Publish to RabbitMQ
```

O publisher não implementa regra de negócio.

---

## Tarefa 4.4 — Criar consumer

Estrutura:

```text
RabbitMQ
    ↓
Consumer
    ↓
Deserialize
    ↓
Validate message
    ↓
Application Use Case
    ↓
ACK / Reject
```

### Regra

Reutilizar os casos de uso existentes sempre que possível.

Não duplicar a lógica do domínio dentro do worker.

---

## Tarefa 4.5 — Definir novo fluxo de POST /events

Decidir explicitamente se:

### Opção inicial

```text
POST /events
      ↓
Process synchronously
      ↓
Persist
```

deve evoluir diretamente para:

```text
POST /events
      ↓
Publish
      ↓
202 Accepted
      ↓
Worker processes later
```

Documentar a decisão e os trade-offs.

---

## Definition of Done da Fase 4

- [ ] RabbitMQ integrado.
- [ ] Producer funcional.
- [ ] Consumer funcional.
- [ ] Worker reutiliza Application Layer.
- [ ] Mensagens são processadas de ponta a ponta.
- [ ] Testes de integração existem.
- [ ] Decisão do fluxo HTTP documentada.

---

# FASE 5 — Failure Recovery

## Objetivo

Criar comportamento previsível quando o processamento falha.

---

## Tarefa 5.1 — Classificar falhas

Criar categorias conceituais.

### Retryable

Exemplos:

- indisponibilidade temporária de banco;
- timeout;
- falha transitória de infraestrutura.

### Non-retryable

Exemplos:

- payload inválido;
- transição inválida;
- shipment inexistente.

### Regra

A classificação deve ser centralizada e testável.

---

## Tarefa 5.2 — Implementar Retry Policy

Começar simples.

```text
Attempt 1
    ↓
Attempt 2
    ↓
Attempt 3
```

Depois avaliar:

```text
Exponential Backoff
```

### Testar

- [ ] Falha temporária.
- [ ] Sucesso após retry.
- [ ] Limite máximo.
- [ ] Falha não retryable.

---

## Tarefa 5.3 — Implementar Dead Letter Queue

Fluxo:

```text
Main Queue
    ↓
Processing Failure
    ↓
Retry
    ↓
Retry
    ↓
Retry
    ↓
DLQ
```

### Dados importantes

Preservar:

- mensagem original;
- motivo da falha;
- número de tentativas;
- timestamps relevantes.

### Não implementar nesta fase

Interface administrativa completa.

---

## Definition of Done da Fase 5

- [ ] Falhas transitórias recebem retry.
- [ ] Falhas permanentes não entram em loop.
- [ ] Mensagens esgotadas vão para DLQ.
- [ ] Informações suficientes são preservadas para investigação.
- [ ] Cenários críticos possuem testes.

---

# FASE 6 — Transactional Outbox

## Objetivo

Resolver a inconsistência entre persistência em PostgreSQL e publicação em RabbitMQ.

---

## Tarefa 6.1 — Criar ADR antes da implementação

Documentar:

```text
Database update succeeds
        +
Message publish fails
```

Explicar por que uma transação única entre PostgreSQL e RabbitMQ não é assumida.

---

## Tarefa 6.2 — Criar modelo Outbox

Possível estrutura:

```text
outbox_events
├── id
├── event_type
├── aggregate_id
├── payload
├── created_at
├── published_at
└── attempts
```

A estrutura final deve refletir as necessidades reais do projeto.

---

## Tarefa 6.3 — Persistir estado e Outbox na mesma transação

Fluxo:

```text
Transaction
│
├── Domain state update
│
└── Outbox event creation
        ↓
COMMIT
```

### Garantia desejada

Se a mudança de domínio existir, a intenção de publicação também existe.

---

## Tarefa 6.4 — Criar Outbox Worker

Responsabilidade:

```text
Find unpublished events
        ↓
Publish
        ↓
Mark published
```

---

## Tarefa 6.5 — Testar duplicidade de publicação

Cenário:

```text
Publish succeeds
      ↓
Worker crashes
      ↓
published_at not updated
      ↓
Worker retries
      ↓
Publish again
```

### Conclusão arquitetural

Outbox não garante exactly-once.

A arquitetura depende de:

```text
At-least-once publishing
        +
Idempotent Consumers
```

---

## Definition of Done da Fase 6

- [ ] Outbox persistida transacionalmente.
- [ ] Worker publica eventos pendentes.
- [ ] Falhas de publicação são recuperáveis.
- [ ] Publicação duplicada é considerada e testada.
- [ ] ADR documentado.

---

# FASE 7 — Observability & Production Readiness

## Objetivo

Tornar o comportamento do sistema observável.

---

## Tarefa 7.1 — Structured Logging

Campos recomendados:

```text
event_id
shipment_id
event_type
source
correlation_id
processing_status
```

### Objetivo

Permitir rastrear uma operação sem depender de logs textuais soltos.

---

## Tarefa 7.2 — Correlation ID

Fluxo:

```text
HTTP Request
      ↓
correlation_id
      │
      ├── API logs
      ├── Message metadata
      ├── Worker logs
      └── Processing logs
```

### Regra

O identificador deve acompanhar o fluxo de uma operação.

---

## Tarefa 7.3 — Métricas

Implementar progressivamente:

```text
events_received_total
events_processed_total
events_failed_total
events_duplicate_total
event_processing_duration_seconds
events_in_dlq_total
outbox_pending_events
```

Adicionar métricas somente quando o componente correspondente existir.

---

## Tarefa 7.4 — Prometheus

Criar endpoint ou mecanismo apropriado de exposição.

Validar:

- [ ] Métricas coletadas.
- [ ] Counters corretos.
- [ ] Erros não distorcem métricas.
- [ ] Métricas não expõem dados sensíveis.

---

## Tarefa 7.5 — Grafana

Dashboard mínimo.

### Event Processing

- eventos recebidos;
- eventos processados;
- eventos falhos.

### Queue Health

- tamanho das filas;
- taxa de consumo;
- erros.

### Reliability

- retries;
- mensagens em DLQ;
- eventos pendentes no Outbox.

---

## Definition of Done da Fase 7

- [ ] Logs estruturados.
- [ ] Correlation ID.
- [ ] Métricas relevantes.
- [ ] Prometheus funcional.
- [ ] Dashboard básico.
- [ ] Fluxos críticos investigáveis.

---

# 4. ADRs planejados

Criar apenas quando a decisão estiver madura.

```text
ADR-001 — Estratégia de idempotência concorrente
ADR-002 — Política para eventos fora de ordem
ADR-003 — Por que RabbitMQ?
ADR-004 — Modelo de retries e classificação de falhas
ADR-005 — Estratégia de Dead Letter Queue
ADR-006 — Transactional Outbox
ADR-007 — Estratégia de observabilidade
```

## Template

```markdown
# ADR-XXX — Título

## Status

Proposed | Accepted | Superseded

## Context

Qual problema existe?

## Decision

Qual decisão foi tomada?

## Alternatives Considered

Quais alternativas foram avaliadas?

## Trade-offs

Quais são os custos e limitações?

## Consequences

O que muda após essa decisão?
```

---

# 5. Ordem de execução recomendada

## Próximo passo imediato

```text
FASE 2.5
```

### Sequência exata

1. Criar infraestrutura de testes de integração.
2. Testar repositories contra PostgreSQL real.
3. Testar constraints.
4. Testar rollback.
5. Testar fluxo HTTP completo.

## Depois

```text
FASE 2.6
```

Reproduzir problemas concorrentes.

## Depois

```text
FASE 3
```

Resolver idempotência e definir eventos fora de ordem.

Somente então:

```text
FASE 4
```

Adicionar RabbitMQ.

---

# 6. Checklist global de qualidade

Antes de considerar qualquer fase concluída:

- [ ] O comportamento foi testado no nível correto?
- [ ] Existem testes de falha?
- [ ] Existe alguma race condition conhecida?
- [ ] Uma responsabilidade foi parar na camada errada?
- [ ] A solução é proporcional ao problema?
- [ ] Existe tecnologia adicionada sem necessidade?
- [ ] Os trade-offs foram documentados?
- [ ] A suíte anterior continua passando?
- [ ] A documentação do estado atual foi atualizada?

---

# 7. Instrução para a IA ao executar este plano

Ao receber uma solicitação para implementar uma tarefa deste documento:

1. Identifique a fase e a tarefa.
2. Inspecione o código atual antes de propor mudanças.
3. Informe resumidamente o que já existe relacionado à tarefa.
4. Liste os arquivos que provavelmente serão alterados.
5. Implemente a menor mudança necessária.
6. Não antecipar tarefas de fases futuras.
7. Execute ou valide os testes relevantes quando possível.
8. Explique decisões arquiteturais apenas quando forem relevantes.
9. Atualize documentação ou ADR quando a tarefa exigir uma decisão arquitetural.
10. Ao terminar, informe:
   - o que foi implementado;
   - o que foi validado;
   - limitações conhecidas;
   - qual é o próximo passo dentro da fase atual.

## Regra final

**O projeto deve evoluir como consequência de problemas reais identificados durante sua implementação, e não como uma coleção de tecnologias adicionadas artificialmente.**
