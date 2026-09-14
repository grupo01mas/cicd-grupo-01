# Pipeline de Integração Contínua (CI)

Referência do pipeline de CI: `.github/workflows/ci.yml` e o reusable
`.github/workflows/_reusable-test.yml`.

O objetivo do CI é ser um conjunto de **quality gates** que bloqueiam o merge
quando lint, testes ou scans de segurança falham.

> **Status:** pipeline de CI implementado e ativo na `main`. Branch protection
> configurada com required status checks e Code Owners. O repositório é público,
> portanto as regras de proteção são aplicadas de verdade.
>
> Os arquivos `.yml.example` permanecem como material didático para demonstrar
> a evolução e a ordem de construção dos workflows.

---

## As peças

| Peça                                       | Papel                                          | Status         |
| ------------------------------------------ | ---------------------------------------------- | -------------- |
| Gatilhos `pull_request` e `push` na `main` | Faz o pipeline ser gate de merge               | ✅ Implementado |
| Job de teste com `pytest`                  | Prova que a aplicação funciona                 | ✅ Implementado |
| `ruff`                                     | Gate de qualidade e lint                       | ✅ Implementado |
| `pip-audit`                                | Gate de vulnerabilidades nas dependências      | ✅ Implementado |
| Matrix de Python + cache de pip            | Cobertura de versões e feedback rápido         | ✅ Implementado |
| Reusable workflow (`workflow_call`)        | DRY: uma definição de teste, vários chamadores | ✅ Implementado |
| `permissions:` mínimo + pinning por SHA    | Reduz o raio de dano do pipeline               | ✅ Implementado |
| Branch protection com required checks      | Bloqueia merge com CI vermelho                 | ✅ Configurada  |
| Code Owners                                | Exige revisão dos responsáveis pelo código     | ✅ Configurado  |
| Environment com required reviewer          | Aprovação humana antes de passo sensível       | ⏳ Roadmap (CD) |
| Trivy                                      | Gate de CVE na imagem e no filesystem          | ⏳ Roadmap (CD) |
| Notificação por webhook                    | O pipeline conversa com o time                 | ⏳ Roadmap (CD) |
| Build e push no Docker Hub                 | Entrega o artefato versionado                  | ⏳ Roadmap (CD) |

---

## Gatilhos

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

* **`pull_request` para `main`** — roda em toda proposta de merge. É o gatilho
  que faz o CI ser um gate de verdade.

* **`push` para `main`** — roda quando algo entra na branch principal, mantendo
  o estado da `main` visível.

Uma extensão comum para a etapa de CD é adicionar:

```yaml
on:
  push:
    tags: ['*']
```

Isso permite executar etapas específicas de publicação quando uma tag de versão
é criada.

> Essa publicação por tag não faz parte do CI atual e permanece como evolução
> planejada do pipeline de CD.

---

## Permissions: menor privilégio

```yaml
permissions:
  contents: read
```

Sem um bloco `permissions:` explícito, o `GITHUB_TOKEN` pode receber permissões
maiores do que o workflow realmente precisa.

Um workflow comprometido — por exemplo, por meio de uma action de terceiro
maliciosa — poderia utilizar essas permissões para modificar recursos do
repositório.

Declarar apenas as permissões necessárias reduz esse risco.

Jobs específicos podem solicitar permissões adicionais quando necessário:

```yaml
jobs:
  algum-job:
    permissions:
      contents: read
      security-events: write
```

A permissão `security-events: write`, por exemplo, será necessária em uma futura
etapa que utilize o Trivy e envie resultados em formato SARIF para o GitHub Code
Scanning.

---

## Os gates

### Lint (`ruff`)

O lint executa:

```bash
ruff check .
```

O `ruff` verifica problemas de estilo, imports e diversos padrões conhecidos de
erro.

A configuração fica centralizada no `pyproject.toml`, fazendo com que o mesmo
comando produza resultados consistentes localmente e no CI.

Se o lint falhar, o pipeline fica vermelho e o merge pode ser bloqueado pela
branch protection.

---

### Test (`pytest`) com matrix e cache

O job de testes utiliza uma **matrix** para executar os testes nas versões de
Python suportadas pelo projeto:

```yaml
strategy:
  fail-fast: false
  matrix:
    python-version: ['3.11', '3.12']
```

A matrix cria uma execução independente para cada versão.

Isso permite verificar se a aplicação funciona em:

* Python 3.11
* Python 3.12

O `fail-fast: false` é importante porque, se o Python 3.11 falhar, o Python 3.12
**continua executando**.

Assim é possível identificar se o problema está restrito a uma versão ou se
afeta todas as versões testadas.

### Cache

As dependências são armazenadas em cache utilizando o diretório:

```text
~/.cache/pip
```

A chave do cache considera o conteúdo dos arquivos de requirements.

Quando a chave é igual à utilizada anteriormente, ocorre um **cache hit**.

Quando as dependências mudam, ocorre um **cache miss**, mas o `restore-keys`
pode recuperar um cache próximo e reaproveitar parte dos arquivos existentes.

O objetivo principal não é apenas economizar minutos de processamento, mas
reduzir o tempo de feedback durante o desenvolvimento e nos Pull Requests.

---

### Dependency audit (`pip-audit`)

O `pip-audit` verifica as dependências Python do projeto contra bases de
vulnerabilidades conhecidas.

O comando utilizado localmente é:

```bash
pip-audit -r requirements.txt
```

Quando uma dependência possui uma vulnerabilidade conhecida com correção
disponível, o job falha.

Esse é um dos principais gates de **shift-left security** do pipeline.

O objetivo é detectar uma dependência vulnerável **antes do merge**, e não depois
que o código já chegou a um ambiente de execução.

---

## Container scan (`Trivy`) — roadmap

O Trivy **ainda não faz parte do CI implementado**. Ele permanece planejado para
a etapa de CD.

A intenção é utilizá-lo para verificar vulnerabilidades tanto nos arquivos da
aplicação quanto na imagem de container.

O Trivy complementará o `pip-audit`, pois poderá detectar vulnerabilidades que não
estão relacionadas exclusivamente às bibliotecas Python, incluindo componentes
do sistema operacional presentes na imagem base.

Configurações planejadas:

| Campo                     | Efeito                                                       |
| ------------------------- | ------------------------------------------------------------ |
| `scan-type: fs`           | Escaneia arquivos e manifestos sem precisar buildar a imagem |
| `severity: HIGH,CRITICAL` | Concentra o gate nas vulnerabilidades mais relevantes        |
| `exit-code: '1'`          | Transforma o resultado do scan em um gate                    |
| `ignore-unfixed: true`    | Ignora vulnerabilidades sem correção disponível              |
| `format: sarif`           | Permite integração com o Code Scanning do GitHub             |

Quando implementado com upload de SARIF, o job precisará de:

```yaml
permissions:
  contents: read
  security-events: write
```

> O Trivy também poderá identificar vulnerabilidades em componentes da imagem
> base, além das bibliotecas Python. Por isso, a etapa de container scanning
> complementará o `pip-audit`, em vez de substituí-lo.

---

## Reusable workflow: o DRY do YAML

Em vez de repetir os steps de teste, o job `test` delega a execução para um
workflow reutilizável:

```yaml
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.11', '3.12']
    uses: ./.github/workflows/_reusable-test.yml
    with:
      python-version: ${{ matrix.python-version }}
```

A divisão de responsabilidade é:

**Chamador:**

* define a matrix;
* define quais versões de Python serão testadas.

**Reusable workflow:**

* configura o ambiente;
* instala as dependências;
* executa os testes;
* executa os passos compartilhados do processo de validação.

Isso evita duplicação.

Trocar as versões testadas não exige modificar os steps internos do teste.
Da mesma forma, alterar os steps do teste não exige modificar a matrix.

### Cuidados com reusable workflows

Ao chamar um reusable workflow, o job chamador não possui `runs-on` nem `steps`.
A execução dos steps pertence ao workflow reutilizável.

Outro ponto importante é que os **nomes dos checks podem mudar** quando um workflow
é refatorado.

Isso pode afetar os required status checks configurados na branch protection.

Por isso, depois de alterar o nome ou a estrutura dos jobs:

1. execute o workflow pelo menos uma vez;
2. aguarde os novos checks aparecerem no GitHub;
3. confirme os nomes na branch protection;
4. marque os checks corretos como obrigatórios.

A convenção de iniciar o nome do reusable com `_` indica que ele é um workflow
de apoio, utilizado por outros workflows.

---

## Environment com required reviewer — roadmap

Um Environment é um objeto do repositório que pode agrupar:

* secrets;
* variables;
* required reviewers;
* wait timers;
* regras de branch.

A ideia para o CD é utilizar um environment chamado `staging`.

Um futuro job poderá ser semelhante a:

```yaml
deploy-staging:
  needs: test
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  environment:
    name: staging
```

Com um required reviewer configurado, o job ficará aguardando aprovação antes
de executar o passo protegido.

A aprovação ficará registrada no histórico de deployments do GitHub, fornecendo
rastreabilidade para a operação.

O `if:` restringe o deployment para pushes na `main`, evitando que cada Pull
Request tente executar um deploy.

> O Environment com required reviewer faz parte do **roadmap de CD** e não deve
> ser considerado um recurso já implementado no CI atual.

---

## Pinning de actions por SHA

Tags e branches de GitHub Actions são mutáveis.

Por exemplo:

```yaml
uses: actions/checkout@v4
```

não identifica diretamente um commit imutável.

Para aumentar a segurança da cadeia de CI, as actions utilizadas pelo pipeline
são fixadas por SHA.

Pins utilizados:

```yaml
- uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
- uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
- uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830 # v4.3.0
```

O SHA identifica um commit específico.

Assim, o workflow não passa a executar automaticamente uma versão diferente da
action apenas porque uma tag foi movida.

O comentário com a versão mantém o arquivo legível e facilita futuras
atualizações.

### Estratégia prática

* Actions de terceiros: preferencialmente pinadas por SHA.
* Actions oficiais do GitHub (`actions/*`): também podem ser pinadas por SHA,
  especialmente em etapas críticas.
* Dependabot ou Renovate podem ser utilizados para auxiliar na atualização dos
  pins.

> A manutenção dos pins deve considerar a evolução das versões das actions e dos
> runtimes utilizados pelo GitHub Actions.

---

## O exercício de shift-left

O `requirements.txt` utilizado no exercício começa limpo de propósito.

A vulnerabilidade é introduzida deliberadamente para demonstrar o funcionamento
do gate de segurança.

### 1. Quebrar

Em uma branch nova, rebaixe o `requests`:

```diff
- requests==2.33.0
+ requests==2.31.0
```

Depois, abra um Pull Request para `main`.

---

### 2. Observar

O `pip-audit` identifica vulnerabilidades relacionadas à versão vulnerável do
`requests`.

No exercício foram observadas as seguintes vulnerabilidades:

| Identificador   | Dependência | Versão vulnerável | Fix disponível |
| --------------- | ----------- | ----------------: | -------------: |
| PYSEC-2026-1873 | requests    |            2.31.0 |         2.32.0 |
| PYSEC-2026-1872 | requests    |            2.31.0 |         2.32.4 |
| PYSEC-2026-2275 | requests    |            2.31.0 |         2.33.0 |

**O PR #6** ficou com o merge **bloqueado** pela branch protection: os required
status checks `Test (Python 3.11)` e `Test (Python 3.12)` ficaram vermelhos por
causa do `pip-audit`.

Lint e testes unitários seguem independentes desse problema, permitindo
identificar que a falha estava relacionada à dependência vulnerável.

---

### 3. Corrigir

Na mesma branch, atualize novamente para a versão corrigida:

```diff
- requests==2.31.0
+ requests==2.33.0
```

Depois faça commit e push.

O CI será executado novamente.

Com a dependência corrigida, o `pip-audit` volta a passar e os required status
checks podem ficar verdes.

> A versão utilizada na correção do exercício é `2.33.0`. O objetivo é
> demonstrar que uma atualização precisa considerar todas as vulnerabilidades
> encontradas, e não apenas a primeira correção disponível.

O ponto central do exercício é que o problema foi detectado **no Pull Request,
antes do merge**, sem depender de uma execução manual da aplicação em produção.

Isso é **shift-left security** aplicado ao pipeline.

---

### Demonstração do gate de testes

Também é possível demonstrar o funcionamento do gate de testes alterando
deliberadamente uma asserção em `test_app.py`.

Quando a asserção falhar, o job `Test` ficará vermelho nas versões de Python
afetadas.

Com os required status checks ativos, o GitHub impede o merge enquanto o teste
não voltar a passar.

---

## Branch protection

A branch `main` possui regras de proteção configuradas em:

**Settings → Branches → Add branch protection rule**

As regras configuradas são:

1. **Require a pull request before merging**

   Impede que alterações sejam inseridas diretamente na `main`.

2. **Require approvals: 1**

   Exige pelo menos uma aprovação antes do merge.

3. **Dismiss stale pull request approvals when new commits are pushed**

   Uma nova alteração enviada ao Pull Request invalida a aprovação anterior,
   exigindo nova revisão quando aplicável.

4. **Require review from Code Owners**

   Ativa a exigência de revisão pelos responsáveis definidos no `CODEOWNERS`.

5. **Require status checks to pass before merging**

   Os checks do CI precisam estar verdes antes do merge.

   Checks obrigatórios configurados:

   * `Test (Python 3.11)`
   * `Test (Python 3.12)`

6. **Require branches to be up to date before merging**

   Exige que a branch do Pull Request esteja atualizada em relação à `main`
   antes do merge.

7. **Require conversation resolution before merging**

   Conversas de revisão precisam ser resolvidas.

8. **Do not allow bypassing the above settings**

   As regras também se aplicam a administradores/owners, evitando que a proteção
   seja simplesmente ignorada.

> Os status checks somente aparecem na lista de required checks depois que já
> executaram pelo menos uma vez. Caso a lista esteja vazia, abra um Pull Request,
> aguarde o CI executar e depois volte às configurações da branch protection.

### Validação

Foi realizado um Pull Request de teste (**PR #3**) com alteração no `README.md`.

Mesmo com os checks verdes, o GitHub bloqueou o merge enquanto a revisão
obrigatória não havia sido realizada.

Também foi possível observar o bloqueio enquanto os checks obrigatórios estavam
em execução.

Após a revisão necessária e a conclusão dos checks, o merge foi liberado.

Esse teste valida empiricamente que a branch protection está funcionando como
**quality gate**, e não apenas registrada como configuração.

---

## Rodando os gates localmente

Os mesmos comandos utilizados pelo CI podem ser executados localmente:

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements-dev.txt

ruff check .
pytest -q
pip-audit -r requirements.txt
```

No Windows PowerShell, a ativação pode ser feita com:

```powershell
.venv\Scripts\Activate.ps1
```

Executar os gates localmente antes de abrir um Pull Request reduz o tempo de
feedback.

A ideia é manter o mesmo processo:

**desenvolvimento → validação local → Pull Request → CI → review → merge**

---

## Notificações — roadmap

Notificações por webhook ainda **não estão implementadas no CI atual**.

A ideia para o CD é permitir que uma falha relevante seja comunicada
automaticamente ao time.

O futuro job de notificação deverá utilizar:

```yaml
if: always()
```

Isso é importante porque a notificação precisa ser executada mesmo quando um job
anterior falhar.

O job poderá consultar resultados como:

```text
needs.<job>.result
```

e montar uma mensagem contendo:

* status do pipeline;
* job que falhou;
* branch;
* commit;
* Pull Request, quando aplicável;
* link direto para o run do GitHub Actions.

O link do run é especialmente importante porque permite que quem recebe a
notificação vá diretamente para os logs.

> Notificar o suficiente para acionar uma ação, mas não a ponto de gerar ruído
> que faça o time ignorar os alertas.

---

## Publicação da imagem no Docker Hub — roadmap

A publicação automática da imagem Docker ainda **não faz parte do CI atual**.

Ela será implementada na etapa de CD.

A ideia é que o job de publicação seja executado somente depois que os quality
gates forem aprovados.

O desenho planejado será semelhante a:

```yaml
needs:
  - lint
  - test
  - dependency-audit
  - container-scan
  - sast
```

O `build`/`push` somente deverá ocorrer depois que todos os gates necessários
estiverem verdes.

Dessa forma:

> Nunca publicar uma imagem que não passou pelos controles de qualidade e
> segurança definidos pelo pipeline.

### Regras de tag planejadas

| Evento                   | Tag principal | Exemplo  |
| ------------------------ | ------------- | -------- |
| Pull Request para `main` | `PR-<número>` | `PR-42`  |
| Push na `main`           | `latest`      | `latest` |
| Criação de tag           | Tag exata     | `v1.2.0` |

Além da tag principal, cada imagem deverá receber uma segunda tag contendo o hash
curto do commit:

```text
${GITHUB_SHA::7}
```

Isso fornece rastreabilidade entre a imagem e o commit que a originou.

Por exemplo:

```text
latest
a1b2c3d
```

permite identificar tanto a finalidade da imagem quanto o commit exato associado
ao build.

> A publicação no Docker Hub, as regras de tag e o scan da imagem são
> **roadmap de CD**, não funcionalidades do CI atualmente implementado.

---

## Rodapé com informações da imagem — roadmap

Uma evolução planejada é passar as tags da imagem para a aplicação através de
um build argument:

```text
IMAGE_TAGS
```

A aplicação poderá então exibir no rodapé a versão/build atualmente em execução.

O objetivo é conectar:

> **o que o pipeline construiu**

com:

> **o que o usuário está utilizando**

Dessa forma, diante de uma aplicação em execução, será possível identificar
rapidamente qual build está sendo utilizado.

Essa funcionalidade permanece como parte do roadmap de containerização/CD.

---

## Secrets e variables

Os secrets e variables utilizados pelo CI/CD são cadastrados em:

**Settings → Secrets and variables → Actions**

Os valores sensíveis não devem ser armazenados diretamente no repositório.

### Secrets planejados para CI/CD

| Nome                 | Tipo                  | Para quê                                               |
| -------------------- | --------------------- | ------------------------------------------------------ |
| `DOCKERHUB_USERNAME` | Secret                | Usuário/organização do Docker Hub                      |
| `DOCKERHUB_TOKEN`    | Secret                | Access token utilizado para autenticação no Docker Hub |
| `NOTIFY_WEBHOOK_URL` | Secret                | Webhook para notificações do pipeline                  |
| `STAGING_URL`        | Secret de Environment | URL utilizada pelo ambiente `staging`                  |

Os secrets relacionados ao canal de deploy, como:

```text
EC2_*
KIND_CLUSTER
```

ficam documentados no `cd-pipeline.md`.

### Docker Hub token

Quando o Docker Hub for integrado ao CD, deverá ser utilizado um **Personal
Access Token**, e não a senha da conta.

O token deve possuir apenas as permissões necessárias para a operação.

Um token pode ser revogado individualmente caso seja comprometido, reduzindo o
impacto em comparação com a exposição da senha da conta.

### Webhooks

Webhooks de Slack/Discord funcionam como credenciais.

Quem possuir a URL poderá utilizá-la para publicar mensagens no canal associado.

Por isso:

* nunca commite o valor do webhook;
* nunca coloque o valor real em comentários;
* nunca coloque o valor real em arquivos de exemplo;
* não exponha secrets nos logs.

Mesmo depois que um secret é removido de um arquivo, ele pode continuar presente
no histórico do Git.

---

## Relação com o CD

O CI é responsável por validar o código e, futuramente, participar da construção
do artefato.

O CD será responsável por levar uma imagem publicada para o ambiente de execução.

O fluxo planejado é:

```text
Pull Request
     │
     ▼
   CI
     │
     ├── Lint
     ├── Test
     └── Dependency Audit
             │
             ▼
       Branch Protection
             │
             ▼
           Merge
             │
             ▼
            CD
             │
             ├── Build
             ├── Trivy
             ├── Docker Hub
             └── Deploy
```

Atualmente, o fluxo entre CI e CD permanece **manual**: o CD utiliza uma tag de
imagem escolhida para realizar o deployment.

Uma integração automática utilizando:

```yaml
on:
  workflow_run:
```

fica como evolução futura.

---

## Roadmap

As funcionalidades abaixo não devem ser confundidas com partes já
implementadas do CI:

| Funcionalidade                              | Status         |
| ------------------------------------------- | -------------- |
| Lint com `ruff`                             | ✅ Implementado |
| Testes com `pytest`                         | ✅ Implementado |
| Matrix Python 3.11/3.12                     | ✅ Implementado |
| Cache de pip                                | ✅ Implementado |
| `pip-audit`                                 | ✅ Implementado |
| Reusable workflow                           | ✅ Implementado |
| Pinning das actions por SHA                 | ✅ Implementado |
| Branch protection                           | ✅ Configurada  |
| Code Owners                                 | ✅ Configurado  |
| Trivy                                       | ⏳ Roadmap      |
| SAST adicional                              | ⏳ Roadmap      |
| Environment `staging` com required reviewer | ⏳ Roadmap      |
| Notificações por webhook                    | ⏳ Roadmap      |
| Build da imagem                             | ⏳ Roadmap      |
| Push para Docker Hub                        | ⏳ Roadmap      |
| Tags automáticas                            | ⏳ Roadmap      |
| Rodapé com versão/build                     | ⏳ Roadmap      |
| Deploy automático                           | ⏳ Roadmap      |
| Integração automática CI → CD               | ⏳ Roadmap      |

---

## Conclusão

O CI atual implementa os principais quality gates necessários para impedir que
código com problemas conhecidos seja incorporado à `main`.

O fluxo atual é:

```text
Pull Request
     ↓
Lint
     ↓
Test — Python 3.11
     ↓
Test — Python 3.12
     ↓
Dependency Audit
     ↓
Branch Protection
     ↓
Code Review
     ↓
Merge
```

A branch protection transforma os resultados do CI em regras efetivas de merge.

O exercício de shift-left demonstra que uma dependência vulnerável pode ser
detectada ainda no Pull Request e impedir sua entrada na branch principal.

As funcionalidades de container scanning, publicação, notificações,
environment protegido e deployment permanecem como etapas futuras do CD.

Assim, o CI atual funciona como a primeira camada de qualidade e segurança do
processo de entrega contínua.
