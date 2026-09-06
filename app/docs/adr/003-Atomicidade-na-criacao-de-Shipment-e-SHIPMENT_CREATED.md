# ADR-003 — Atomicidade na criacao de Shipment e SHIPMENT_CREATED

- Status: Accepted
- Date: 2026-09-06
- Relacionado: ADR-002 - Evolucao da Fase 2: API e Persistencia

## 1. Contexto

A criacao de uma `Shipment` foi inicialmente tratada como operacao de dominio e persistencia separada da registracao do evento `SHIPMENT_CREATED`.

Esse padrao deixava o historico do lifecycle inconsistente em pontos importantes:

- a `Shipment` era criada e persistida;
- o evento de criacao nao era necessariamente registrado no mesmo fluxo;
- a representacao do fato de que a shipment foi criada dependia de outro passo ou de uma segunda entrada HTTP;
- o ciclo de vida da entidade e do historico de eventos nao eram necessariamente vistos como uma unica transacao de negocio.

A API possui um contrato claro para criacao de shipments em `POST /shipments`, mas a semantica correta do dominio exige que a criacao da entidade e a criacao do evento `SHIPMENT_CREATED` sejam tratadas como um unico acontecimento de negocio.

A arquitetura atual tambem define uma fronteira transacional por request, usando uma unica `Session` SQLAlchemy via `get_db()`. Dessa forma, a persistencia de `Shipment` e `ShipmentEvent` pode ocorrer no mesmo ciclo transacional, desde que o caso de uso mantenha essa coesao e o repositorio nao finalize a transacao de forma isolada.

## 2. Problema

Precisamos decidir como documentar e implementar a semantica de criacao correta para uma shipment.

A decisao deve responder:

- o evento `SHIPMENT_CREATED` deve ser persistido no mesmo fluxo da criacao da shipment?
- a API deve possuir um contrato alternativo de criacao via `POST /events`?
- o `ShipmentEventHandler` deve processar `SHIPMENT_CREATED` como transicao de estado?
- a criacao da entity e do evento podem ocorrer como uma unica operacao atomica?

O objetivo e evitar estados inconsistentes entre o estado atual da shipment e o historico de eventos, sem mover regras de negocio para controllers ou repositories.

## 3. Decisao

A operacao de criacao de `Shipment` e registrada como uma unica operacao de negocio dentro do use case `CreateShipment`.

A API possui um unico contrato para criacao de shipment:

`POST /shipments`

Esse endpoint nao deve existir em uma segunda forma por `POST /events`.

A criacao de uma shipment agora implica conceitualmente:

```text
CreateShipment
    |
    +-- cria Shipment
    |
    +-- cria ShipmentEvent(SHIPMENT_CREATED)
    |
    +-- persiste ambos na mesma transacao
    |
    +-- commit da request
```

A entidade nasce no estado `CREATED` via `Shipment.create()`, e o evento `SHIPMENT_CREATED` registra o fato historico de que essa criacao ocorreu.

Esse evento nao entra no `ShipmentEventHandler` como transicao de estado normal.

A regra atual e:

- `Shipment.create()` define `status = CREATED`;
- `ShipmentEvent(event_type = SHIPMENT_CREATED)` registra o acontecimento;
- o fluxo de processamento do `ShipmentEventHandler` continua sendo usado para eventos de lifecycle posteriores;
- `SHIPMENT_CREATED` nao representa `CREATED -> CREATED` em uma state machine.

## 4. Semantica transacional atual

A transacao atual e definida pela dependencia `get_db()`.

Essa dependencia:

- cria a `Session` do SQLAlchemy;
- entrega a mesma sessao aos repositories da request;
- executa `commit()` quando a operacao termina com sucesso;
- executa `rollback()` quando ocorre uma excecao;
- fecha a sessao ao final.

Assim, `CreateShipment` usa a mesma Session para:

```text
ShipmentRepository
        |
        +---- mesma Session SQLAlchemy ----+
                                           |
ShipmentEventRepository                   |
        |                                  |
        +----------------------------------+
```

A operacao de criacao fica dentro da mesma transacao da request, e os repositories nao assumem a responsabilidade de finalizar a transacao.

### Comportamento esperado

Sucesso:

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

Falha:

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

Isso preserva a integridade entre estado atual e historico de eventos.

## 5. Timestamps

A arquitetura continua utilizando a distinccao entre:

- `occurred_at`: momento em que o fato ocorreu no dominio;
- `received_at`: momento em que o sistema recebeu/registrou o evento.

No caso do `SHIPMENT_CREATED`:

```text
Shipment.created_at == ShipmentEvent(SHIPMENT_CREATED).occurred_at
```

Esse mesmo instante de criacao da entity e usada como ocorrencia do evento de criacao.

A diferenca entre `occurred_at` e `received_at` permanece relevante para evolucoes futuras de eventos fora de ordem e reprocessamento, mas nao vira uma regra de negocio implementada neste estagio.

## 6. Responsabilidades por camada

### API/controller

A camada HTTP continua responsavel por:

- receber a request;
- validar o contrato HTTP via schemas;
- converter o DTO em input da application;
- chamar o use case;
- converter/retornar a resposta.

A controller nao cria o evento `SHIPMENT_CREATED` diretamente e nao implementa regras de negocio.

### Application / Use Case

`CreateShipment` e o ponto de negocio responsavel por:

1. criar a entidade `Shipment` via dominio;
2. criar o evento `SHIPMENT_CREATED`;
3. persistir a shipment e o evento na mesma transacao;
4. retornar a entidade criada.

### Domain

O dominio continua responsavel por:

- estado inicial da `Shipment`;
- validacoes de estado;
- transicoes via state machine;
- atualizacao de localizacao;
- invariantes de negocio.

### Infrastructure

Repositories continuam responsaveis apenas pela persistencia. Eles nao devem assumir a finalizacao da transacao e nem implementar logica de negocio em cima de controladores ou eventos.

## 7. Consequencias positivas

- historico completo a partir da criacao da shipment;
- ausencia de necessidade de segunda request para registrar o evento de criacao;
- `Shipment` e `SHIPMENT_CREATED` permanecem consistentes na mesma transacao;
- rollback impede persistencia parcial;
- controller permanece sem regra de negocio;
- melhoria do alinhamento entre dominio, aplicacao e persistencia.

## 8. Trade-offs e consequencias

- `CreateShipment` passa a depender de `ShipmentEventRepository` alem do `ShipmentRepository`;
- a criacao da shipment implica dois writes no mesmo fluxo transacional;
- a fronteira transacional precisa ser preservada por `get_db()`;
- evolucoes futuras podem exigir um mecanismo adicional de publicacao assincrona, mas isso nao faz parte desta implementacao.

## 9. Alternativas consideradas

### 1. Exigir `POST /events` para criar o evento de criacao

Foi rejeitada porque torna a criacao da shipment incompleta por um problema de modelagem e de historico. O fato de a shipment ter sido criada e um unico acontecimento de negocio, e nao um evento separado que dependeria de outra request.

### 2. Gerar o evento no controller

Foi rejeitada porque move responsabilidade de dominio e integridade para a camada HTTP, quebrando a separacao de responsabilidades e a regra de negocio da aplicacao.

### 3. Criar um event bus na mesma etapa

Foi rejeitada porque ainda nao existe infraestrutura e nem necessidade imediata de publicacao assincrona. A implementacao atual precisa manter a operacao atomica local e consistente antes de evoluir para fluxo de eventos distribuido.

### 4. Usar Outbox neste momento

Foi rejeitada porque Outbox nao esta implementado e nao e necessario para a transacao local atual. A criacao de `Shipment` e `SHIPMENT_CREATED` ja pode ser persistida dentro da mesma transacao SQLAlchemy, sem introduzir infraestrutura adicional.

## 10. Decisao final

A criacao de `Shipment` e a criacao do evento `SHIPMENT_CREATED` fazem parte da mesma operacao de negocio e da mesma transacao.

A API e o contrato publico continuam sendo orientados por `POST /shipments`, enquanto `POST /events` continua sendo usado apenas para eventos posteriores do lifecycle da shipment.

A implementacao atual e coerente com a separacao atual de responsabilidades e com o objetivo de manter o historico e o estado atual consistentes desde a criacao da entidade.
