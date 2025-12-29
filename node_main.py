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
NODE_FILE_NAME = "node1" 
MY_NID  = "NID_NODE_01"
MY_ADVERTISER_NAME = "SIC_NODE_01" 

class NodeMain:
    def __init__(self):
        my_cert_bytes = None
        my_private_key = None

        # 1. CARREGAR CERTIFICADOS
        cert_path = f"support/certs/{NODE_FILE_NAME}.crt"
        key_path  = f"support/certs/{NODE_FILE_NAME}.key"
        
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
        except Exception as e:
            print(f"[ERRO] Nao foi possivel carregar certificados: {e}")
            print("[WARN] A iniciar em modo INSEGURO.")

        # 2. INICIAR CONNECTION MANAGER - *** MUDANÇA AQUI (Index=0 / Interna) ***
        self.manager = ConnectionManager(my_cert_bytes, my_private_key, adapter_index=0)
        
        # 3. CONFIGURAR ROUTER
        self.router = Router(MY_NID, self.manager)
        self.manager.set_router_callback(self.router.process_packet)

        # 4. OUTROS COMPONENTES
        self.hb_monitor = HeartbeatManager(self.manager, timeout_seconds=7)
        self.advertiser = NodeAdvertiser(MY_ADVERTISER_NAME)
        
        self.running = True
        self.uplink_ready = False

    async def start(self):
        # Mantemos o "Modo Silencioso" (comentado) para garantir a conexão primeiro
        # asyncio.create_task(self.advertiser.run())
        
        print(f"[SYSTEM] No {MY_ADVERTISER_NAME} iniciado (MODO SILENCIOSO).")
        print(f"[SYSTEM] A procurar Uplink...")

        while self.running:
            # Se nao temos pai (Uplink), procuramos um
            if not self.manager.uplink:
                
                if self.uplink_ready:
                    print("[SYSTEM] Conexao perdida! Resetting estado...")
                    self.uplink_ready = False
                    self.hb_monitor.stop()
                    
                print("[SYSTEM] A procurar Uplink...")
                
                # Executa o scan e conexao
                connected = await asyncio.to_thread(self.manager.find_and_connect_uplink)
                
                if connected:
                    print("[SYSTEM] Uplink estabelecido e Handshake iniciado!")
                    self.uplink_ready = True
                    self.hb_monitor.start()
            
            await asyncio.sleep(2)

if __name__ == "__main__":
    node = NodeMain()
    try:
        asyncio.run(node.start())
    except KeyboardInterrupt:
        print("\n[SYSTEM] A encerrar...")
        if node.manager.uplink:
            try:
                node.manager.uplink.disconnect()
            except:
                pass