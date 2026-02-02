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
from common.protocol import Packet, MSG_TYPE_DATA, MSG_TYPE_E2E_DATA, MSG_TYPE_E2E_HELLO, MSG_TYPE_E2E_HELLO_ACK

C_BOLD = "\033[1m"
C_GREEN = "\033[92m"
C_BLUE = "\033[94m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_CYAN = "\033[96m"
C_END = "\033[0m"

if len(sys.argv) > 1: MY_NID = sys.argv[1]
else: MY_NID = "node1"
if len(sys.argv) > 2: ADAPTER_INDEX = int(sys.argv[2])
else: ADAPTER_INDEX = 0 

CERT_PATH = f"certs/{MY_NID}.crt"
KEY_PATH = f"certs/{MY_NID}.key"
ROOT_CA_PATH = "certs/root_ca.crt"
SINK_NID = "sink" 

class NodeApp:
    def __init__(self):
        self.running = True
        self.prompt_text = f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}"
        self.log_lock = threading.Lock()
        self.current_hops = 99 # Estado inicial: Desconectado

        print(f"{C_BOLD}{C_BLUE}[SYSTEM] A inicializar Node: {MY_NID}...{C_END}")

        try:
            self.sec_manager = SecurityManager(ROOT_CA_PATH, CERT_PATH, KEY_PATH)
        except Exception as e:
            self.safe_print(f"{C_RED}[ERRO] Falha na Segurança: {e}{C_END}")
            sys.exit(1)

        self.manager = ConnectionManager(self.sec_manager, adapter_index=ADAPTER_INDEX, my_nid=MY_NID)
        self.router = Router(MY_NID, self.manager, self.sec_manager)
        self.manager.set_router(self.router)
        self.dtls_manager = DTLSManager(MY_NID, self.sec_manager, self.router.forward)
        
        self.router.set_app_callback(self.on_app_message)
        self.hb_monitor = HeartbeatManager(self.on_uplink_death, interval=5)
        self.router.on_heartbeat = self.on_heartbeat_safe 

        self.advertiser = None 
        self.gatt_server_started = False
        self.start_gatt_and_advertiser(hops=99)

    def safe_print(self, text):
        with self.log_lock:
            sys.stdout.write(f"\r\033[K{text}\n")
            sys.stdout.write(self.prompt_text)
            sys.stdout.flush()

    def on_heartbeat_safe(self, nid):
        self.hb_monitor.heartbeat_received()

    def on_app_message(self, packet):
        if packet.msg_type in [MSG_TYPE_DATA, MSG_TYPE_E2E_DATA, MSG_TYPE_E2E_HELLO, MSG_TYPE_E2E_HELLO_ACK]:
            decrypted = self.dtls_manager.process_packet(packet)
            if decrypted and isinstance(decrypted, str):
                 self.safe_print(f"{C_GREEN}[APP] 📩 MENSAGEM de {packet.source_nid}: {decrypted}{C_END}")

    def start_gatt_and_advertiser(self, hops):
        self.current_hops = hops
        if hasattr(self, 'advertiser') and self.advertiser:
            try: self.advertiser.stop()
            except: pass

        def run_gatt_loop():
            try:
                bus = dbus.SystemBus()
                if not getattr(self, 'gatt_server_started', False):
                    gatt_server = GATTServerManager(bus, adapter_index=ADAPTER_INDEX)
                    gatt_server.set_data_callback(self.router.process_packet)
                    gatt_server.set_disconnect_callback(self.router.drop_connection)
                    gatt_server.register()
                    self.router.set_gatt_server(gatt_server)
                    self.gatt_server_started = True

                self.advertiser = NodeAdvertiser(MY_NID, hops=hops, adapter_index=ADAPTER_INDEX)
                loop = GLib.MainLoop()
                async def start_ad(): await self.advertiser.run()
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(start_ad())
                loop.run()
            except: pass

        t = threading.Thread(target=run_gatt_loop, daemon=True)
        t.start()
        time.sleep(0.5)

    def on_uplink_death(self):
        self.safe_print(f"\n{C_RED}[CRITICAL] UPLINK DEAD! Parando Advertiser para novo scan...{C_END}")
        if hasattr(self, 'advertiser') and self.advertiser:
            self.advertiser.stop()
        self.reset_network_state()

    def reset_network_state(self):
        if hasattr(self, 'hb_monitor'):
            self.hb_monitor.stop()
            self.hb_monitor.missed_count = 0
        
        self.manager.disconnect_all()
        
        self.manager.uplink = None
        self.manager.session_key = None
        self.dtls_manager.sessions.clear() 
        self.router.forwarding_table.clear()
        self.router.downlink_keys.clear()
        
        if hasattr(self, 'advertiser') and self.advertiser:
            self.advertiser.stop()
            
        self.safe_print(f"{C_YELLOW}[SYSTEM] Estado de rede resetado.{C_END}")

    def wait_for_secure_connection(self, parent_hops):
        self.safe_print(f"{C_YELLOW}[SYSTEM] A aguardar Handshake Link-Layer...{C_END}")
        for _ in range(60):
            if not self.manager.uplink: return False
            if self.manager.session_key:
                self.safe_print(f"{C_GREEN}[SYSTEM] Conexão Segura Estabelecida!{C_END}")
                self.hb_monitor.start()
                
                my_new_hops = parent_hops + 1
                self.safe_print(f"{C_BLUE}[TOPOLOGY] Hops atualizado: {parent_hops} -> {my_new_hops}{C_END}")
                self.start_gatt_and_advertiser(hops=my_new_hops)
                self.safe_print(f"{C_CYAN}[DTLS] A estabelecer canal seguro automático com {SINK_NID}...{C_END}")
                self.dtls_manager.start_handshake(SINK_NID)
                return True 
            time.sleep(0.5)
        return False

    def scan_and_select(self):
        """Permite ao utilizador ESCOLHER a quem se quer ligar."""
        self.safe_print("A procurar candidatos...")
        candidates = scan_for_candidates(self.manager.adapter)
        
        if not candidates:
            self.safe_print("Nenhum nó encontrado.")
            return None, 99

        print(f"\n{C_BOLD}--- CANDIDATOS DISPONÍVEIS ---{C_END}")
        valid_indices = []
        for i, cand in enumerate(candidates):
            hops_str = cand.get('hops', '?')
            print(f"[{i}] {cand['name']} (Hops: {hops_str}) | RSSI: {cand['rssi']}")
            valid_indices.append(i)
        print("------------------------------")
        
        # Input Bloqueante (Simples)
        while True:
            try:
                choice = input("Escolha o índice (ou 'c' para cancelar): ")
                if choice.lower() == 'c': return None, 99
                idx = int(choice)
                if idx in valid_indices:
                    return candidates[idx], candidates[idx].get('hops', 99)
            except: pass
            print("Inválido.")

    def draw_ui(self):
        os.system('clear' if os.name == 'posix' else 'cls')
        print(f"{C_BOLD}{C_CYAN}════"*15 + f"{C_END}")
        print(f"       SIC PROTOCOL - NODE TERMINAL")
        print(f"       Node ID: {MY_NID} | Hops: {self.current_hops}")
        print(f"{C_BOLD}{C_CYAN}════"*15 + f"{C_END}")
        
        status = f"{C_GREEN}CONNECTED 🔗{C_END}" if self.manager.uplink else f"{C_RED}DISCONNECTED ❌{C_END}"
        print(f"  📡  LINK:    {status}")
        
        # --- FORWARDING TABLE VISUAL ---
        print(f"\n{C_BOLD}  🗺️  FORWARDING TABLE (Quem eu conheço):{C_END}")
        if not self.router.forwarding_table:
            print("     (Vazia)")
        else:
            for nid, via in self.router.forwarding_table.items():
                via_str = "UPLINK" if via == self.manager.uplink else f"Downlink ({via})"
                print(f"     • {nid} -> via {via_str}")
        
        print(f"\n{C_CYAN}────────────────────────────────────────────────────────────{C_END}")
        print(f" {C_BOLD}MENU:{C_END} scan (auto), list (escolher), msg <txt>, who (rede), disc, cls, q")
        print(f"{C_CYAN}────────────────────────────────────────────────────────────{C_END}\n")

    def run_cli(self):
        import select
        self.draw_ui()
        sys.stdout.write(self.prompt_text)
        sys.stdout.flush()

        while self.running:
            if select.select([sys.stdin], [], [], 0.5)[0]:
                line = sys.stdin.readline().strip()
                if not line: 
                    sys.stdout.write(self.prompt_text)
                    sys.stdout.flush()
                    continue
                
                parts = line.split()
                cmd = parts[0].lower()

                if cmd == "scan":
                    # Conexão automática (comportamento antigo)
                    if self.manager.find_and_connect_uplink():
                        # Assume 0 hops se auto-conectar ao Sink, ou 1 (fallback)
                        self.wait_for_secure_connection(0) 

                elif cmd == "list":
                    # ESCOLHA MANUAL
                    cand, hops = self.scan_and_select()
                    if cand:
                        # Chama manager diretamente com o objeto selecionado
                        if self.manager.connect_to_specific_device(cand['device_obj']):
                            self.wait_for_secure_connection(hops)
                        self.draw_ui()

                elif cmd == "msg":
                    if len(parts) < 2: 
                        self.safe_print("Use: msg <texto>")
                    else:
                        txt = " ".join(parts[1:])
                        if SINK_NID not in self.dtls_manager.sessions:
                            self.safe_print(f"{C_YELLOW}[DTLS] Sem sessão. A iniciar handshake com o Sink...{C_END}")
                            self.dtls_manager.start_handshake(SINK_NID)
                            self.safe_print(f"{C_YELLOW}[DTLS] Aguarde o estabelecimento da sessão e repita o comando.{C_END}")
                        else:
                            self.dtls_manager.send_data(SINK_NID, txt, service="Inbox")

                elif cmd == "who":
                    if SINK_NID not in self.dtls_manager.sessions:
                         self.safe_print("Sem sessão com Sink. Tente 'msg ola' primeiro.")
                    else:
                        self.safe_print("A pedir lista de nós ao Sink...")
                        self.dtls_manager.send_data(SINK_NID, "LIST_NODES", service="NetworkManager")

                elif cmd == "disc":
                    self.safe_print(f"{C_YELLOW}A desligar...{C_END}")
                    self.reset_network_state()
                elif cmd == "cls":
                    self.draw_ui()
                elif cmd == "q":
                    self.running = False
                    self.reset_network_state()
                    os._exit(0)
                
                sys.stdout.write(self.prompt_text)
                sys.stdout.flush()

if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    app = NodeApp()
    app.run_cli()