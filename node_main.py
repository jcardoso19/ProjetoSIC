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
from common.protocol import Packet, MSG_TYPE_DATA

# Cores
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
SINK_NID = "SINK" # Nome padrão do Sink no protocolo

class NodeApp:
    def __init__(self):
        self.running = True
        self.prompt_text = f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}"
        
        # Sistema de Logs limpo (evita salganhada)
        self.log_lock = threading.Lock()

        print(f"{C_BOLD}{C_BLUE}[SYSTEM] A inicializar Node: {MY_NID}...{C_END}")

        try:
            self.sec_manager = SecurityManager(ROOT_CA_PATH, CERT_PATH, KEY_PATH)
        except Exception as e:
            self.safe_print(f"{C_RED}[ERRO] Falha na Segurança: {e}{C_END}")
            sys.exit(1)

        self.manager = ConnectionManager(self.sec_manager, adapter_index=ADAPTER_INDEX, my_nid=MY_NID)
        self.router = Router(MY_NID, self.manager, self.sec_manager)
        self.manager.set_router(self.router)

        # DTLS Manager (Segurança E2E)
        self.dtls_manager = DTLSManager(MY_NID, self.sec_manager, self.router.send_message)
        
        # Callbacks
        self.router.set_app_callback(self.on_app_message)
        self.hb_monitor = HeartbeatManager(self.on_uplink_death, interval=5)
        
        # Quando recebe heartbeat, chama esta função segura
        self.router.on_heartbeat = self.on_heartbeat_safe 

        # Inicia Advertiser (Hops=99 até conectar)
        self.start_gatt_and_advertiser(hops=99)

    def safe_print(self, text):
        """Imprime sem estragar o input do utilizador (Salganhada Fix)."""
        with self.log_lock:
            # \r = volta ao inicio da linha, \033[K = apaga a linha
            sys.stdout.write(f"\r\033[K{text}\n")
            # Reescreve o prompt
            sys.stdout.write(self.prompt_text)
            sys.stdout.flush()

    def on_heartbeat_safe(self, nid):
        self.hb_monitor.heartbeat_received()
        # Mostra o heartbeat de forma bonita e não intrusiva
        self.safe_print(f"   {C_CYAN}♥ [SINK ALIVE]{C_END} (Seq: Recente)")

    def on_app_message(self, packet):
        """Recebe dados da rede (Router -> App)."""
        if packet.msg_type == MSG_TYPE_DATA:
            # Passa para o DTLS processar
            self.dtls_manager.process_packet(packet)

    def start_gatt_and_advertiser(self, hops):
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
        self.safe_print(f"\n{C_RED}[CRITICAL] UPLINK DEAD! A reiniciar estado...{C_END}")
        self.reset_network_state()
        self.start_gatt_and_advertiser(hops=99)

    def reset_network_state(self):
        """Limpa tudo para garantir reconexão limpa."""
        self.manager.disconnect_all()
        self.manager.uplink = None
        self.manager.session_key = None
        self.dtls_manager.sessions.clear() # Limpa sessões E2E antigas
        self.router.forwarding_table.clear()
        self.router.downlink_keys.clear()
        self.hb_monitor.missed_count = 0

    def wait_for_secure_connection(self):
        self.safe_print(f"{C_YELLOW}[SYSTEM] A aguardar Handshake Link-Layer...{C_END}")
        for _ in range(60):
            if not self.manager.uplink: return False
            if self.manager.session_key:
                self.safe_print(f"{C_GREEN}[SYSTEM] Conexão Segura Estabelecida!{C_END}")
                self.hb_monitor.start()
                
                # Atualizar Hops e Advertiser
                self.start_gatt_and_advertiser(hops=1)
                return True 
            time.sleep(0.5)
        return False

    def draw_ui(self):
        os.system('clear' if os.name == 'posix' else 'cls')
        print(f"{C_BOLD}{C_CYAN}════"*15 + f"{C_END}")
        print(f"       SIC PROTOCOL - NODE TERMINAL")
        print(f"       Node ID: {MY_NID} | Adapter: hci{ADAPTER_INDEX}")
        print(f"{C_BOLD}{C_CYAN}════"*15 + f"{C_END}")
        
        status = f"{C_GREEN}CONNECTED 🔗{C_END}" if self.manager.uplink else f"{C_RED}DISCONNECTED ❌{C_END}"
        print(f"  📡  LINK:    {status}")
        print(f"{C_CYAN}────────────────────────────────────────────────────────────{C_END}")
        print(f" {C_BOLD}MENU:{C_END} scan, conn, msg <txt>, disc, cls, q")
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
                    scan_for_candidates(self.manager.adapter)
                elif cmd == "conn":
                    if self.manager.find_and_connect_uplink():
                        self.wait_for_secure_connection()
                elif cmd == "msg":
                    if len(parts) < 2: self.safe_print("Use: msg <texto>")
                    else:
                        txt = " ".join(parts[1:])
                        # Tenta iniciar sessão E2E se não existir
                        if SINK_NID not in self.dtls_manager.sessions:
                             self.safe_print(f"{C_YELLOW}[DTLS] A iniciar sessão E2E...{C_END}")
                             self.dtls_manager.start_handshake(SINK_NID)
                             time.sleep(1) # Dá tempo para o handshake
                        
                        # Envia a mensagem (cifrada se houver sessão)
                        self.dtls_manager.send_data(SINK_NID, txt)
                        self.safe_print(f"[APP] 📤 Mensagem enviada para {SINK_NID}")

                elif cmd == "disc":
                    self.safe_print(f"{C_YELLOW}A desligar...{C_END}")
                    self.reset_network_state()
                    self.on_uplink_death() # Força UI update
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