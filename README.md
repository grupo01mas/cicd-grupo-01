# Starter-kit — CI/CD e Automação de Deployments

Repositório-base da disciplina. Cada equipe cria **o seu** repositório a partir
deste template e o evolui ao longo do curso, entregando dois projetos avaliativos:
**CI** e **CD**.

A aplicação e os manifestos já vêm prontos. **Os pipelines, não** — eles são o
objeto de estudo e são escritos por vocês, em aula. O que o kit entrega são
esqueletos comentados em `.github/workflows/*.yml.example`, com TODOs na ordem de
construção.

---

## Como começar

**Só o Repo Owner da equipe faz isto.** Os demais aguardam o convite.

1. Neste repositório, clicar em **Use this template → Create a new repository**
2. Nome sugerido: `cicd-grupo-<N>` · Visibilidade: **Private**
3. **Settings → Collaborators → Add people**:
   - cada membro do grupo com permissão **Write**
   - **`HardSource`** (o professor) com permissão **Read** — é assim que a entrega
     é avaliada, já que o repositório é privado
4. Todo mundo clona:

```bash
git clone https://github.com/<owner>/cicd-grupo-<N>.git
cd cicd-grupo-<N>
```

Pelo `gh` CLI, os passos 1 a 4 viram:

```bash
gh repo create cicd-grupo-1 --template HardSource/cicd-starter-kit --private --clone

# membros do grupo (repetir para cada um)
gh api -X PUT /repos/<owner>/cicd-grupo-1/collaborators/<username> -f permission=push

# professor, somente leitura
gh api -X PUT /repos/<owner>/cicd-grupo-1/collaborators/HardSource -f permission=pull
```

> Convidar o professor **no início**, não na véspera da apresentação: o convite
> precisa ser aceito, e repositório inacessível na hora da correção conta como
> entrega não disponível.

### Confirme que a base funciona antes de automatizar

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -v
```

Todos os testes devem passar. Automatizar uma base quebrada só multiplica o
problema.

---

## Estrutura

```
.
├── app.py                     Flask + SQLite (rota /healthz usada pelos gates)
├── test_app.py                Suíte pytest
├── requirements.txt           Dependências de produção — alvo dos scans
├── requirements-dev.txt       pytest, ruff, pip-audit
├── pyproject.toml             Configuração do ruff
├── Dockerfile                 Imagem da app
├── k8s/
│   ├── todolist.yaml          Rolling: Deployment + Service ClusterIP + Ingress
│   └── blue-green/
│       └── bootstrap.yaml     Blue/Green: 2 cores + 3 Services + Ingress
├── .github/
│   ├── CODEOWNERS.example     Template — renomeie e preencha
│   └── workflows/
│       ├── validate-ssh.yml                  PRONTO — valida o canal até o cluster
│       ├── ci.yml.example                    Quality gates em PR
│       ├── _reusable-test.yml.example        Steps de teste reutilizáveis
│       ├── cd.yml.example                    Deploy Rolling
│       ├── cd-blue-green.yml.example         Deploy num slot de cor
│       └── cd-blue-green-switch.yml.example  Switch de tráfego
└── docs/
    ├── ci-pipeline.md         Referência do pipeline de CI
    ├── cd-pipeline.md         Referência das pipelines de CD
    └── cd-lab-vm-setup.md     Provisionar a EC2 + kind + ingress pelo Console
```

### Por que `.yml.example`

O GitHub Actions só executa arquivos `.yml`/`.yaml` em `.github/workflows/`. Os
`.example` ficam inertes até vocês renomearem:

```bash
git mv .github/workflows/ci.yml.example .github/workflows/ci.yml
```

Cada esqueleto tem TODOs numerados na ordem de construção, e um step `TODO guard`
que **falha de propósito** — pipeline que passa verde sem testar nada é pior que
pipeline que falha. Complete um bloco, faça push, veja rodar, e só então siga para
o próximo.

**A exceção é o `validate-ssh.yml`**, que já vem completo e funcional. Ele não é
exercício: é a ferramenta de diagnóstico que prova que o GitHub alcança o cluster.
Não precisa alterar nada nele — basta cadastrar os secrets `EC2_*` e rodar.

---

## Roteiro de construção

### Fase 1 — Integração Contínua

1. Repositório da equipe criado, membros como collaborators
2. `CODEOWNERS` preenchido + branch protection na `main`
3. `ci.yml`: gatilhos em PR e push, `pytest` e `pip-audit` como gates
4. Matrix de Python + cache de dependências
5. Steps de teste extraídos para o reusable workflow
6. Environment com required reviewer
7. `permissions:` mínimo + pinning de actions por SHA
8. Trivy como gate de segurança
9. Notificação de status no canal da equipe
10. Badge e documentação do pipeline no README

Detalhe de cada peça: **[docs/ci-pipeline.md](docs/ci-pipeline.md)**.

### Fase 2 — Entrega Contínua

1. EC2 com `kind` + `ingress-nginx`, chave SSH gerada dentro da VM
2. Imagem publicada no Docker Hub pelo `ci.yml`
3. Secrets `EC2_*` e variable `KIND_CLUSTER` cadastrados
4. `validate-ssh.yml` verde — o canal está provado (workflow já pronto no kit)
5. `cd.yml`: Rolling deployment com `rollout status` e smoke test
6. `cd-blue-green.yml` + `cd-blue-green-switch.yml`: deploy por cor e cutover
7. Rollback do Blue/Green demonstrado (re-switch para a cor anterior)

Passo a passo do item 1: **[docs/cd-lab-vm-setup.md](docs/cd-lab-vm-setup.md)**.
Detalhe dos pipelines: **[docs/cd-pipeline.md](docs/cd-pipeline.md)**.

---

## Antes de cada sessão prática

A EC2 é parada ao fim de cada sessão para preservar crédito, e o **IP público muda**
ao reiniciar. Rotina de abertura:

1. Console da AWS → **EC2 → Instances → Start instance**
2. Copiar o novo Public IPv4
3. **Settings → Secrets → `EC2_HOST` → Update**
4. Rodar `validate-ssh.yml` e confirmar o verde

Pular o passo 3 faz todo o CD falhar com `Connection timed out`. É o erro mais
comum do curso.

---

## Antes do primeiro deploy

Os manifestos em `k8s/` usam o placeholder `SEU_USUARIO_DOCKERHUB`. Troque pelo
usuário do Docker Hub da equipe nos dois arquivos:

- `k8s/todolist.yaml` — 1 ocorrência
- `k8s/blue-green/bootstrap.yaml` — 2 ocorrências (uma por cor)

O `cd.yml` reescreve a linha do `k8s/todolist.yaml` a cada execução, mas o
bootstrap do blue/green sobe as duas cores com o valor que estiver no arquivo.

---

## A aplicação

Uma todo-list em Flask + SQLite, deliberadamente simples: o objeto de estudo é o
**pipeline**, não a aplicação. Vocês não precisam alterar `app.py` em momento
nenhum. As únicas mudanças de código previstas são no `requirements.txt`
(exercício de shift-left) e, opcionalmente, em `test_app.py`.

Login padrão: `admin` / `admin`.

| Variável | Default | Descrição |
|---|---|---|
| `APP_NAME` | `TodoList` | Título exibido na interface |
| `APP_PORT` | `5000` | Porta do servidor |
| `APP_COLOR` | *(cinza)* | Cor do tema — é o que torna o blue/green visível |
| `SESSION_KEY` | `dev-only-insecure-key` | Assina o cookie de sessão |
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` | Credenciais de login |
| `CLEANUP_TOKEN` | *(vazio)* | Token exigido por `POST /cleanup` |
| `DATABASE_URI` | `sqlite:////data/todos.db` | URI do SQLAlchemy |
| `IMAGE_TAGS` | *(vazio)* | Tags da imagem, injetadas pelo CI. Aparecem no rodapé |

`APP_COLOR` aceita `purple`, `green`, `blue`, `cyan`, `pink`, `red`, `orange`,
`brown`, `yellow`. Valor ausente ou inválido cai no cinza. Os manifestos usam
`purple` no rolling e `blue`/`green` nos slots, então a interface **muda de cor ao
vivo** quando o switch de tráfego roda.

Rodando pelo Docker:

```bash
docker build -t todolist:dev .
docker run --rm -p 8080:5000 -e APP_COLOR=blue -e SESSION_KEY=local todolist:dev
```

> Porta 8080 no host de propósito: no macOS a 5000 é ocupada pelo AirPlay
> Receiver, que responde `403` e gera confusão.

As rotas `/pods` e `/cleanup/status` chamam a API do Kubernetes via ServiceAccount.
Os manifestos deste kit são mínimos de propósito e não incluem ServiceAccount nem
RBAC, então as duas páginas mostram "Unable to query the Kubernetes API". Isso é
esperado e não afeta nenhuma entrega.

---

## O README é entregável

Este arquivo é do professor. **Substituam pelo README da equipe** — ele é avaliado
nas duas rubricas. O mínimo esperado:

```markdown
# CI/CD Grupo <N>

![CI](https://github.com/<owner>/<repo>/actions/workflows/ci.yml/badge.svg)

## Membros
- @user1 (Owner) · @user2 · @user3 · @user4

## Pipeline de CI
Gatilhos, matrix, cache, reusable, gates de segurança, environment, notificações.

## Pipeline de CD
Arquitetura do deploy, as duas estratégias, como fazer rollback.

## Como rodar localmente
...
```

O snippet do badge sai pronto em **Actions → workflow "CI" → ... → Create status
badge**. Badge verde = `main` saudável; vermelho = `main` quebrada, e consertar
vira prioridade sobre qualquer feature.

---

## Checklist — Projeto 1 (CI)

- [ ] Branch `main` protegida: require PR, require status checks, CODEOWNERS
- [ ] Professor (`HardSource`) adicionado como collaborator com permissão `Read`
- [ ] `ci.yml` disparando em `pull_request` e em `push` na `main`
- [ ] `pytest` e `pip-audit` rodando como gates
- [ ] Matrix em pelo menos 2 versões do Python
- [ ] Cache de dependências
- [ ] Reusable workflow (`workflow_call`) extraindo os steps de teste
- [ ] Environment com required reviewer
- [ ] `permissions:` mínimo explícito
- [ ] Actions com pin por SHA
- [ ] Trivy como gate de segurança
- [ ] Notificação de sucesso e de falha chegando no canal da equipe
- [ ] Badge de status no README + README explicando o pipeline
- [ ] Falha de segurança demonstrada e corrigida (shift-left)
- [ ] Participação de todos os membros verificável (commits, preparação do ambiente ou apresentação)

## Checklist — Projeto 2 (CD)

- [ ] Imagem publicada no Docker Hub com tag do commit, via access token
- [ ] EC2 com kind + ingress-nginx, chave SSH gerada dentro da VM
- [ ] Manifestos em `k8s/`: Deployment + Service `ClusterIP` + Ingress
- [ ] `cd.yml`: `scp` + `kubectl apply` + `rollout status` + smoke test `/healthz`
- [ ] `cd-blue-green.yml` + `cd-blue-green-switch.yml`, com `run-name` dinâmico
- [ ] Rollback do Blue/Green demonstrado (re-switch de tráfego)
- [ ] README atualizado com a arquitetura de deploy

---

## Teardown

**Ao fim de toda sessão prática:**

- [ ] EC2 em **Stop instance** — não Terminate. Preserva o disco e o cluster kind
- [ ] Confirmar no Console que o estado é `stopped`
- [ ] Lembrar que o `EC2_HOST` precisará ser atualizado na próxima sessão

**Ao fim do curso:**

- [ ] **Terminate instance** — apaga a EC2 e o volume EBS
- [ ] Conferir em **EC2 → Volumes** se não sobrou volume órfão
- [ ] Revogar o access token do Docker Hub
- [ ] Remover o webhook de notificação do canal

> `t3.small` custa ~US$ 0,023/h, então o crédito do Learner Lab tem folga enorme. O
> motivo do teardown é higiene e disciplina de FinOps, não risco de estourar o
> crédito. Instância esquecida ligada é o clássico da vida real.
