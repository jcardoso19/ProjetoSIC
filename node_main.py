import asyncio
import time
import threading
import os
from cryptography.hazmat.primitives import serialization

from common.manageConnections import ConnectionManager
from common.advertiser import NodeAdvertiser
from node.router import Router
from node.heartbeat_manager import HeartbeatManager

# CONFIGURACAO DE IDENTIDADE
# Nota: O nome deve corresponder ao ficheiro gerado pelo pkiGenerator (ex: node1, node2)
NODE_FILE_NAME = "node1" 
MY_NID  = "NID_NODE_01"
MY_ADVERTISER_NAME = "SIC_NODE_01" # Nome visivel no Bluetooth Scan

class NodeMain:
    def __init__(self):
        # 1. CARREGAR CERTIFICADOS
        # Tenta carregar da pasta 'certs' ou 'support/certs'
        cert_path = f"support/certs/{NODE_FILE_NAME}.crt"
        key_path  = f"support/certs/{NODE_FILE_NAME}.key"
        
        # Fallback se a pasta for diferente (caso estejas a correr da raiz)
        if not os.path.exists(cert_path):
            cert_path = f"certs/{NODE_FILE_NAME}.crt"
            key_path  = f"certs/{NODE_FILE_NAME}.key"

        try:
            print(f"[INIT] A carregar identidade de: {cert_path}")
            with open(cert_path, "rb") as f:
                my_cert_bytes = f.read()
            
            with open(key_path, "rb") as f:
                my_private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )
            # Inicializa com chaves para permitir o Handshake
            self.manager = ConnectionManager(my_cert_bytes, my_private_key)
            
        except Exception as e:
            print(f"[ERRO] Nao foi possivel carregar certificados: {e}")
            print("[WARN] A iniciar em modo INSEGURO (sem handshake possivel)")
            self.manager = ConnectionManager() # Modo fallback sem chaves

        self.router = Router(MY_NID, self.manager)
        
        # 2. LIGAR O ROUTER AO MANAGER
        # Isto e CRITICO: Quando o Manager recebe bytes do Uplink, passa-os ao Router
        self.manager.set_router_callback(self.router.process_packet)

        self.hb_monitor = HeartbeatManager(self.manager, timeout_seconds=7)
        self.advertiser = NodeAdvertiser(MY_ADVERTISER_NAME)
        
        self.running = True
        self.uplink_ready = False

    async def start(self):
        # Inicia o Advertising (para que outros nos vejam)
        asyncio.create_task(self.advertiser.run())
        
        print(f"[SYSTEM] No {MY_ADVERTISER_NAME} iniciado. Hops atuais: -1")

        while self.running:
            # Se nao temos pai (Uplink), procuramos um
            if not self.manager.uplink:
                if self.uplink_ready:
                    print("[SYSTEM] Conexao perdida! Resetting estado...")
                    self.uplink_ready = False
                    self.hb_monitor.stop()
                    self.advertiser.set_hops(-1) 
                    
                print("[SYSTEM] A procurar Uplink...")
                
                # Executa o scan e conexao numa thread separada para nao bloquear o loop async
                connected = await asyncio.to_thread(self.manager.find_and_connect_uplink)
                
                if connected:
                    print("[SYSTEM] Uplink estabelecido e Handshake iniciado!")
                    self.uplink_ready = True
                    
                    # Atualiza os Hops baseado no pai
                    parent_hops = self.manager.uplink_info.get('hops', 99)
                    new_hops = parent_hops + 1
                    
                    # Atualiza o advertiser para que os filhos saibam o novo custo
                    await self.advertiser.update_hops(new_hops)
                    
                    self.hb_monitor.start()
            
            await asyncio.sleep(2)

if __name__ == "__main__":
    node = NodeMain()
    try:
        asyncio.run(node.start())
    except KeyboardInterrupt:
        print("\n[SYSTEM] A encerrar...")
        if node.manager.uplink:
            node.manager.uplink.disconnect()
        node.advertiser.stop()