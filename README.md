# CI/CD Grupo 1

Pipeline de Integração e Entrega Contínua da equipe — Atividades 1 (CI) e 2 (CD) da disciplina.

## Membros

* **@cicerooant Cicero Antonio**
* **@ErisonSantiago Erison Santiago**
* **@mviniciusalves Marcos Vinicius**

Professor: **@HardSource** (Read)

---

## Pipeline de CI

Referência completa: [docs/ci-pipeline.md](docs/ci-pipeline.md)

O CI funciona como um conjunto de **quality gates** que bloqueiam o merge na `main` quando algum check falha. Todo PR passa por:

| Gate                | O que valida                                             |
| ------------------- | -------------------------------------------------------- |
| **Lint (ruff)**     | Estilo, imports e padrões conhecidos de erro             |
| **Trivy (fs scan)** | Vulnerabilidades no filesystem (código + dependências)   |
| **Pytest**          | Suíte de testes da aplicação                             |
| **pip-audit**       | CVEs em dependências Python                              |
| **Docker Hub push** | Build e publicação da imagem (somente em push na `main`) |

### Destaques da implementação

* **Gatilhos:** `pull_request` e `push` em `main`
* **Matrix:** Python 3.11 e 3.12
* **Cache:** pip com chave por versão + hash dos requirements
* **Reusable workflow:** `_reusable-test.yml` chamado via `workflow_call`
* **Branch protection:** required status checks, review de Code Owners e sem bypass
* **Environment ****`staging`****:** required reviewer antes do deploy
* **Notificações:** job `notify` envia o status para o webhook do time
* **`permissions:`**** mínimo** por workflow e por job
* **Pinning por SHA** de todas as actions (`checkout`, `setup-python`, `cache`, `docker/*`)
* **CODEOWNERS:** exigindo review de quem mantém cada área

### Shift-left demonstrado

O PR #6 rebaixou `requests` para `2.31.0`. O `pip-audit` identificou 3 CVEs:

* `PYSEC-2026-1873`
* `PYSEC-2026-1872`
* `PYSEC-2026-2275`

As vulnerabilidades fizeram o pipeline falhar e bloquearam o merge por meio da branch protection.

A atualização de `requests` para `2.33.0` corrigiu o problema e permitiu a continuidade do fluxo.

Detalhes no [docs/ci-pipeline.md](docs/ci-pipeline.md).

---

## Pipeline de CD

Referência completa: [docs/cd-pipeline.md](docs/cd-pipeline.md)

O CD leva a imagem publicada no Docker Hub até o cluster Kubernetes.

### Infraestrutura

* **EC2 (AWS Academy Learner Lab)** — instância `t3.small` rodando Amazon Linux 2023
* **kind** — cluster Kubernetes local (`devops-labs`) dentro da EC2
* **ingress-nginx** — entrada HTTP única (porta 80), com roteamento por host
* **GitHub Actions → EC2** via SSH (`validate-ssh.yml` prova o canal)
* **Aplicação** exposta em `todolist.local`

### Fluxo

```text
Pull Request
     │
     ▼
CI (lint, Trivy, pytest, pip-audit)
     │
     ▼
Branch Protection (required checks + review)
     │
     ▼
Merge na main
     │
     ▼
Build + push → Docker Hub
     │
     ▼
Deploy no cluster kind
├── Rolling (cd.yml) — implementado
```

### Estratégias de deploy

O projeto contempla duas estratégias de deploy:

* **Rolling Update:** implementado em `cd.yml` — `scp` do manifesto + `kubectl apply` + `rollout status` + smoke test em `/healthz`

O rollback do Blue/Green será feito via **re-switch de tráfego** para a cor anterior.

---

## Como rodar localmente

### Clonar o repositório

```bash
git clone https://github.com/grupo01mas/cicd-grupo-01.git
cd cicd-grupo-01
```

### Criar o ambiente virtual

**Linux/macOS:**

```bash
python -m venv .venv
source .venv/bin/activate
```

**Windows PowerShell:**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Instalar as dependências

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Rodar os quality gates localmente

```bash
# Lint
ruff check .

# Testes
pytest -q

# Auditoria de dependências
pip-audit -r requirements.txt
```

### Subir a aplicação

```bash
python app.py
```

A aplicação ficará disponível em:

```text
http://localhost:5000
```

Credenciais:

```text
Login: admin
Senha: admin
```

---

## Rodando via Docker

Construir a imagem:

```bash
docker build -t todolist:dev .
```

Executar o container:

```bash
docker run --rm \
  -p 8080:5000 \
  -e APP_COLOR=blue \
  -e SESSION_KEY=local \
  todolist:dev
```

A aplicação ficará disponível em:

```text
http://localhost:8080
```

---

## Estrutura do projeto

```text
.
├── app.py                         # Flask + SQLite
├── test_app.py                    # Suíte pytest
├── requirements.txt               # Dependências de produção
├── requirements-dev.txt           # pytest, ruff, pip-audit
├── pyproject.toml                 # Configuração do ruff
├── Dockerfile                     # Imagem da aplicação
│
├── k8s/
│   ├── todolist.yaml              # Deployment + Service + Ingress (rolling)
│   └── blue-green/
│       └── bootstrap.yaml         # Blue/Green: 2 cores + 3 Services + Ingress
│
├── .github/
│   ├── CODEOWNERS
│   └── workflows/
│       ├── ci.yml                 # Quality gates em PR
│       ├── _reusable-test.yml     # Steps de teste reutilizáveis
│       └── validate-ssh.yml       # Valida GitHub → EC2 → kind
│
└── docs/
    ├── ci-pipeline.md             # Referência do pipeline de CI
    ├── cd-pipeline.md             # Referência do pipeline de CD
    └── cd-lab-vm-setup.md         # Setup da EC2 + kind + ingress
```

---

## Secrets e Variables

Cadastrados em **Settings → Secrets and variables → Actions**:

| Nome                 | Tipo     | Para quê                                         |
| -------------------- | -------- | ------------------------------------------------ |
| `DOCKERHUB_USERNAME` | Secret   | Usuário do Docker Hub                            |
| `DOCKERHUB_TOKEN`    | Secret   | Access token do Docker Hub (Read, Write, Delete) |
| `NOTIFY_WEBHOOK_URL` | Secret   | Webhook do canal do time                         |
| `EC2_HOST`           | Secret   | IPv4 público da EC2                              |
| `EC2_SSH_KEY`        | Secret   | Chave privada SSH da EC2                         |
| `EC2_USER`           | Secret   | Usuário SSH (`ec2-user`)                         |
| `KIND_CLUSTER`       | Variable | Nome do cluster kind (`devops-labs`)             |

---

## Teardown

### Ao fim de cada sessão

* Parar a EC2 (**Stop**, não **Terminate**) para preservar o ambiente e o cluster kind.
* Atualizar o secret `EC2_HOST` na próxima sessão, pois o IPv4 público pode mudar.

### Ao fim do curso

* Terminate da instância EC2.
* Revogar o access token do Docker Hub.
* Remover o webhook do canal.
