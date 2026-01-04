# Projeto SIC: Rede Ad Hoc Segura IoT sobre Bluetooth

## 👥 Autores e Contribuição

| Nome do Aluno | Número Mec. | Contribuição (%) |
| :--- | :---: | :---: |
| **João Cardoso** | [120440] | 33% |
| **Rafael Marques** | [119927] | 33% |
| **Tiago Vieira** | [119655] | 33% |

---

## 📖 Visão Geral do Projeto

Este projeto implementa uma rede **Ad Hoc (Mesh) segura** para dispositivos IoT utilizando a tecnologia **Bluetooth Low Energy (BLE)**. O sistema é composto por um nó central (**Sink**) e múltiplos nós (**Nodes**).

A rede permite que nós fora do alcance direto do Sink comuniquem através de nós intermédios (*multi-hop*), garantindo autenticidade, confidencialidade e integridade dos dados em duas camadas distintas: **Link-Layer** (salto-a-salto) e **End-to-End** (aplicação-para-sink).

---

## 🏗️ Arquitetura e Design (Gestão da Rede)

O sistema foi desenhado de forma modular, de modo a separar a lógica de comunicação Bluetooth da lógica de encaminhamento e de segurança.

### 1. Descoberta e Ligação
* **Service Discovery:** Utilizamos um **UUID específico** (`A074...`) anunciado pelo Sink. Os nós realizam *scan* passivo e ligam-se apenas a dispositivos que anunciem este serviço.
* **Justificação:** A utilização de UUID em vez de endereços MAC fixos permite a substituição de hardware sem recompilação do código e garante que os nós não se ligam a dispositivos Bluetooth não autorizados.

### 2. Encaminhamento (Routing)
* **Forwarding Table:** Cada nó mantém uma tabela de encaminhamento (`forwarding_table`) que mapeia o ID do destino (NID) para a ligação Bluetooth direta (*next hop*).
* **Heartbeats:** O Sink envia periodicamente mensagens de *heartbeat* em *broadcast*.
* **Propagação:** Quando um nó recebe um *heartbeat*, atualiza a sua rota para o Sink e propaga a mensagem para os seus vizinhos.
* **Deteção de Falhas:** Se um nó deixar de receber *heartbeats* durante um período definido (por exemplo, 15 s), assume que a rota para o Sink foi perdida (“SINK LOST”) e tenta reconectar-se.

### 3. Interface Bluetooth (BlueZ/DBus)
* É utilizada a API `dbus` para comunicar diretamente com a *stack* BlueZ do Linux.
* **GATT Server/Client:** A comunicação baseia-se em características GATT para escrita e leitura de pacotes fragmentados (*chunk size* = 100 bytes, para compatibilidade BLE).

---

## 🔒 Implementação de Segurança (Funcionalidades de Segurança)

A segurança foi o foco principal do projeto, tendo sido implementado um modelo de defesa em profundidade.

### 1. Segurança Link-Layer (Hop-by-Hop)
Todas as ligações diretas entre nós vizinhos são protegidas após um *handshake* inicial.

* **Protocolo:** Station-to-Station (baseado em curvas elípticas).
* **Autenticação:** Certificados X.509. Cada nó possui um par de chaves e um certificado assinado por uma Root CA de confiança.
* **Troca de Chaves:** ECDH (*Elliptic Curve Diffie-Hellman*) para derivação de uma chave de sessão única por ligação.
* **Criptografia:** AES-GCM (*Galois/Counter Mode*).
* **Justificação:** O AES-GCM foi escolhido por ser um algoritmo de *Authenticated Encryption* (AEAD), garantindo confidencialidade e integridade numa única operação, sendo simultaneamente eficiente para dispositivos IoT.

### 2. Autenticação do Sink (*Heartbeats* Assinados)
Para prevenir ataques de *spoofing*, nos quais um nó malicioso se faz passar pelo Sink:

* **Assinatura Digital:** O Sink assina o *payload* (número de sequência) do *heartbeat* utilizando a sua chave privada (ECDSA).
* **Verificação:** Os nós validam a assinatura recorrendo à chave pública do Sink (extraída do certificado) antes de propagarem a mensagem.
* **Prevenção de Replay:** A utilização de números de sequência (`seq_num`) crescentes impede a retransmissão maliciosa de *heartbeats* antigos.

### 3. Segurança End-to-End (DTLS Simplificado)
Mesmo que um nó intermédio seja comprometido, as mensagens da aplicação permanecem protegidas.

* **Túnel E2E:** Foi implementada a classe `DTLSManager`, responsável por criar um canal seguro direto entre a aplicação do nó e o Sink.
* **Isolamento:** Os nós intermédios (“routers”) limitam-se a encaminhar os pacotes cifrados, não tendo acesso ao seu conteúdo.

---

## ✅ Estado da Implementação

### Funcionalidades Implementadas (100%)
- [x] **Descoberta Automática:** *Scan* e ligação baseados em UUID.
- [x] **Rede Mesh:** Encaminhamento de pacotes *multi-hop*.
- [x] **Fragmentação:** Suporte para envio de mensagens com tamanho superior ao MTU do BLE.
- [x] **Handshake Seguro:** Troca de certificados e validação da *chain of trust*.
- [x] **Criptografia AES-GCM:** Proteção de todos os pacotes de dados.
- [x] **Heartbeats Assinados:** Garante que apenas o Sink legítimo controla a rede.
- [x] **Blacklist de MACs:** Funcionalidade adicional no Sink para bloqueio de nós específicos via CLI (`block <MAC>`).
- [x] **Interface CLI:** Menus interativos com *feedback* visual do estado da ligação e da segurança.

### Funcionalidades Não Implementadas / Limitações
- [ ] **Rotação Automática de Chaves:** As chaves de sessão mantêm-se válidas enquanto a ligação Bluetooth estiver ativa. Uma rotação periódica (*re-keying*) aumentaria o nível de segurança.
- [ ] **Persistência:** A tabela de encaminhamento é perdida aquando do reinício de um nó (comportamento esperado em redes Ad Hoc dinâmicas).

---
