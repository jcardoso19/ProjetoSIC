from common.manageConnections import ConnectionManager
from node.router import Router
from node.heartbeat_manager import HeartbeatManager
from common.security import SecurityManager
from common.gatt_server import GATTServerManager
from common.advertiser import NodeAdvertiser
from common.dtls import DTLSManager
from common.scan import scan_for_candidates
import dbus.mainloop.glib
import threading
import time
import asyncio
import random
import sys
from gi.repository import GLib

# --- CONFIGURAÇÃO ---
MY_NID = "node1"
CERT_PATH = "certs/node1.crt"
KEY_PATH = "certs/node1.key"
ROOT_CA_PATH = "certs/root_ca.crt"
SINK_NID = "sink"

class NodeApp:
    def __init__(self):
        self.running = True
        self.candidates = []
        
        try:
            self.sec_manager = SecurityManager(ROOT_CA_PATH, CERT_PATH, KEY_PATH)
        except Exception as e:
            print(f"[ERRO] Falha ao carregar segurança: {e}")
            sys.exit(1)

        # MUDANÇA: Passa o MY_NID para o Manager
        self.manager = ConnectionManager(
            security_manager=self.sec_manager, 
            adapter_index=1, 
            my_nid=MY_NID
        )
        
        self.router = Router(MY_NID, self.manager, security_manager=self.sec_manager)
        self.manager.set_router_callback(self.router.process_packet)
        
        self.dtls_manager = DTLSManager(MY_NID, self.sec_manager, self.router.forward)
        self.router.set_app_callback(self.dtls_manager.process_packet)

        self.hb_monitor = HeartbeatManager(self.manager, timeout_seconds=7)
        self.router.on_heartbeat = lambda nid: self.hb_monitor.beat_received()
        
        self.setup_gatt()
        self.handshake_started = False
        self.my_client_id = random.randint(1000, 9999)

    def setup_gatt(self):
        def run_gatt_server():
            try:
                bus = dbus.SystemBus()
                gatt_server = GATTServerManager(bus, adapter_index=1)
                gatt_server.set_data_callback(self.router.process_packet)
                gatt_server.register()
                self.router.set_gatt_server(gatt_server)
                advertiser = NodeAdvertiser(MY_NID, hops=99, adapter_index=1)
                loop = GLib.MainLoop()
                async def start_ad(): await advertiser.run()
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(start_ad())
                loop.run()
            except Exception as e:
                print(f"[GATT] Erro na thread do servidor: {e}")

        t = threading.Thread(target=run_gatt_server, daemon=True)
        t.start()
        time.sleep(2)

    def print_menu(self):
        print("\n" + "="*40)
        print(f"   NODE CONTROL: {MY_NID} (Client {self.my_client_id})")
        print("="*40)
        print("1. Status")
        print("2. Scan")
        print("3. Connect")
        print("4. Send <msg>")
        print("5. Block HB <nid>")
        print("6. Unblock HB <nid>")
        print("7. Disconnect")
        print("h. Help")
        print("q. Quit")
        print("="*40)

    def run_cli(self):
        self.print_menu()
        while self.running:
            try:
                cmd_line = input("\n> ").strip().split()
                if not cmd_line: continue
                cmd = cmd_line[0].lower()
                
                if cmd == '1':
                    print(f"⬆️ Uplink: {self.manager.uplink is not None}")
                elif cmd == '2':
                    self.candidates = scan_for_candidates(self.manager.adapter)
                elif cmd == '3':
                    if self.manager.find_and_connect_uplink():
                         self.hb_monitor.start()
                         print("[CLI] ✅ Connected!")
                elif cmd == '4':
                    msg = " ".join(cmd_line[1:])
                    if SINK_NID in self.dtls_manager.sessions:
                        self.dtls_manager.send_data(SINK_NID, msg, client_id=self.my_client_id)
                    else: print("[CLI] No Session yet.")
                elif cmd == 'q': sys.exit(0)
            except Exception as e: print(f"[CLI] Error: {e}")

    def main_loop(self):
        cli_thread = threading.Thread(target=self.run_cli, daemon=True)
        cli_thread.start()
        while self.running:
            if self.manager.uplink and self.manager.session_key:
                 if not self.handshake_started:
                     self.dtls_manager.start_handshake(SINK_NID)
                     self.handshake_started = True
            time.sleep(1)

if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    app = NodeApp()
    app.main_loop()