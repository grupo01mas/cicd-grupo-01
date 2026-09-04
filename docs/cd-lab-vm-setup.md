# Configuração da VM de deploy (EC2 + kind) — Lab de CD

Guia passo a passo para preparar o **alvo de deploy** do lab de CD: uma EC2 no
AWS Academy Learner Lab rodando um cluster `kind`, alcançável pelo GitHub Actions
via SSH.

Todo o provisionamento é feito pelo **Console da AWS** e o acesso à máquina é pelo
**terminal do próprio Console** (EC2 Instance Connect). Não é preciso `aws-cli`
nem cliente SSH no seu computador.

Ao final, o workflow `.github/workflows/validate-ssh.yml` conecta na EC2, seleciona
o contexto do cluster `kind` e lista os namespaces — provando que o canal
GitHub → EC2 → Kubernetes funciona ponta a ponta. Esse workflow **já vem pronto** no
starter-kit: não é preciso alterar nada nele, só cadastrar os secrets da Seção 7.

> Este é o primeiro passo do CD. Ainda **não** fazemos deploy da app; só validamos
> o canal. O deploy do manifesto `k8s/todolist.yaml` vem em seguida, e está
> descrito em [cd-pipeline.md](cd-pipeline.md).

---

## Pré-requisitos

- Navegador com acesso ao **AWS Academy Learner Lab** (crédito ativo)
- Acesso ao repositório no GitHub (para cadastrar os secrets)

---

## 1. Abrir a sessão do Learner Lab

1. Portal do AWS Academy → **Modules → Learner Lab → Start Lab**
2. Aguardar o ícone ficar **verde** (~30–60s)
3. Clicar em **AWS** (no topo) para abrir o Console da AWS já autenticado

> A sessão do Learner Lab expira em ~4h. Se o Console parar de responder, volte ao
> portal e clique em **Start Lab** de novo.

---

## 2. Lançar a EC2 pelo Console

No Console da AWS, ir em **EC2 → Instances → Launch instances** e preencher:

- **Name**: `cicd-lab`
- **Application and OS Images (AMI)**: **Amazon Linux 2023** (x86_64)
- **Instance type**: `t3.small`
- **Key pair (login)**: **Proceed without a key pair (Not recommended)** — vamos
  entrar pelo EC2 Instance Connect e gerar nossa própria chave dentro da VM
- **Network settings** → **Edit** → em **Firewall (security groups)**, criar um
  novo security group e adicionar as regras de entrada:

  | Type | Protocol | Port | Source | Para quê |
  |---|---|---|---|---|
  | SSH | TCP | 22 | `Anywhere 0.0.0.0/0` | EC2 Instance Connect / SSH do Actions |
  | HTTP | TCP | 80 | `Anywhere 0.0.0.0/0` | Ingress (nginx) — todas as apps entram por aqui |
  | Custom TCP | TCP | 6443 | `Anywhere 0.0.0.0/0` | API do Kubernetes (OpenLens/Freelens) |

  > A porta **6443** é o endpoint de administração do cluster. Deixá-la aberta
  > para `0.0.0.0/0` **não é seguro** (qualquer um com o kubeconfig alcança a
  > API) — em produção, restrinja à sua faixa de IP. Para o lab, assumimos esse
  > tradeoff para simplificar.

  > **Uma porta só de entrada (80):** o roteamento das apps é feito pelo
  > ingress-nginx com base no host, então não precisamos abrir uma porta por app.
  > Adicionar uma nova app vira um `Ingress` novo, sem tocar no security group nem
  > recriar o cluster — é o padrão de produção.

- **(Opcional) Advanced details → IAM instance profile**: `LabInstanceProfile`
  (não é necessário para validar o canal, mas fica pronto para os próximos passos)

Clicar em **Launch instance** e aguardar o estado virar **Running**.

> **Trava didática:** SSH, HTTP e a API do Kubernetes abertos para `0.0.0.0/0`.
> Não é como se faz em produção; assumimos para simplificar o lab.

Anotar o **Public IPv4 address** da instância (em **EC2 → Instances**, coluna
Public IPv4 address) — ele vira o secret `EC2_HOST`.

---

## 3. Conectar via EC2 Instance Connect

Ainda no Console:

1. **EC2 → Instances** → selecionar a `cicd-lab`
2. Botão **Connect** (topo)
3. Aba **EC2 Instance Connect** → usuário `ec2-user` → **Connect**

Abre um terminal no navegador, logado como `ec2-user`. Todos os comandos das
próximas seções rodam **dentro desse terminal**.

---

## 4. Gerar a chave SSH dentro da VM

O GitHub Actions precisa de uma chave para entrar na EC2. Geramos o par **dentro
da própria VM**: a pública autoriza o acesso, a privada vira o secret do GitHub.

```bash
# Gerar o par de chaves (sem passphrase — o Actions usa sem interação)
ssh-keygen -t ed25519 -C "cicd-course" -f ~/.ssh/cicd-lab -N ""

# Autorizar a chave pública a entrar nesta mesma VM
cat ~/.ssh/cicd-lab.pub >> ~/.ssh/authorized_keys

# Imprimir a chave PRIVADA para copiar (vira o secret EC2_SSH_KEY)
cat ~/.ssh/cicd-lab
```

Copie **todo** o conteúdo impresso da chave privada, incluindo as linhas
`-----BEGIN OPENSSH PRIVATE KEY-----` e `-----END OPENSSH PRIVATE KEY-----`.

> A chave é gerada e fica na VM. A privada só sai daqui para virar o secret no
> GitHub; nunca a compartilhe por outro canal.

---

## 5. Instalar Docker, kind e kubectl

Ainda no terminal do Console:

```bash
# Docker
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

# kind
sudo curl -Lo /usr/local/bin/kind https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-amd64
sudo chmod +x /usr/local/bin/kind

# kubectl
sudo curl -Lo /usr/local/bin/kubectl \
  "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo chmod +x /usr/local/bin/kubectl
```

Para o grupo `docker` valer sem `sudo`, recarregue a sessão do shell:

```bash
newgrp docker
```

---

## 6. Criar o cluster kind

Criar o arquivo de config. O bloco `networking` expõe a **API do Kubernetes** (6443)
em todas as interfaces da EC2; o `node-labels: ingress-ready=true` e o
`extraPortMappings` de **80/443** preparam o nó para receber o ingress-nginx (é a
**única** porta de entrada das apps):

```bash
cat > kind-config.yaml <<'YAML'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  apiServerAddress: "0.0.0.0"
  apiServerPort: 6443
nodes:
  - role: control-plane
    kubeadmConfigPatches:
      - |
        kind: InitConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "ingress-ready=true"
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
YAML

kind create cluster --name devops-labs --config kind-config.yaml
kubectl get nodes
kubectl get namespaces
```

Instalar o **ingress-nginx** (manifesto oficial do provider kind) e esperar ficar pronto:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml

kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

> **Já tinha um cluster e mudou as portas do nó?** O kind **não** atualiza
> `extraPortMappings` de um cluster existente (elas viram publicação de portas do
> container do nó, fixadas na criação). Para aplicar as portas do ingress (80/443),
> recrie o cluster **uma vez**:
>
> ```bash
> kind delete cluster --name devops-labs
> kind create cluster --name devops-labs --config kind-config.yaml
> # reinstalar o ingress-nginx (comando acima)
> ```
>
> Recriar **zera** o cluster (re-rode as pipelines; a de blue/green re-aplica o
> bootstrap sozinha) e **regenera o certificado da API** (refaça o kubeconfig do
> OpenLens na Seção 10). Depois do ingress instalado, **adicionar apps/rotas nunca
> mais exige recriar** — é só aplicar um `Ingress`.

O nome do cluster (`devops-labs`) define o contexto `kind-devops-labs`, que é o
que o workflow de validação seleciona. Se usar outro nome, ajuste a variable
`KIND_CLUSTER` no GitHub (Seção 7).

---

## 7. Cadastrar os secrets no GitHub

Em **Settings → Secrets and variables → Actions**.

Secrets (**New repository secret**):

| Nome | Valor |
|---|---|
| `EC2_SSH_KEY` | conteúdo completo da chave privada impresso na Seção 4 (com as linhas `BEGIN`/`END`) |
| `EC2_HOST` | Public IPv4 address da EC2 (anotado na Seção 2) |
| `EC2_USER` | `ec2-user` |

Variable (**Variables → New repository variable**), opcional:

| Nome | Valor | Default se ausente |
|---|---|---|
| `KIND_CLUSTER` | nome do cluster kind (ex.: `devops-labs`) | `devops-labs` |

> **`EC2_HOST` muda toda vez que a EC2 é recriada ou parada/reiniciada.** Sempre
> reconferir antes de rodar o workflow.

> Os secrets do Docker Hub e das notificações estão em
> [ci-pipeline.md](ci-pipeline.md); os do deploy, em [cd-pipeline.md](cd-pipeline.md).

---

## 8. Validar o canal pelo GitHub Actions

O workflow `validate-ssh.yml` conecta na EC2, seleciona o contexto do kind e
lista os namespaces.

Pela UI: **Actions → Validate SSH to EC2 → Run workflow**.

No log você deve ver a saída de `kubectl get namespaces` (`default`,
`kube-system`, `kube-public`, `kube-node-lease`). Isso prova que o GitHub Actions
alcança o cluster.

### Debug comum

- **`Permission denied (publickey)`** — secret `EC2_SSH_KEY` incompleto, ou a
  pública não foi para `authorized_keys`. Sanity dentro da VM:
  `ssh-keygen -y -f ~/.ssh/cicd-lab`.
- **`Connection timed out`** — IP mudou (atualize `EC2_HOST`), ou o SG não libera
  a porta 22.
- **`error: no context exists with the name`** — o nome do cluster kind não bate
  com a variable `KIND_CLUSTER`.

---

## 9. Aplicar o manifesto da app (próximo passo)

Com o canal validado, o deploy simples é aplicar `k8s/todolist.yaml` no cluster.
Antes, troque `SEU_USUARIO_DOCKERHUB` na linha `image:` do manifesto pelo seu
usuário do Docker Hub.

Como o repositório é **privado**, não dá para baixar o manifesto por `curl` direto.
No terminal do Console (dentro da VM), cole o conteúdo de `k8s/todolist.yaml` (do
seu editor ou da página do arquivo no GitHub) dentro de um heredoc e aplique:

```bash
cat > todolist.yaml <<'YAML'
# --- cole aqui o conteúdo de k8s/todolist.yaml ---
YAML

kubectl apply -f todolist.yaml

# validar via ingress (host-based); a app entra pela porta 80 do ingress-nginx
curl -fsS -H "Host: todolist.local" http://localhost/healthz
```

> Este apply manual é só para provar o cluster. Em seguida, o deploy passa a ser
> feito pelo pipeline (`scp` do manifesto via SSH a partir do runner): o runner já
> tem o repositório em checkout, então não precisa clonar nada na VM nem tornar o
> repo público.

Do seu computador, mapeie os hosts do lab para o IP público (uma vez) e acesse pelo
navegador ou `curl`:

```bash
# no seu /etc/hosts (troque pelo Public IPv4 da EC2)
<PUBLIC_IP> todolist.local todolist-bg.local blue.todolist-bg.local green.todolist-bg.local
```

```bash
curl -fsS http://todolist.local/healthz
```

---

## 10. Conectar o OpenLens / Freelens ao cluster

OpenLens e Freelens são a mesma coisa para este fim (forks do Lens); os passos
valem para os dois. A ideia é usar o kubeconfig do kind apontando para o **IP
público** da EC2 na porta **6443**.

### Gerar o kubeconfig na VM

No terminal do Console (dentro da VM), reescrever o endereço do servidor para o IP
público e relaxar a verificação de TLS:

```bash
# use o Public IPv4 anotado na Seção 2
export PUBLIC_IP=<seu_ip_publico>

kind get kubeconfig --name devops-labs \
  | sed "s#https://0.0.0.0:6443#https://${PUBLIC_IP}:6443#" \
  | sed "s#    certificate-authority-data:.*#    insecure-skip-tls-verify: true#" \
  > kubeconfig-devops-labs.yaml

cat kubeconfig-devops-labs.yaml
```

Copiar **todo** o conteúdo impresso.

> **Por que `insecure-skip-tls-verify`?** O certificado da API do kind não inclui
> o IP público da EC2 nos SANs, então a verificação de TLS falharia. Para o lab,
> pulamos essa verificação. Em produção, adicione o IP/hostname aos `certSANs` do
> cluster em vez de desabilitar o TLS.

### Adicionar o cluster no OpenLens / Freelens

1. Salvar o conteúdo copiado num arquivo local, ex.: `~/kubeconfig-devops-labs.yaml`
2. Abrir o OpenLens/Freelens → **Catalog** → botão **+** (canto inferior direito)
   → **Add from kubeconfig**
3. Colar o conteúdo (ou apontar para o arquivo) → **Add clusters**
4. Clicar no cluster para conectar

Você deve ver os **nodes**, os **namespaces** e, após a Seção 9, os **pods** do
namespace `todolist`.

> **O IP muda ao parar/reiniciar a EC2.** Quando isso acontecer, regenere o
> kubeconfig com o novo IP e re-adicione o cluster (ou edite o `server:` nas
> configurações do cluster no OpenLens).

---

## 11. Teardown (higiene do lab)

Pelo Console, em **EC2 → Instances**, selecionar a `cicd-lab` →
**Instance state**:

- **Stop instance** — preserva o disco e o cluster kind para a próxima aula
- **Terminate instance** — apaga tudo (só no fim do curso)

> Ao parar/reiniciar, o **Public IPv4 address muda** — atualize o secret
> `EC2_HOST` antes de rodar o workflow de novo.
