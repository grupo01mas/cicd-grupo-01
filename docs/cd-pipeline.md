# Pipeline de Deployment (CD)

Referência das pipelines de **deploy**: levam uma imagem publicada no Docker Hub
para um cluster `kind` que roda numa EC2, via SSH.

> Este doc explica **as estratégias e as decisões**. Os esqueletos comentados, com
> os TODOs na ordem de construção, estão em `.github/workflows/cd*.yml.example`.

---

## As duas estratégias

| Estratégia | Workflow(s) | Namespace | Host (ingress) |
|---|---|---|---|
| **Rolling Update** | `cd.yml` | `todolist` | `todolist.local` |
| **Blue/Green** | `cd-blue-green.yml` (deploy) + `cd-blue-green-switch.yml` (switch) | `todolist-bg` | `todolist-bg.local` (produção), `blue.`/`green.todolist-bg.local` (slots) |

As duas **coexistem** no mesmo cluster, em namespaces e hosts distintos. Dá para
demonstrar uma e depois a outra sem conflito nem teardown no meio.

Todas as apps entram pelo **ingress-nginx** na porta 80 do nó, com roteamento por
host. Os Services são `ClusterIP` — nada de NodePort. Consequência prática:
adicionar app ou rota é aplicar um `Ingress`, sem abrir porta no Security Group e
sem recriar cluster.

---

## Arquitetura do canal

```
   workflow_dispatch (image_tag)
        │
        ▼
   GitHub runner ──scp manifesto──►  EC2
        │                            └─ kind cluster
        └──ssh: kubectl apply ────►     ├─ ingress-nginx (:80) ── host todolist.local
                                        └─ namespace todolist
                                           └─ Deployment + Service ClusterIP + Ingress
```

O runner hospedado do GitHub faz o papel de operador remoto: ele já tem o
repositório em checkout, então copia o manifesto por `scp` e executa `kubectl` por
`ssh`. Nada precisa ser clonado dentro da VM, e o repositório pode seguir privado.

---

## Pré-requisitos

### O alvo de deploy

Uma EC2 com Docker, `kind` e `kubectl` instalados, um cluster kind com
`ingress-ready` + `extraPortMappings` de 80/443, e o **ingress-nginx** instalado. A
chave SSH é gerada **dentro da VM**: a pública vai para `authorized_keys`, a
privada vira o secret do GitHub.

Passo a passo completo, do launch da instância ao OpenLens:
**[cd-lab-vm-setup.md](cd-lab-vm-setup.md)**.

### Secrets e variables

Cadastrados em **Settings → Secrets and variables → Actions**:

| Nome | Tipo | Para quê |
|---|---|---|
| `EC2_SSH_KEY` | secret | Chave SSH **privada** gerada na VM, conteúdo completo |
| `EC2_HOST` | secret | Public IPv4 address da EC2 |
| `EC2_USER` | secret | Usuário SSH da VM (`ec2-user`) |
| `DOCKERHUB_USERNAME` | secret | Compõe o nome da imagem (`<usuário>/app-k8s-todolist`) |
| `KIND_CLUSTER` | variable | Nome do cluster kind (default `devops-labs` se ausente) |

Ao copiar a chave privada, copie **tudo**, das linhas
`-----BEGIN OPENSSH PRIVATE KEY-----` até a `-----END OPENSSH PRIVATE KEY-----`.
Chave truncada é a causa #1 de `Permission denied (publickey)`.

Os secrets do CI (`DOCKERHUB_TOKEN`, `NOTIFY_WEBHOOK_URL`) estão em
[ci-pipeline.md](ci-pipeline.md).

### A imagem e os manifestos

- A imagem `<DOCKERHUB_USERNAME>/app-k8s-todolist:<tag>` precisa **existir** no
  Docker Hub. O CI publica `latest` no push da `main`.
- O repositório no Docker Hub precisa ser **público** — se for privado, falta um
  `imagePullSecret` no cluster (ver [Próximos passos](#próximos-passos)).
- **Antes do primeiro deploy**, troque `SEU_USUARIO_DOCKERHUB` nas linhas `image:`
  dos manifestos em `k8s/` pelo usuário do Docker Hub: 1 ocorrência em
  `todolist.yaml` e 2 em `blue-green/bootstrap.yaml` (uma por cor).

### Valide o canal antes de deployar

Rode `validate-ssh.yml` primeiro: ele entra na EC2 por SSH, seleciona o contexto do
kind e lista os namespaces. Este workflow **já vem pronto e funcional** no kit — não
precisa de nenhuma alteração, só dos secrets acima. Dispare em
**Actions → Validate SSH to EC2 → Run workflow**.

Deploy sobre canal não validado transforma erro de infra em erro de pipeline, e você
perde tempo debugando o lugar errado.

Debug comum:

- **`Permission denied (publickey)`** — secret `EC2_SSH_KEY` incompleto, ou a
  pública não foi para `authorized_keys`
- **`Connection timed out`** — o IP mudou, ou o Security Group não libera a 22
- **`error: no context exists with the name`** — o nome do cluster kind não bate
  com a variable `KIND_CLUSTER`

> **A pegadinha do IP:** o Public IPv4 muda cada vez que a EC2 é parada e iniciada.
> Se a instância é parada ao fim de cada sessão para preservar crédito, no início
> da seguinte o IP quase sempre é outro — atualize o `EC2_HOST` **antes** de rodar
> qualquer coisa. Sintoma de esquecer: `Connection timed out` em todos os deploys.

---

## Rolling Update (`cd.yml`)

A estratégia padrão do Kubernetes e o ponto de partida: manual, um ambiente só.

- **Disparo:** `workflow_dispatch`, com input `image_tag` — quem dispara escolhe
  qual tag vai para o cluster
- **Ferramenta:** `kubectl apply` do manifesto `k8s/todolist.yaml`
- **Ambiente:** namespace `todolist`
- **Cor da UI:** `purple`, para distinguir visualmente dos slots blue/green

### Os passos e o papel de cada um

1. **Checkout** — traz `k8s/todolist.yaml` para o runner.
2. **Configure SSH key** — grava o secret em `~/.ssh/id_ed25519`, ajusta permissão
   (o SSH recusa chave com permissão frouxa) e registra o host em `known_hosts`.
3. **Pin image tag** — reescreve a linha `image:` do manifesto com `sed`. Casando a
   partir de `image:`, a indentação do YAML é preservada.
4. **Copy manifest** — `scp` do manifesto ajustado para a home na EC2.
5. **Apply and wait for rollout** — seleciona o contexto `kind-${KIND_CLUSTER}`,
   roda `kubectl apply` e espera com `kubectl rollout status --timeout=120s`. **Este
   é o gate**: se o pod novo não fica `Ready`, o step falha.
6. **Smoke test** — `curl -H "Host: todolist.local" http://localhost/healthz`
   através do ingress, com retry. Prova o caminho inteiro: ingress → Service → pod
   → banco.

### Por que isso é Rolling Update

`kubectl apply` num Deployment aciona o `RollingUpdate`, a estratégia default do
Kubernetes: sobe o pod novo, espera ficar `Ready` pela `readinessProbe`, e só então
remove o antigo. Sem downtime, ao custo de **duas versões convivendo** durante a
transição.

### Rollback do rolling

Não é automático. Duas opções:

```bash
# Opção 1: re-deployar a tag anterior pelo próprio pipeline
gh workflow run cd.yml -f image_tag=<tag-anterior>

# Opção 2: na VM, desfazer a última revisão
kubectl rollout undo deployment/todolist -n todolist
```

Rollback **automático** exigiria `helm upgrade --atomic` — está no roadmap.

---

## Blue/Green (deploy + switch)

Blue/green clássico, com as duas operações **deliberadamente separadas em duas
pipelines**: primeiro você publica a versão num slot de cor; depois, como decisão
própria, vira o tráfego.

### Topologia (namespace `todolist-bg`)

Dois Deployments de cor fixa, três Services `ClusterIP` e um Ingress com três
hosts:

| Service | Selector | Host | Papel |
|---|---|---|---|
| `todolist-blue` | `color: blue` | `blue.todolist-bg.local` | Testar o slot blue |
| `todolist-green` | `color: green` | `green.todolist-bg.local` | Testar o slot green |
| `todolist` | `color: <ativo>` | `todolist-bg.local` | **Produção** — selector flipado pelo switch |

A ideia central: **o switch mexe só no selector do Service de produção.** O Ingress
e os hosts nunca mudam. Roteamento é dado declarativo, não infra.

**Bootstrap** (`k8s/blue-green/bootstrap.yaml`) cria os dois Deployments, os três
Services e o Ingress, com produção começando em `blue`. A pipeline de deploy aplica
isso sozinha na primeira execução, se o namespace ainda não existir.

### Pipeline de deploy (`cd-blue-green.yml`)

Publica uma versão no slot escolhido, **sem** tocar no tráfego de produção.

Inputs: `color` (blue|green) e `image_tag`.

1. `kubectl set image` no Deployment da cor + `rollout status`.
2. Smoke test no host **fixo do slot** (`blue.` / `green.todolist-bg.local`) — não
   no host de produção.
3. Avisa no log se a cor escolhida já é a de produção (o deploy iria direto ao
   tráfego, anulando a rede de proteção do blue/green), mas **segue**.

```bash
gh workflow run cd-blue-green.yml -f color=green -f image_tag=latest
```

### Pipeline de switch (`cd-blue-green-switch.yml`)

O cutover. Input: `color`.

1. Confirma que o slot alvo está **saudável** no host dele, antes de virar. Virar
   tráfego para slot doente é causar incidente com um clique.
2. `kubectl patch` no selector do Service `todolist` → cor escolhida.
3. Confirma o `/healthz` no host de produção.
4. Imprime no log como fazer o rollback. Log bom é o que serve na hora do
   incidente.

```bash
gh workflow run cd-blue-green-switch.yml -f color=green
```

### Fluxo típico

```
deploy(green, X) → testa em green.todolist-bg.local → switch(green) → produção serve green
                                                      (rollback: switch(blue))
```

**Rollback é instantâneo:** rodar o switch de novo com a cor anterior. Como a cor
antiga **continua rodando** (não escalamos para 0), o repatch resolve na hora. Este
é o argumento de venda do blue/green, e o custo é o dobro de recursos durante o
período de convivência.

### Detalhes e escolhas

- **Deploy e switch desacoplados:** preparar a versão é uma ação, o cutover é
  outra. Permite gatear o switch com aprovação (GitHub Environment) sem mexer no
  deploy.
- **Entrada por ingress:** o switch é `Service`/selector, sem NodePort e sem
  recriar cluster — o mesmo padrão de produção.
- **A UI muda de cor:** cada Deployment sobe com o seu `APP_COLOR` (`blue` num,
  `green` no outro), então o switch é visível a olho nu. Sinal imediato de qual
  versão está em produção.
- **Acesso pelo navegador:** mapeie os hosts do lab no seu `/etc/hosts` apontando
  para o IP público da EC2:

  ```
  <PUBLIC_IP> todolist.local todolist-bg.local blue.todolist-bg.local green.todolist-bg.local
  ```

---

## `/healthz`: o endpoint que sustenta o pipeline

A mesma rota aparece em três papéis diferentes, e vale distinguir:

1. **`readinessProbe`** — o Kubernetes só manda tráfego para o pod depois que o
   `/healthz` responde. É o que o `kubectl rollout status` espera.
2. **`livenessProbe`** — se parar de responder, o Kubernetes reinicia o container.
3. **Smoke test do pipeline** — o último step do CD faz `curl` no `/healthz`
   através do ingress. Prova que o caminho **inteiro** funciona.

Ele não devolve `ok` de graça: executa um `SELECT 1` no banco e retorna `503` se o
banco não responder. Health check que sempre responde `ok` não é health check.

---

## Persistência: SQLite em `emptyDir`

O banco fica em `/data/todos.db`, montado como `emptyDir` — volume que vive e morre
com o pod. Consequências que valem discussão:

- **Cada pod tem o seu banco.** Com mais de uma réplica, as tarefas que você vê
  dependem de qual pod atendeu.
- **Reiniciou o pod, sumiram os dados.** No blue/green, trocar de cor "reinicia" a
  lista, porque é outro Deployment. Como só uma cor serve produção por vez, não há
  incoerência de leitura — mas não há continuidade.
- **É por isso que Canary não cabe aqui:** canary manda tráfego para as duas
  versões ao mesmo tempo, e com um banco por pod o mesmo usuário veria listas
  diferentes a cada request. Sem falar que, em k8s puro, a fração de tráfego é a
  razão de réplicas — 5% exigiria ~20 pods.

Continuidade de dados exigiria um `PersistentVolumeClaim` ou banco externo, e isso
é **ortogonal** à estratégia de deploy. A escolha aqui é deliberada: manter o lab
leve e o foco no pipeline.

---

## Limitações conscientes

Assumidas de propósito, e vale saber nomear cada uma:

- **Sem rollback automático no rolling.** Se o rollout falha, o step quebra no
  `rollout status`, mas a revisão anterior não é revertida sozinha.
- **Deploy manual.** Nada dispara após o merge; o workflow é acionado à mão.
- **Ambiente único.** Um namespace, um cluster, sem promoção test → prod.
- **Chave privada como secret.** Vaza o secret, vaza o cluster.
- **Security Group aberto em `0.0.0.0/0`.** Qualquer bot tenta a porta 22.
- **O CI conhece o cluster.** Blast radius maior se o runner for comprometido.

> É assim porque é **didático**: o caminho mais curto entre "commit" e "pod
> rodando", com o mínimo de infra no caminho. Saber por que **não** é assim que se
> faz em escala é parte do aprendizado.

---

## Próximos passos

Evoluções naturais, em ordem de maturidade:

- [ ] **Disparo automático após o CI** — `on: workflow_run` acionando o deploy
      quando o CI conclui com sucesso na `main`.
- [ ] **Múltiplos ambientes (test / prod)** — GitHub Environments, um cluster por
      ambiente, secrets por ambiente.
- [ ] **Approval em prod** — required reviewer no environment de produção,
      promovendo **a mesma imagem** que passou em test.
- [ ] **Rollback automático no rolling** — migrar para Helm com
      `helm upgrade --install --atomic --wait`.
- [ ] **imagePullSecret** — caso a imagem no Docker Hub seja privada.
- [ ] **GitOps** — ArgoCD/Flux reconciliando o cluster a partir do Git, com o CI
      deixando de conhecer o cluster.

---

## Como isso se faz em produção

O `kind` na EC2 é um lab, mas o padrão que estas pipelines espelham — entrada única
via ingress, roteamento declarativo — é o mesmo de produção:

- **Ponto de entrada estável:** um `Service type=LoadBalancer` faz o cloud
  provisionar um load balancer com IP/DNS fixo na frente do ingress controller.
  Provisionado uma vez; nunca se recria para mudar rota.
- **Roteamento é dado:** adicionar app ou rota = aplicar `Ingress`/`HTTPRoute`.
- **Blue/Green e Canary de verdade:** com Gateway API ou service mesh
  (Envoy/Istio), o switch é mudança declarativa de `weight`/backend. **Argo
  Rollouts** e **Flagger** automatizam o cutover e o rollback com análise de
  métricas.
- **Push vs Pull:** aqui o pipeline empurra via SSH, e portanto tem credenciais do
  cluster. Com GitOps, um agente **dentro** do cluster reconcilia o estado a partir
  do Git, e o CI não conhece o cluster.

A diferença para o lab é essencialmente **o ponto de entrada**: aqui o ingress-nginx
é exposto por um `extraPortMapping` do kind; em produção, por um load balancer do
cloud. O resto — Ingress, Services `ClusterIP`, switch por selector — é igual.
