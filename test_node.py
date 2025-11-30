from common.manageConnections import ConnectionManager
from node.router import Router
from node.heartbeat_manager import HeartbeatManager
import time
import threading

MY_NID = "NID_TESTE_01"

manager = ConnectionManager()
router = Router(MY_NID, manager)
hb_monitor = HeartbeatManager(manager, timeout_seconds=6)


def simulate_incoming_heartbeats():
    time.sleep(2)
    for i in range(3):
        hb_monitor.beat_received()
        time.sleep(2)
    
    print("\n🛑 [SIMULAÇÃO] O Uplink parou de enviar Heartbeats! (Corte de cabo)\n")

while True:
    if not manager.uplink:
        connected = manager.find_and_connect_uplink()
        if connected:
            hb_monitor.start()
            threading.Thread(target=simulate_incoming_heartbeats).start()

    time.sleep(1)