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

# ==============================================================================
# 1. LER ARGUMENTOS DA LINHA DE COMANDOS (CLI)
# ==============================================================================

# Argumento 1: Nome do Nó (Default: node1)
if len(sys.argv) > 1:
    MY_NID = sys.argv[1]
else:
    MY_NID = "node1"

if len(sys.argv) > 2:
    ADAPTER_INDEX = int(sys.argv[2])
else:
    ADAPTER_INDEX = 0 

print(f"{C_BOLD}[CONFIG] A iniciar {MY_NID} na interface hci{ADAPTER_INDEX}...{C_END}")


CERT_PATH = f"certs/{MY_NID}.crt"
KEY_PATH = f"certs/{MY_NID}.key"
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
            print(f"{C_RED}       Verifica se criaste as chaves para {MY_NID}!{C_END}")
            sys.exit(1)

        # MUDANÇA: Usa ADAPTER_INDEX e MY_NID das variáveis globais
        self.manager = ConnectionManager(self.sec_manager, adapter_index=ADAPTER_INDEX, my_nid=MY_NID)
        
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
                gatt_server = GATTServerManager(bus, adapter_index=ADAPTER_INDEX)
                gatt_server.set_data_callback(self.router.process_packet)
                gatt_server.register()
                self.router.set_gatt_server(gatt_server)
                
                advertiser = NodeAdvertiser(MY_NID, hops=99, adapter_index=ADAPTER_INDEX)
                
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
        
        # AUMENTADO PARA 90 SEGUNDOS
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
        self.manager.disconnect_all()
        return False

    def draw_ui(self):
        os.system('clear' if os.name == 'posix' else 'cls')
        
        if self.manager.uplink:
            conn_txt = f"{C_GREEN}CONNECTED 🔗{C_END}"
        else:
            conn_txt = f"{C_RED}DISCONNECTED ❌{C_END}"

        is_secured = getattr(self.router, 'is_secured', False)

        if is_secured:
            sec_txt = f"{C_GREEN}ACTIVE 🔒{C_END}"
        elif self.manager.uplink:
            sec_txt = f"{C_YELLOW}HANDSHAKING... ⏳{C_END}"
        else:
            sec_txt = f"{C_RED}OFFLINE 🚫{C_END}"

        print(f"{C_BOLD}{C_CYAN}═"*60)
        print(f"       SIC PROTOCOL - NODE TERMINAL")
        print(f"       Node ID: {MY_NID} | Adapter: hci{ADAPTER_INDEX}")
        print("═"*60 + f"{C_END}")
        
        print(f"  📡  LINK:  {conn_txt}")
        print(f"  🛡️  E2E SECURITY:   {sec_txt}")
        print(f"{C_CYAN}─"*60 + f"{C_END}")
        print(f" {C_BOLD}MENU:{C_END} scan, conn, msg <txt>, disc, cls, q")
        print(f"{C_CYAN}─"*60 + f"{C_END}\n")

    def run_cli(self):
        import select
        
        # Variáveis para memorizar o estado anterior
        last_uplink = None
        last_secure = None
        
        # Desenha a primeira vez
        self.draw_ui()
        print(f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}", end="", flush=True)

        while self.running:
            # 1. Verificar o Estado Atual
            curr_uplink = self.manager.uplink
            curr_secure = getattr(self.router, 'is_secured', False)

            # 2. Só redesenha o ecrã SE algo tiver mudado!
            if curr_uplink != last_uplink or curr_secure != last_secure:
                self.draw_ui()
                print(f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}", end="", flush=True)
                
                # Atualiza a memória
                last_uplink = curr_uplink
                last_secure = curr_secure

            # 3. Espera por input (timeout curto para verificar estados frequentemente)
            # Se carregares numa tecla, entra aqui. Se não, passa à frente.
            if select.select([sys.stdin], [], [], 0.2)[0]:
                line = sys.stdin.readline().strip()
                if not line: 
                    # Se der Enter vazio, redesenha o prompt
                    print(f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}", end="", flush=True)
                    continue
                
                parts = line.split()
                cmd = parts[0].lower()

                if cmd == "scan":
                    scan_for_candidates(self.manager.adapter)
                    input("Pressiona Enter para continuar...") 
                    self.draw_ui() # Força redesenho após o scan
                elif cmd == "conn":
                    if self.manager.find_and_connect_uplink():
                        self.wait_for_secure_connection()
                        # O wait já mexe no ecrã, forçamos update a seguir
                        last_uplink = None 
                elif cmd == "msg":
                    if len(parts) < 2: 
                        print("Erro: msg <texto>")
                    else:
                        msg_text = " ".join(parts[1:])
                        if SINK_NID in self.dtls_manager.sessions:
                            self.dtls_manager.send_data(SINK_NID, msg_text, client_id=self.my_client_id)
                        else:
                            print(f"{C_YELLOW}[DTLS] A negociar sessão E2E...{C_END}")
                            self.dtls_manager.start_handshake(SINK_NID)
                            time.sleep(1)
                elif cmd == "cls": 
                    self.draw_ui()
                elif cmd == "disc": 
                    self.manager.disconnect_all()
                elif cmd == "q": 
                    self.running = False
                    os._exit(0)
                
                print(f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}", end="", flush=True)

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