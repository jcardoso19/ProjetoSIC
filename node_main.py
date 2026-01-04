import os
import sys
import threading
import time
import random
import asyncio
import dbus.mainloop.glib
from gi.repository import GLib

from common.manageConnections import ConnectionManager
from node.router import Router
from node.heartbeat_manager import HeartbeatManager
from common.security import SecurityManager
from common.gatt_server import GATTServerManager
from common.advertiser import NodeAdvertiser
from common.dtls import DTLSManager
from common.scan import scan_for_candidates

# --- CORES ANSI ---
C_BOLD = "\033[1m"
C_GREEN = "\033[92m"
C_BLUE = "\033[94m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_CYAN = "\033[96m"
C_END = "\033[0m"

MY_NID = "node1"
CERT_PATH = "certs/node1.crt"
KEY_PATH = "certs/node1.key"
ROOT_CA_PATH = "certs/root_ca.crt"
SINK_NID = "sink"

class NodeApp:
    def __init__(self):
        self.running = True
        self.last_handshake_attempt = 0
        self.my_client_id = random.randint(1000, 9999)
        
        print(f"{C_BOLD}{C_BLUE}[SYSTEM] A inicializar Node: {MY_NID}...{C_END}")

        try:
            self.sec_manager = SecurityManager(ROOT_CA_PATH, CERT_PATH, KEY_PATH)
        except Exception as e:
            print(f"{C_RED}[ERRO] Falha na Segurança: {e}{C_END}")
            sys.exit(1)

        self.manager = ConnectionManager(self.sec_manager, adapter_index=1, my_nid=MY_NID)
        self.router = Router(MY_NID, self.manager, self.sec_manager)
        self.manager.set_router(self.router)

        self.dtls_manager = DTLSManager(MY_NID, self.sec_manager, self.router.forward)
        self.router.set_app_callback(self.dtls_manager.process_packet)

        self.hb_monitor = HeartbeatManager(self.manager.on_uplink_lost, interval=5)
        self.router.on_heartbeat = lambda nid: self.hb_monitor.heartbeat_received()
        
        self.setup_gatt_server()

    def setup_gatt_server(self):
        def run_gatt():
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
                print(f"{C_RED}[GATT] Erro fatal: {e}{C_END}")

        threading.Thread(target=run_gatt, daemon=True).start()
        time.sleep(1)

    def wait_for_secure_connection(self):
        print(f"{C_YELLOW}[SYSTEM] A aguardar Handshake de Segurança... (Aguarde){C_END}")
        
        # AUMENTADO PARA 90 SEGUNDOS (180 * 0.5s)
        # Como o envio é seguro e lento (0.25s/chunk), precisamos de tempo para várias tentativas.
        for _ in range(180):
            if not self.running or not self.manager.uplink:
                print(f"{C_RED}[SYSTEM] Ligação perdida durante a negociação.{C_END}")
                return False
            
            if self.manager.session_key:
                print(f"{C_GREEN}[SYSTEM] Segurança confirmada.{C_END}")
                
                print(f"{C_GREEN}[SYSTEM] A iniciar Monitor de Heartbeats.{C_END}")
                self.hb_monitor.start()
                
                if SINK_NID not in self.dtls_manager.sessions:
                    self.dtls_manager.start_handshake(SINK_NID)
                
                return True 
            
            time.sleep(0.5)
            
        print(f"{C_RED}[SYSTEM] Timeout: O Handshake falhou (Sink incontactável).{C_END}")
        self.manager.disconnect_all() # FORÇA A PARAGEM DAS TENTATIVAS EM BACKGROUND
        return False

    def draw_ui(self):
        os.system('clear' if os.name == 'posix' else 'cls')
        print(f"{C_BOLD}{C_CYAN}═"*50)
        print(f"       SIC PROTOCOL - NODE TERMINAL")
        print(f"       Node ID: {MY_NID} | Client: {self.my_client_id}")
        print("═"*50 + f"{C_END}")
        
        conn = f"{C_GREEN}CONNECTED{C_END}" if self.manager.uplink else f"{C_RED}DISCONNECTED{C_END}"
        sec = f"{C_GREEN}SECURE{C_END}" if self.manager.session_key else f"{C_YELLOW}OPEN{C_END}"
        e2e = f"{C_GREEN}ACTIVE{C_END}" if SINK_NID in self.dtls_manager.sessions else f"{C_RED}INACTIVE{C_END}"
        
        print(f" {C_BOLD}Status:{C_END} [Link: {conn}] [Enc: {sec}] [E2E: {e2e}]")
        print(f"{C_CYAN}─"*50 + f"{C_END}")
        print(f" {C_BOLD}MENU:{C_END} {C_YELLOW}scan{C_END}, {C_YELLOW}conn{C_END}, {C_YELLOW}msg <t>{C_END}, {C_YELLOW}disc{C_END}, {C_YELLOW}cls{C_END}, {C_YELLOW}q{C_END}")
        print(f"{C_CYAN}─"*50 + f"{C_END}\n")

    def run_cli(self):
        self.draw_ui()
        while self.running:
            try:
                line = input(f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}").strip()
                if not line: continue
                parts = line.split()
                cmd = parts[0].lower()

                if cmd == "scan":
                    scan_for_candidates(self.manager.adapter)
                elif cmd == "conn":
                    if self.manager.find_and_connect_uplink():
                        self.wait_for_secure_connection()
                elif cmd == "msg":
                    if len(parts) < 2: continue
                    msg_text = " ".join(parts[1:])
                    if SINK_NID in self.dtls_manager.sessions:
                        self.dtls_manager.send_data(SINK_NID, msg_text, client_id=self.my_client_id)
                    else:
                        print(f"{C_YELLOW}[DTLS] A negociar sessão E2E...{C_END}")
                        self.dtls_manager.start_handshake(SINK_NID)
                elif cmd == "cls": self.draw_ui()
                elif cmd == "disc": self.manager.disconnect_all()
                elif cmd == "q": os._exit(0)
            except Exception as e: print(f"{C_RED}[CLI] Erro: {e}{C_END}")

    def auto_retry_loop(self):
        while self.running:
            if self.manager.uplink and self.manager.session_key:
                if SINK_NID not in self.dtls_manager.sessions:
                    now = time.time()
                    if now - self.last_handshake_attempt > 10:
                        self.dtls_manager.start_handshake(SINK_NID)
                        self.last_handshake_attempt = now
            time.sleep(2)

if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    app = NodeApp()
    threading.Thread(target=app.auto_retry_loop, daemon=True).start()
    app.run_cli()