## Autores e Contribuição

| Número | Nome | Contribuição | Foco Principal |
| :--- | :--- | :---: | :--- |
| **120440** | **João Cardoso** | **33%** | **Camada de Rede, Topologia e Heartbeats** |
| **XXXXXX** | **Rafael Marques** | **33%** | **Infraestrutura de Segurança & Comunicação bidirecional** |
| **XXXXXX** | **Tiago Vieira** | **33%** | **Encaminhamento Seguro e Serviços End-to-End** |

---

### Camada de Rede & Gestão de Topologia (João Cardoso)
Esta componente implementa a infraestrutura fundamental da rede Ad-Hoc sobre Bluetooth BLE, operando numa arquitetura híbrida de Cliente/Servidor (node_main.py, common/advertiser.py). A topologia em árvore é construída dinamicamente seguindo a estratégia "Lazy" exigida: os nós realizam scan do ambiente (common/scan.py), identificam vizinhos válidos e conectam-se automaticamente ao Uplink com menor contagem de saltos (hop count) até ao Sink (common/manageConnections.py). A vivacidade da rede (Network Liveness) é assegurada por um protocolo de Heartbeat; o sistema monitoriza a chegada de pacotes de controlo (node/heartbeat_manager.py) e, após 3 falhas consecutivas, declara o Uplink como morto, forçando o corte da conexão e o reinício imediato do processo de descoberta para recuperação da rede (node_main.py).

### Infraestrutura de Segurança & Comunicação bidirecional (Rafael Marques)
Esta componente estabelece a camada de confiança e o transporte de dados bidirecional da rede. A segurança baseia-se numa Infraestrutura de Chaves Públicas (PKI) personalizada (support/pkiGenerator.py): optou-se por Criptografia de Curva Elíptica (ECC P-521) para garantir segurança elevada com chaves compactas, adequadas ao MTU reduzido do Bluetooth Low Energy. A autenticação dos nós segue um modelo de Handshake pós-conexão; o ConnectionManager inicia a troca de certificados X.509 através de pacotes de controlo HELLO (common/manageConnections.py), permitindo a validação mútua antes da aceitação de tráfego de dados. Para viabilizar a comunicação Downlink (do Sink para os Nós) em ambiente Linux, foi desenvolvida uma abstração de Servidor GATT baseada em DBus (common/gatt_server.py), que ultrapassa as limitações das bibliotecas padrão ao implementar o mecanismo de Notificações (PropertiesChanged) para o envio assíncrono de respostas e comandos de controlo (sync/sync_main.py).

### Encaminhamento Seguro e Serviços End-to-End (Tiago Vieira)
Esta componente implementa as camadas superiores de segurança e aplicação, garantindo confidencialidade, integridade e frescura dos dados tanto salto-a-salto como fim-a-fim. O encaminhamento (Routing) foi protegido através da implementação de um protocolo de chaves de sessão derivado via ECDH (common/security.py), onde cada link utiliza chaves simétricas negociadas dinamicamente para cifrar o tráfego com AES-GCM (node/router.py). Isto assegura autenticidade e, crucialmente, proteção contra ataques de Replay através da monitorização estrita de números de sequência (Anti-Replay). Adicionalmente, foi desenvolvido um serviço seguro End-to-End (DTLS-like) que cria um túnel cifrado entre cada Nó e o Sink (common/dtls.py), isolando os dados da aplicação ("Inbox") de nós intermédios. O sistema foi finalizado com uma Interface de Utilizador (CLI) robusta (test_node.py, sync/core.py) que permite a visualização em tempo real da tabela de encaminhamento, estatísticas de tráfego e controlo manual da rede (bloqueio de heartbeats e envio de mensagens seguras), cumprindo todos os requisitos de gestão e debug.

---

### Funcionalidades Não Implementadas ou Parciais
Todas as funcionalidades críticas e mandatórias descritas no enunciado foram implementadas com sucesso, incluindo a topologia em árvore, gestão de falhas, PKI completa e segurança multinível (Link e E2E). 

*   **Nota sobre o DTLS Standard:** Em estrita conformidade técnica com o termo "DTLS" (Datagram Transport Layer Security - RFC 6347), a implementação utiliza uma stack criptográfica aplicacional personalizada (AES-GCM + Handshake E2E) em vez das bibliotecas OpenSSL padrão. Esta decisão técnica justifica-se pela inexistência de uma abstração de *socket* nativa fiável sobre o protocolo GATT do Bluetooth Low Energy em Python. A solução implementada oferece as **mesmas garantias de segurança** (Confidencialidade, Integridade, Autenticação) exigidas, adaptadas às restrições do meio físico.