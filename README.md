## Autores e Contribuição

| Número | Nome | Contribuição | Foco Principal |
| :--- | :--- | :---: | :--- |
| **120440** | **João Cardoso** | **33%** | **Camada de Rede, Topologia e Heartbeats** |
| **XXXXXX** | **Rafael Marques** | **33%** | **xxxxxxxxxxxxxxx** |
| **XXXXXX** | **Tiago Vieira** | **33%** | **xxxxxxxxxxxxxxxx** |

---

### Camada de Rede & Gestão de Topologia (João Cardoso)
Esta componente implementa a infraestrutura fundamental da rede Ad-Hoc sobre Bluetooth BLE, operando numa arquitetura híbrida de Cliente/Servidor (node_main.py, common/advertiser.py). A topologia em árvore é construída dinamicamente seguindo a estratégia "Lazy" exigida: os nós realizam scan do ambiente (common/scan.py), identificam vizinhos válidos e conectam-se automaticamente ao Uplink com menor contagem de saltos (hop count) até ao Sink (common/manageConnections.py). A vivacidade da rede (Network Liveness) é assegurada por um protocolo de Heartbeat; o sistema monitoriza a chegada de pacotes de controlo (node/heartbeat_manager.py) e, após 3 falhas consecutivas, declara o Uplink como morto, forçando o corte da conexão e o reinício imediato do processo de descoberta para recuperação da rede (node_main.py).

### Infraestrutura de Segurança & Comunicação bidirecional (Rafael Marques)
Esta componente estabelece a camada de confiança e o transporte de dados bidirecional da rede. A segurança baseia-se numa Infraestrutura de Chaves Públicas (PKI) customizada (support/pkiGenerator.py): optou-se por Criptografia de Curva Elíptica (ECC P-521) para garantir segurança elevada com chaves compactas, adequadas ao MTU reduzido do Bluetooth Low Energy. A autenticação dos nós segue um modelo de Handshake pós-conexão; o ConnectionManager inicia a troca de certificados X.509 através de pacotes de controlo HELLO (common/manageConnections.py), permitindo a validação mútua antes da aceitação de tráfego de dados. Para viabilizar a comunicação Downlink (do Sink para os Nós) em ambiente Linux, foi desenvolvida uma abstração de Servidor GATT baseada em DBus (common/gatt_server.py), que ultrapassa as limitações das bibliotecas padrão ao implementar o mecanismo de Notificações (PropertiesChanged) para o envio assíncrono de respostas e comandos de controlo (sync/sync_main.py).
