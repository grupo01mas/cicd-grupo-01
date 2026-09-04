# Pipeline de Integração Contínua (CI)

Referência do pipeline de CI: `.github/workflows/ci.yml` e o reusable
`.github/workflows/_reusable-test.yml`.

O objetivo do CI é ser um conjunto de **quality gates** que bloqueiam o merge
quando lint, testes ou scans de segurança falham — e publicar a imagem no Docker
Hub quando tudo passa.

> Este doc explica **o que cada peça faz e por quê**. Os esqueletos comentados,
> com os TODOs na ordem de construção, estão em `.github/workflows/*.yml.example`.

---

## As peças

| Peça | Papel |
|---|---|
| Gatilhos em `pull_request` e `push` na `main` | Faz o pipeline ser gate de merge |
| Job de teste com `pytest` | Prova que a app funciona |
| `pip-audit` | Gate de CVE nas dependências |
| Matrix de Python + cache de pip | Cobertura de versões e feedback rápido |
| Reusable workflow (`workflow_call`) | DRY: uma definição de teste, vários chamadores |
| Environment com required reviewer | Aprovação humana antes de um passo sensível |
| `permissions:` mínimo + pinning por SHA | Reduz o raio de dano do pipeline |
| Trivy | Gate de CVE na imagem e no filesystem |
| Notificação por webhook | O pipeline conversa com o time |
| Build e push no Docker Hub | Entrega o artefato versionado |

---

## Gatilhos

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

- **`pull_request` para `main`** — roda em toda proposta de merge. É o gatilho que
  faz o CI ser um gate de verdade.
- **`push` para `main`** — roda quando algo entra na branch principal, mantendo o
  badge do README honesto sobre a saúde da `main`.

Uma extensão comum é `tags: ['*']` no `push`, para publicar imagem versionada
quando uma tag é criada.

---

## Permissions: menor privilégio

```yaml
permissions:
  contents: read
```

Sem bloco `permissions:` explícito, o `GITHUB_TOKEN` do workflow vem com
`contents: write` (ou mais). Um workflow comprometido — via action de terceiro
maliciosa, por exemplo — poderia escrever no repositório, criar releases, apagar
coisas.

Declarar só o que o workflow realmente precisa é a mitigação. Jobs específicos
podem pedir mais que o padrão do workflow:

```yaml
  jobs:
    algum-job:
      permissions:
        contents: read
        security-events: write     # necessário para upload de SARIF (Trivy)
```

---

## Os gates

### Lint (`ruff`)

Roda `ruff check .` — estilo, ordenação de imports e padrões conhecidos de bug. A
configuração vive em `pyproject.toml`, então o mesmo comando dá o mesmo resultado
na sua máquina e no CI.

### Test (`pytest`) com matrix e cache

**Matrix** cria uma execução paralela do job por versão do Python:

```yaml
strategy:
  fail-fast: false
  matrix:
    python-version: ['3.10', '3.11', '3.12']
```

- Prova que a app funciona em **todas** as versões suportadas, não só na sua.
- `fail-fast: false` é importante: se a 3.10 quebra, as outras **continuam**
  rodando. Você descobre se o problema é de uma versão só ou de todas, em uma
  execução em vez de três.

**Cache** de dependências com `actions/cache`, sobre `~/.cache/pip`. A chave
inclui o hash de `requirements*.txt`:

- chave **igual** à anterior → cache hit, restaura tudo
- chave **diferente** → miss, mas `restore-keys` recupera um cache próximo e
  aproveita parte da instalação

Não é sobre economizar minutos de máquina: é sobre **feedback rápido no PR**.

### Dependency audit (`pip-audit`)

Consulta a base de advisories do Python (PyPI/OSV) e falha quando uma dependência
tem CVE conhecido **com correção disponível**.

É o gate do [exercício de shift-left](#o-exercício-de-shift-left): o
`requirements.txt` deste kit vem **limpo**, e a falha é introduzida de propósito.

### Container scan (`trivy`)

O Trivy enxerga mais que o `pip-audit`: além das bibliotecas Python, ele cobre os
pacotes do **sistema operacional base** da imagem.

Configurações que importam:

| Campo | Efeito |
|---|---|
| `scan-type: fs` | Escaneia arquivos e manifestos, sem precisar buildar a imagem |
| `severity: HIGH,CRITICAL` | Só reporta o que dá para agir |
| `exit-code: '1'` | **Transforma o scan em gate** — sem isso ele só informa |
| `ignore-unfixed: true` | Ignora CVE sem patch disponível, evitando build eternamente vermelho |
| `format: sarif` | Formato que alimenta a aba **Security → Code scanning** |

Subir o SARIF com `github/codeql-action/upload-sarif` exige
`security-events: write` nas permissions.

> Escaneando a imagem inteira, o Trivy também pega CVEs das ferramentas de
> empacotamento que vêm na base image (`pip`, `setuptools`, `wheel`). É por isso
> que o `Dockerfile` deste kit atualiza as três antes de instalar as dependências.

---

## Reusable workflow: o DRY do YAML

Em vez de repetir os steps de teste, o job `test` **delega** para um workflow
reutilizável do próprio repositório:

```yaml
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.10', '3.11', '3.12']
    uses: ./.github/workflows/_reusable-test.yml
    with:
      python-version: ${{ matrix.python-version }}
```

A divisão de responsabilidade: **a matrix vive no chamador, a lógica de teste vive
no reusable**. Trocar as versões testadas não toca nos steps; mudar os steps não
toca nas versões.

Dois cuidados que costumam pegar:

- Ao chamar um reusable, o job chamador **não** tem `runs-on` nem `steps`. Quem
  executa steps é o reusable.
- Os **nomes dos checks mudam** ao refatorar. Isso quebra os required checks já
  configurados na branch protection: rode o CI uma vez para os novos nomes
  aparecerem na lista e remarque-os. Esquecer disso deixa o merge liberado com
  teste falhando.

Convenção: o prefixo `_` sinaliza workflow de apoio, chamado por outros e não
disparado por evento próprio.

---

## Environment com required reviewer

Um environment é um objeto do repositório que agrupa secrets, variables e
**políticas de proteção**: required reviewers, wait timer, branches permitidas.

Um job reivindica o environment e as políticas entram em cena:

```yaml
  deploy-staging:
    needs: test
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    environment:
      name: staging
```

Com **required reviewer** configurado, o job aparece como *Waiting* e pausa até
alguém aprovar em **Review deployments**. A aprovação fica registrada no histórico
de deployments do repositório — auditoria de graça.

O `if:` restringe a push na `main`: não faz sentido "deployar" a cada PR.

Secrets cadastrados **dentro** do environment (**Settings → Environments →
staging → Add secret**) só existem para jobs que reivindicam aquele environment.
É a diferença entre secret de repositório e secret com escopo de ambiente.

---

## Pinning de actions por SHA

Tags e branches de actions são **mutáveis**. `@v4` hoje pode apontar para um commit
diferente amanhã, e você acabou de dar ao mantenedor (ou a quem comprometer a conta
dele) execução de código no seu pipeline com acesso aos seus secrets.

```yaml
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
```

O hash é imutável: você confia num commit específico que foi auditado, não num
nome. O comentário com a versão mantém a linha legível.

Estratégia prática:

- Actions de **terceiros**: sempre pin por SHA
- Actions **oficiais** do GitHub (`actions/*`): pin nas críticas
- **Renovate/Dependabot** cuidam de atualizar os pins, então isso não vira
  manutenção manual

O SHA completo aparece na página da release da action, ao lado da tag.

---

## Notificações

CI roda em background e ninguém fica olhando dashboard. Falha na `main` é
incidente que precisa de dono rápido.

O job de notificação usa `if: always()` — precisa rodar **justamente quando algo
falhou antes**, então não pode depender do sucesso dos jobs anteriores. Ele lê o
resultado dos outros jobs via `needs.<job>.result`, compõe a mensagem e faz `curl`
no webhook (secret `NOTIFY_WEBHOOK_URL`).

Sempre inclua o **link do run** na mensagem: notificação que não leva ao log gera
mais pergunta que resposta.

> Regra de dosagem: notifique o suficiente para acionar, não a ponto de virar
> ruído que todo mundo aprende a ignorar.

---

## Publicação da imagem no Docker Hub

Único job que **não** roda em paralelo: ele depende de todos os gates.

```yaml
needs: [lint, test, dependency-audit, container-scan, sast]
```

Nunca publicamos imagem que não passou pelos scans. Se qualquer gate falha, o push
nem é tentado.

### Regras de tag

| Evento | Tag principal | Exemplo |
|---|---|---|
| Pull request para `main` | `PR-<número>` | `PR-42` |
| Push na `main` | `latest` | `latest` |
| Criação de tag | a tag exata | `v1.2.0` |

Além da principal, **toda** imagem recebe uma segunda tag com o hash curto do
commit (`${GITHUB_SHA::7}`). É o que dá rastreabilidade exata: dado um pod
rodando, você sabe de qual commit ele veio.

### O rodapé com as tags

O conjunto de tags também vai como build-arg `IMAGE_TAGS`, e a app mostra a parte
curta de cada uma no rodapé, sob `version:`. Builds locais, sem o build-arg, não
mostram rodapé nenhum.

Serve para conectar "o que o pipeline fez" com "o que o usuário vê": o rodapé diz
exatamente qual build está rodando naquele pod.

---

## Secrets e variables

Cadastrados em **Settings → Secrets and variables → Actions**.

| Nome | Tipo | Para quê |
|---|---|---|
| `DOCKERHUB_USERNAME` | secret | Usuário/organização no Docker Hub. Compõe o nome da imagem: `<usuário>/app-k8s-todolist` |
| `DOCKERHUB_TOKEN` | secret | Access token do Docker Hub (**nunca** a senha da conta) |
| `NOTIFY_WEBHOOK_URL` | secret | Webhook do canal Slack/Discord do time |
| `STAGING_URL` | secret | Valor dummy, cadastrado **dentro** do environment `staging` |

O access token sai em **Docker Hub → Account settings → Personal access tokens →
Generate new token**, com permissão *Read, Write, Delete*. Ele aparece **uma única
vez**. Token é revogável e escopado; a senha da conta não — se o token vazar você
revoga um token, se a senha vazar você perde a conta.

> Webhook de Slack/Discord é um bearer token: quem tem a URL posta no canal.
> Nunca commite valor de secret, nem em comentário nem em arquivo de exemplo — um
> secret no histórico do Git continua lá depois de "apagado".

Os secrets do canal de deploy (`EC2_*`, `KIND_CLUSTER`) estão em
[cd-pipeline.md](cd-pipeline.md).

---

## O exercício de shift-left

O `requirements.txt` deste kit vem **limpo** de propósito: o pipeline fica verde na
primeira execução. A falha é introduzida deliberadamente, para você ver o gate agir.

**1. Quebrar** — numa branch nova, rebaixe o `requests` e abra um PR:

```diff
- requests==2.33.0
+ requests==2.31.0
```

**2. Observar** — `pip-audit` e Trivy ficam vermelhos, apontando os CVEs
(CVE-2024-35195, CVE-2024-47081, CVE-2026-25645) e as versões que corrigem. Lint e
testes seguem verdes: o problema está isolado na dependência. Com branch
protection ativa, o merge fica **bloqueado**.

**3. Corrigir** — na **mesma branch**, volte para a versão corrigida:

```diff
- requests==2.31.0
+ requests==2.33.0
```

> A correção precisa ser **2.33.0**. Bumpar só para `2.32.x` **não** zera todos os
> CVEs — bom lembrete de que "atualizar um pouco" nem sempre basta.

O ponto: o problema foi pego **no PR, antes do merge**, sem ninguém rodar a app e
sem chegar a produção. Custo do fix: 1x. Isso é shift-left, e não é sorte — é
desenho de pipeline.

Para demonstrar o gate de testes, quebre uma asserção de propósito em
`test_app.py` e observe o job `Test` vermelho nas três versões do Python.

---

## Sem branch protection, o pipeline é teatro

Um CI vermelho que não impede o merge não é gate, é decoração. Em
**Settings → Branches → Add branch ruleset** para `main`:

1. **Require a pull request before merging** — ninguém commita direto na `main`
2. **Require review from Code Owners** — ativa o efeito do `CODEOWNERS`
3. **Require status checks to pass** — marque os checks do CI como obrigatórios.
   **É este item que bloqueia o merge**
4. **Require branches to be up to date before merging** — força integrar a `main`
   antes de mergear
5. **Do not allow bypassing the above settings** — vale para o owner também

> Os status checks só aparecem na lista depois de rodarem **pelo menos uma vez**.
> Se a lista estiver vazia, abra um PR, deixe o CI rodar e volte para marcá-los.

---

## Rodando os gates localmente

Os mesmos comandos que o CI executa, na sua máquina:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

ruff check .                    # lint
pytest -q                       # testes
pip-audit -r requirements.txt   # audit de dependências
```

Rodar local antes de abrir PR economiza minutos de fila. Mesmo comando, mesmo
resultado.

---

## Relação com o CD

O CI publica a imagem; o [CD](cd-pipeline.md) leva uma tag publicada para o
cluster. O gancho entre os dois é **manual**: você dispara o CD escolhendo a tag.
Disparo automático (`on: workflow_run`) está no roadmap do doc de CD.
