# ADR-001 — Core Domain e State Machine da Shipment

- Status: Accepted
- Date: 2026-09-05
- Decision: Implementar o Core Domain como um componente independente de infraestrutura, utilizando uma entidade Shipment, uma entidade imutável ShipmentEvent e uma State Machine explícita para controlar as transições de estado.

## 1. Contexto

A Freight Event Intelligence Platform precisa manter uma visão consistente do estado atual de uma shipment a partir de eventos provenientes de diferentes fontes.

Esses eventos podem:

- chegar duplicados;
- chegar fora de ordem;
- possuir diferentes formatos;
- representar mudanças de estado;
- apenas atualizar informações da shipment;
- ser processados de forma assíncrona no futuro.

A primeira fase do projeto tem como objetivo construir o domínio antes de introduzir infraestrutura como PostgreSQL, RabbitMQ, Redis ou FastAPI.

A decisão desta ADR é, portanto, estabelecer as principais abstrações do domínio e garantir que as regras fundamentais possam ser testadas independentemente de infraestrutura.

## 2. Problema

Precisamos definir:

- Como representar uma Shipment.
- Como representar eventos relacionados a uma shipment.
- Como controlar as transições de estado.
- Onde as regras de negócio devem estar.
- Como impedir que componentes externos alterem o estado da shipment arbitrariamente.
- Como diferenciar o momento em que um evento ocorreu do momento em que foi recebido.
- Como testar essas regras sem depender de banco de dados ou message broker.

Uma preocupação importante é evitar que regras de negócio sejam implementadas prematuramente em repositories, consumers ou controllers.

## 3. Decisão

O Core Domain será implementado como um componente independente de infraestrutura.

A primeira implementação possui os seguintes elementos:

```text
app/
└── domain/
    └── shipment/
        ├── entities.py
        ├── events.py
        ├── state_machine.py
        └── exceptions.py
```

Os testes ficam separados:

```text
tests/
└── domain/
    └── shipment/
        ├── test_entities.py
        ├── test_events.py
        └── test_state_machine.py
```

A responsabilidade de cada componente é:

- Shipment
  - Representa a entidade e seu estado atual.

- ShipmentEvent
  - Representa um evento de negócio recebido.

- ShipmentStateMachine
  - Define quais transições são permitidas.

- Domain Exceptions
  - Representam violações das regras do domínio.

## 4. Shipment

A Shipment é a principal entidade do domínio.

Seu modelo inicial contém:

- id
- reference_number
- origin
- destination
- carrier
- status
- created_at
- updated_at

A criação da shipment inicia seu estado em:

`CREATED`

A criação é realizada através de um método de fábrica:

`Shipment.create(...)`

Isso evita que o código externo precise conhecer detalhes sobre como uma shipment deve ser inicializada.

A alteração de estado ocorre através de:

`shipment.apply_event(event)`

e não através de atribuições arbitrárias como:

`shipment.status = ShipmentStatus.DELIVERED`

Essa decisão concentra a aplicação das regras de negócio dentro do domínio.

## 5. ShipmentEvent

Os eventos são representados por ShipmentEvent.

A estrutura inicial é:

- event_id
- shipment_id
- event_type
- source
- occurred_at
- received_at
- payload

O evento é imutável após sua criação.

A decisão é utilizar uma estrutura equivalente a:

```python
@dataclass(frozen=True, slots=True)
class ShipmentEvent:
    ...
```

A imutabilidade representa a natureza histórica do evento.

Depois que um evento aconteceu e foi registrado, não devemos modificar seu conteúdo para adaptar o histórico ao estado atual.

## 6. occurred_at versus received_at

O domínio mantém explicitamente dois timestamps:

- occurred_at

  Representa quando o evento realmente aconteceu.

- received_at

  Representa quando o sistema recebeu o evento.

Essa distinção é necessária porque a ordem de recebimento não representa necessariamente a ordem em que os acontecimentos ocorreram.

Exemplo:

- Evento A
  - occurred_at = 10:00

- Evento B
  - occurred_at = 10:05

Pode acontecer de o sistema receber:

- Evento B
  - received_at = 10:06

- Evento A
  - received_at = 10:07

Portanto, a arquitetura não deve assumir:

`received_at order == occurred_at order`

## 7. State Machine

O ciclo de vida inicial da shipment é representado por:

- CREATED
- SCHEDULED
- PICKED_UP
- IN_TRANSIT
- DELAYED
- DELIVERED

As transições atualmente permitidas são:

```text
CREATED
    └── PICKUP_SCHEDULED → SCHEDULED

SCHEDULED
    └── PICKUP_COMPLETED → PICKED_UP

PICKED_UP
    └── LOCATION_UPDATED → IN_TRANSIT

IN_TRANSIT
    ├── DELAY_DETECTED → DELAYED
    └── DELIVERED → DELIVERED

DELAYED
    ├── LOCATION_UPDATED → IN_TRANSIT
    └── DELIVERED → DELIVERED
```

A tabela de transições é explicitamente definida dentro da ShipmentStateMachine.

Isso foi escolhido em vez de espalhar regras através de vários if/elif dentro da entidade.

A vantagem é que o conjunto de transições permitidas fica:

- explícito;
- centralizado;
- fácil de revisar;
- fácil de testar;
- independente da infraestrutura.

## 8. Transições inválidas

Uma transição não definida pela State Machine deve gerar uma exceção de domínio:

`InvalidStateTransition`

Por exemplo:

`CREATED → DELIVERED`

é rejeitado.

Isso é importante porque uma transição inválida não deve ser tratada como um simples erro técnico.

Ela representa uma violação de uma regra do domínio.

O comportamento esperado é:

```text
Invalid event
      ↓
Domain rejects event
      ↓
Shipment state remains unchanged
```

## 9. Responsabilidade da State Machine

A State Machine possui uma responsabilidade deliberadamente pequena:

Determinar qual estado pode suceder o estado atual para um determinado tipo de evento.

Ela não é responsável por:

- persistir shipments;
- publicar mensagens;
- acessar PostgreSQL;
- acessar RabbitMQ;
- fazer retry;
- detectar duplicidade;
- controlar transações;
- decidir como eventos atrasados serão reprocessados.

Essas responsabilidades pertencem a outras camadas que serão introduzidas posteriormente.

## 10. Testes

A Fase 1 possui testes unitários para proteger as regras fundamentais.

Os testes cobrem:

### Transições válidas

Exemplos:

- CREATED → SCHEDULED
- SCHEDULED → PICKED_UP
- PICKED_UP → IN_TRANSIT
- IN_TRANSIT → DELAYED
- IN_TRANSIT → DELIVERED
- DELAYED → IN_TRANSIT
- DELAYED → DELIVERED

### Transições inválidas

Exemplos:

- CREATED → DELIVERED
- CREATED → DELAYED
- SCHEDULED → DELIVERED
- PICKED_UP → DELIVERED
- DELIVERED → IN_TRANSIT
- DELIVERED → DELIVERED

### Integridade da entidade

Também são testados:

- estado inicial da shipment;
- aplicação de eventos;
- atualização de updated_at;
- rejeição de eventos pertencentes a outra shipment;
- preservação do estado quando ocorre uma transição inválida.

### Imutabilidade dos eventos

ShipmentEvent também possui teste garantindo que seus atributos não possam ser alterados depois de criado.

## 11. SHIPMENT_CREATED

O evento:

`SHIPMENT_CREATED`

existe no catálogo de eventos, mas não é tratado como uma transição da State Machine.

A criação da entidade já estabelece:

```text
Shipment.create()
        ↓
status = CREATED
```

Portanto, neste momento, não fazemos:

```text
SHIPMENT_CREATED
        ↓
CREATED
```

A decisão evita uma transição redundante.

Entretanto, a relação entre criação da entidade e evento de domínio ainda precisa ser formalizada antes da implementação da persistência.

## 12. Eventos de mudança de estado versus eventos de informação

A implementação atual utiliza eventos como entrada da State Machine.

Entretanto, nem todo evento necessariamente representa uma mudança de estado.

Por exemplo:

`LOCATION_UPDATED`

pode ocorrer diversas vezes durante uma viagem:

- LOCATION_UPDATED
- LOCATION_UPDATED
- LOCATION_UPDATED
- LOCATION_UPDATED
- ...

Depois que a shipment está em:

`IN_TRANSIT`

esses eventos provavelmente devem atualizar informações de localização sem necessariamente representar:

`IN_TRANSIT → IN_TRANSIT`

A implementação atual ainda simplifica esse comportamento.

Essa questão será resolvida antes da Fase 2.

## 13. Eventos fora de ordem

A implementação atual não considera resolvida a questão de eventos fora de ordem.

Esse comportamento foi deliberadamente deixado como pendência.

Exemplo:

```text
10:00 PICKUP_COMPLETED
10:05 LOCATION_UPDATED
10:10 DELIVERED
```

pode ser recebido como:

```text
DELIVERED
PICKUP_COMPLETED
LOCATION_UPDATED
```

Se DELIVERED for aplicado enquanto a shipment estiver em CREATED, a State Machine corretamente rejeitará:

`CREATED → DELIVERED`

Porém, ainda precisamos decidir se esse evento é:

- inválido

ou:

- válido, porém recebido prematuramente

Essa decisão não deve ser simplesmente colocada dentro da entidade Shipment.

A política de processamento de eventos atrasados deve pertencer à camada apropriada de aplicação/processamento.

## 14. Pendências antes da Fase 2

A Fase 2 não deve começar imediatamente.

Antes de introduzir PostgreSQL, repositories e FastAPI, as seguintes questões devem ser resolvidas.

### 14.1 Definir a semântica de SHIPMENT_CREATED

Precisamos decidir se:

`SHIPMENT_CREATED`

será:

- apenas um evento externo recebido;
- um evento de domínio gerado pela criação da shipment;
- ambos, com distinção entre evento externo e evento interno.

A decisão deve considerar também auditoria e o futuro Transactional Outbox.

### 14.2 Separar eventos de transição de estado de eventos informativos

Precisamos distinguir:

- State-changing events

de:

- Informational events

Por exemplo:

- PICKUP_COMPLETED
- DELIVERED
- DELAY_DETECTED

provavelmente representam mudanças de estado.

Enquanto:

`LOCATION_UPDATED`

pode representar uma atualização de dados da shipment sem necessariamente causar uma nova transição.

A modelagem deve evitar que a State Machine seja utilizada para representar todo tipo de alteração existente no domínio.

### 14.3 Definir política para eventos fora de ordem

Precisamos estabelecer explicitamente:

- como detectar eventos atrasados;
- quando um evento deve ser aceito;
- quando deve ser rejeitado;
- quando deve ser armazenado para processamento posterior;
- se será necessário reprocessamento;
- qual papel occurred_at terá na decisão;
- como lidar com eventos que chegam depois de DELIVERED.

A decisão deve ser documentada em uma ADR própria.

Sugestão:

`ADR-004 — Handling Out-of-Order Events`

### 14.4 Definir a semântica de updated_at

Atualmente:

`updated_at = event.occurred_at`

Isso precisa ser validado.

Eventos atrasados podem criar situações como:

`updated_at = 10:10`

seguido de um evento que ocorreu às:

`10:05`

Não devemos permitir que uma atualização tardia faça o relógio lógico da entidade retroceder sem uma decisão explícita.

Antes da persistência, precisamos definir se:

`updated_at`

representará:

- último evento processado;
- último evento ocorrido;
- última alteração material da entidade;
- tempo da última atualização persistida.

### 14.5 Definir invariantes da Shipment

Antes de persistir a entidade, devemos documentar invariantes importantes.

Exemplos:

- Shipment ID não pode mudar.
- Shipment criada sempre inicia em CREATED.
- Uma shipment não pode receber evento de outra shipment.
- Shipment DELIVERED não pode voltar para um estado operacional anterior.
- Transições inválidas não alteram o estado.

Também devemos decidir se existem invariantes adicionais para:

- reference_number;
- origin;
- destination;
- carrier;
- timestamps.

### 14.6 Definir identidade do evento

O event_id foi definido como identificador único do evento.

Antes da Fase 2 precisamos confirmar que essa será a identidade utilizada para idempotência.

A decisão deverá responder:

- O event_id é globalmente único?

ou:

- A unicidade é apenas dentro de uma determinada source?

Isso terá impacto direto na futura tabela:

`processed_events`

e nas constraints do PostgreSQL.

### 14.7 Definir comportamento para eventos duplicados

A entidade atualmente não conhece idempotência.

Isso é intencional.

A decisão futura deverá definir onde ocorre o controle:

```text
Event Consumer
       ↓
Idempotency Check
       ↓
Shipment.apply_event()
```

e como a garantia será reforçada pelo banco de dados.

A implementação deverá considerar:

`At-least-once delivery`

como comportamento normal do sistema.

## 15. O que não faz parte desta ADR

Esta ADR não define:

- PostgreSQL;
- SQLAlchemy;
- FastAPI;
- RabbitMQ;
- Redis;
- Outbox Pattern;
- retries;
- Dead Letter Queue;
- Prometheus;
- Grafana;
- microservices.

Essas decisões serão tomadas quando forem necessárias.

O objetivo desta ADR é exclusivamente estabelecer uma fundação de domínio independente de infraestrutura.

## 16. Consequências positivas

Esta decisão proporciona:

- Independência de infraestrutura
  - O domínio pode ser executado e testado sem:

```text
PostgreSQL
RabbitMQ
Redis
HTTP
```

- Regras explícitas
  - As transições permitidas são centralizadas na State Machine.

- Testabilidade
  - As regras podem ser testadas rapidamente através de unit tests.

- Menor acoplamento
  - A entidade Shipment não conhece repositories, brokers ou frameworks.

- Evolução progressiva
  - A infraestrutura poderá ser adicionada posteriormente sem precisar definir as regras de negócio ao mesmo tempo.

## 17. Consequências negativas

Também existem custos.

- A modelagem ainda não representa todo o domínio
  - Eventos fora de ordem e eventos informativos ainda não estão completamente definidos.

- Pode haver refatoração antes da persistência
  - As decisões pendentes podem alterar algumas interfaces atuais.

Isso é aceitável porque ainda estamos na fase de construção do domínio.

- A State Machine pode evoluir
  - À medida que novas regras forem descobertas, a tabela de transições poderá ficar mais sofisticada.

Isso não deve ser considerado um problema enquanto as regras permanecerem explícitas e testáveis.

## 18. Critério para considerar a Fase 1 concluída

A Fase 1 será considerada concluída quando:

- Shipment estiver implementada.
- ShipmentEvent estiver implementada.
- Estados da shipment estiverem definidos.
- State Machine estiver implementada.
- Transições válidas estiverem testadas.
- Transições inválidas estiverem testadas.
- Eventos estiverem imutáveis.
- A entidade rejeitar eventos de outra shipment.
- Semântica de SHIPMENT_CREATED estiver definida.
- Eventos de transição e eventos informativos estiverem separados.
- Estratégia para eventos fora de ordem estiver definida.
- Semântica de updated_at estiver definida.
- Invariantes da Shipment estiverem documentados.
- Identidade global do evento estiver definida.
- Estratégia de idempotência estiver definida.

Somente após esses pontos serem resolvidos deveremos iniciar a implementação da persistência da Fase 2.

## 19. Próximas ADRs esperadas

As decisões pendentes provavelmente resultarão em ADRs específicas:

- ADR-002 — Event Idempotency
- ADR-003 — Event Identity and Deduplication
- ADR-004 — Handling Out-of-Order Events
- ADR-005 — PostgreSQL as Primary Persistence
- ADR-006 — RabbitMQ as Message Broker

A numeração pode ser ajustada conforme a ordem real em que as decisões forem tomadas.

## 20. Resumo da decisão

O projeto começa pelo domínio, não pela infraestrutura.

A Shipment controla seu próprio comportamento, ShipmentEvent representa fatos imutáveis e a ShipmentStateMachine define explicitamente as transições permitidas.

A implementação atual estabelece uma fundação pequena e testável, mas deliberadamente deixa algumas questões avançadas em aberto.

Antes de adicionar PostgreSQL e APIs, precisamos fechar principalmente:

- Eventos de estado
- Eventos informativos
- Eventos fora de ordem
- Identidade/idempotência
- Semântica dos timestamps
