import asyncio
import time
import threading

from common.manageConnections import ConnectionManager
from common.advertiser import NodeAdvertiser
from node.router import Router
from node.heartbeat_manager import HeartbeatManager

MY_NAME = "SIC_NODE_01"  # mudar para pcs diferentes
MY_NID  = "NID_NODE_01"

class NodeMain:
    def __init__(self):
        self.manager = ConnectionManager()
        self.router = Router(MY_NID, self.manager)
        self.hb_monitor = HeartbeatManager(self.manager, timeout_seconds=7)
        self.advertiser = NodeAdvertiser(MY_NAME)
        
        self.running = True
        self.uplink_ready = False

    async def start(self):

        asyncio.create_task(self.advertiser.run())
        
        print(f"🚀 [SYSTEM] Nó {MY_NAME} iniciado. Hops atuais: -1")

        while self.running:
            if not self.manager.uplink:
                if self.uplink_ready:
                    print("🚨 [SYSTEM] Conexão perdida! Resetting estado...")
                    self.uplink_ready = False
                    self.hb_monitor.stop()
                    self.advertiser.set_hops(-1) 
                    
                print("[SYSTEM] A procurar Uplink...")
                connected = await asyncio.to_thread(self.manager.find_and_connect_uplink)
                
                if connected:
                    print("✅ [SYSTEM] Uplink estabelecido!")
                    self.uplink_ready = True
                    
                    parent_hops = self.manager.uplink_info.get('hops', 99)
                    new_hops = parent_hops + 1
                    
                    self.advertiser.set_hops(new_hops)
                    
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