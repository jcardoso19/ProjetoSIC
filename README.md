## Autores e Contribuição

| Número | Nome | Contribuição | Foco Principal |
| :--- | :--- | :---: | :--- |
| **120440** | **João Cardoso** | **33%** | **Camada de Rede, Topologia e Heartbeats** |
| **XXXXXX** | **Rafael Marques** | **33%** | **xxxxxxxxxxxxxxx** |
| **XXXXXX** | **Tiago Vieira** | **33%** | **xxxxxxxxxxxxxxxx** |

---

### Camada de Rede & Gestão de Topologia (João Cardoso)
Esta componente implementa a infraestrutura fundamental da rede Ad-Hoc sobre Bluetooth BLE, operando numa arquitetura híbrida de Cliente/Servidor (node_main.py, common/advertiser.py). A topologia em árvore é construída dinamicamente seguindo a estratégia "Lazy" exigida: os nós realizam scan do ambiente (common/scan.py), identificam vizinhos válidos e conectam-se automaticamente ao Uplink com menor contagem de saltos (hop count) até ao Sink (common/manageConnections.py). A vivacidade da rede (Network Liveness) é assegurada por um protocolo de Heartbeat; o sistema monitoriza a chegada de pacotes de controlo (node/heartbeat_manager.py) e, após 3 falhas consecutivas, declara o Uplink como morto, forçando o corte da conexão e o reinício imediato do processo de descoberta para recuperação da rede (node_main.py).