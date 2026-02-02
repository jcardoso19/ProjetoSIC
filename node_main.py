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

# Cores para o Terminal
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
        self.last_handshake_attempt = 0
        self.my_client_id = random.randint(1000, 9999)
        self.advertiser = None # Referência para o advertiser
        self.adv_thread = None
        self.loop = None
        
        print(f"{C_BOLD}{C_BLUE}[SYSTEM] A inicializar Node: {MY_NID} na hci{ADAPTER_INDEX}...{C_END}")

        try:
            self.sec_manager = SecurityManager(ROOT_CA_PATH, CERT_PATH, KEY_PATH)
        except Exception as e:
            print(f"{C_RED}[ERRO] Falha na Segurança: {e}{C_END}")
            sys.exit(1)

        self.manager = ConnectionManager(self.sec_manager, adapter_index=ADAPTER_INDEX, my_nid=MY_NID)
        
        self.router = Router(MY_NID, self.manager, self.sec_manager)
        self.manager.set_router(self.router)

        self.dtls_manager = DTLSManager(MY_NID, self.sec_manager, self.router.forward)
        self.router.set_app_callback(self.dtls_manager.process_packet)

        # Configurar callback de morte do uplink
        self.hb_monitor = HeartbeatManager(self.on_uplink_death, interval=5)
        self.router.on_heartbeat = lambda nid: self.hb_monitor.heartbeat_received()
        
        # Inicia com Hops=99 (Desligado da rede)
        self.start_gatt_and_advertiser(hops=99)

    def start_gatt_and_advertiser(self, hops):
        """Inicia (ou reinicia) o GATT Server e o Advertiser com o nº de hops correto."""
        if self.advertiser:
            try: self.advertiser.stop()
            except: pass

        def run_gatt_loop():
            try:
                # Nota: O bus de sistema deve ser obtido dentro da thread se não for partilhado
                bus = dbus.SystemBus()
                # Configurar Servidor GATT (só precisa de ser feito uma vez idealmente, mas aqui garantimos reinicio limpo)
                if not getattr(self, 'gatt_server_started', False):
                    gatt_server = GATTServerManager(bus, adapter_index=ADAPTER_INDEX)
                    gatt_server.set_data_callback(self.router.process_packet)
                    gatt_server.set_disconnect_callback(self.router.drop_connection)
                    gatt_server.register()
                    self.router.set_gatt_server(gatt_server)
                    self.gatt_server_started = True

                # Configurar Advertiser
                self.advertiser = NodeAdvertiser(MY_NID, hops=hops, adapter_index=ADAPTER_INDEX)
                
                # Criar loop para esta thread
                loop = GLib.MainLoop()
                async def start_ad(): await self.advertiser.run()
                
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(start_ad())
                
                loop.run()
            except Exception as e:
                print(f"{C_RED}[GATT/ADV] Erro na thread: {e}{C_END}")

        # Iniciar numa thread nova para não bloquear
        self.adv_thread = threading.Thread(target=run_gatt_loop, daemon=True)
        self.adv_thread.start()
        time.sleep(1)

    def on_uplink_death(self):
        """Chamado quando o Heartbeat falha 3 vezes."""
        print(f"\n{C_RED}[CRITICAL] UPLINK DEAD! A iniciar desconexão em cadeia...{C_END}")
        self.manager.on_uplink_lost() # Limpa estado BLE
        self.dtls_manager.sessions.clear() # Limpa sessões E2E
        
        # REQUISITO: Chain reaction -> Desligar downlinks
        # Reiniciar o advertiser com HOPS=99 força os vizinhos a reavaliar ou a perder conexão
        # Se quiséssemos ser agressivos, podíamos parar o GATT server, mas mudar para 99 avisa que "caímos".
        print(f"{C_YELLOW}[TOPOLOGY] A reiniciar Advertiser com HOPS=99...{C_END}")
        self.start_gatt_and_advertiser(hops=99)

    def wait_for_secure_connection(self):
        print(f"{C_YELLOW}[SYSTEM] A aguardar Handshake...{C_END}")
        
        for _ in range(180):
            if not self.manager.uplink: return False
            
            if self.manager.session_key:
                print(f"{C_GREEN}[SYSTEM] Conexão Segura Estabelecida!{C_END}")
                self.hb_monitor.start()
                
                # --- ATUALIZAÇÃO DE HOPS ---
                # Tentar descobrir hops do uplink para fazer hops + 1
                uplink_hops = 99
                try:
                    # Tenta ler do info guardado pelo scan
                    info = self.manager.uplink_info
                    # Assumindo que o scan guardou hops. Se não, assume 0 (se for Sink) ou mantém 99
                    # Uma implementação robusta parsearia o manufacturer_data aqui.
                    # Simplificação: Se o nome for SINK_DEVICE -> 0, senão tentamos adivinhar ou usar 1.
                    if "SINK" in info.get('name', '').upper():
                        uplink_hops = 0
                    else:
                        # Ler bytes brutos se disponível, senão assume 1 (para teste)
                        uplink_hops = 1 # Fallback
                except: pass

                my_new_hops = uplink_hops + 1
                print(f"{C_BLUE}[TOPOLOGY] Atualizando Advertiser: Uplink={uplink_hops} -> Eu={my_new_hops}{C_END}")
                self.start_gatt_and_advertiser(hops=my_new_hops)
                # ---------------------------

                # Iniciar DTLS
                if SINK_NID not in self.dtls_manager.sessions:
                    self.dtls_manager.start_handshake(SINK_NID)
                
                return True 
            time.sleep(0.5)
        return False

    def draw_ui(self):
        os.system('clear' if os.name == 'posix' else 'cls')
        
        uplink_name = "Nenhum"
        if self.manager.uplink:
            uplink_name = self.manager.uplink_info.get('name', 'Unknown')
            conn_txt = f"{C_GREEN}CONNECTED 🔗 ({uplink_name}){C_END}"
        else:
            conn_txt = f"{C_RED}DISCONNECTED ❌{C_END}"

        dtls_status = f"{C_RED}OFF{C_END}"
        if SINK_NID in self.dtls_manager.sessions:
            dtls_status = f"{C_GREEN}SECURE TÚNEL (Sink){C_END}"

        print(f"{C_BOLD}{C_CYAN}═"*70)
        print(f"       SIC PROTOCOL - NODE DASHBOARD")
        print(f"       Node ID: {MY_NID} | Adapter: hci{ADAPTER_INDEX}")
        print("═"*70 + f"{C_END}")
        
        print(f"  📡  UPLINK STATUS:    {conn_txt}")
        print(f"  🛡️  E2E SECURITY:     {dtls_status}")
        print(f"  💓  HEARTBEAT MISSES: {self.hb_monitor.missed_count} / 3")
        print(f"  📨  MSGs ROUTED:      {self.router.routed_messages_count}")
        print(f"{C_CYAN}─"*70 + f"{C_END}")
        
        print(f"{C_BOLD}  🔻 DOWNLINKS (Vizinhos ligados a mim):{C_END}")
        if not self.router.downlink_keys:
            print("     (Nenhum)")
        else:
            for mac in self.router.downlink_keys:
                # Tenta encontrar o NID associado na forwarding table
                nid = next((k for k, v in self.router.forwarding_table.items() if v == mac), "Unknown NID")
                print(f"     • MAC: {mac} -> NID: {nid}")

        print(f"{C_BOLD}  🗺️  FORWARDING TABLE:{C_END}")
        print(f"     {self.router.forwarding_table}")
        
        print(f"{C_CYAN}─"*70 + f"{C_END}")
        print(f" {C_BOLD}MENU:{C_END} scan, conn, msg <txt>, block <nid>, unblock <nid>, disc, cls, q")
        print(f"{C_CYAN}─"*70 + f"{C_END}\n")

    def run_cli(self):
        import select
        
        last_uplink_state = False
        
        self.draw_ui()
        print(f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}", end="", flush=True)

        while self.running:
            # Refresh automático da UI se o estado da ligação mudar
            current_uplink_state = (self.manager.uplink is not None)
            if current_uplink_state != last_uplink_state:
                self.draw_ui()
                print(f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}", end="", flush=True)
                last_uplink_state = current_uplink_state

            if select.select([sys.stdin], [], [], 0.5)[0]:
                line = sys.stdin.readline().strip()
                if not line: continue
                
                parts = line.split()
                cmd = parts[0].lower()

                if cmd == "scan":
                    scan_for_candidates(self.manager.adapter)
                    input("Enter para voltar...")
                    self.draw_ui()
                elif cmd == "conn":
                    if self.manager.find_and_connect_uplink():
                        self.wait_for_secure_connection()
                elif cmd == "msg":
                    if len(parts) < 2: print("Use: msg <texto>")
                    else:
                        txt = " ".join(parts[1:])
                        self.dtls_manager.send_data(SINK_NID, txt, client_id=self.my_client_id)
                elif cmd == "block":
                    if len(parts) < 2: print("Use: block <nid>")
                    else:
                        self.router.block_heartbeat(parts[1])
                        print(f"🚫 Heartbeats bloqueados para {parts[1]}")
                        time.sleep(1)
                elif cmd == "unblock":
                    if len(parts) < 2: print("Use: unblock <nid>")
                    else:
                        self.router.unblock_heartbeat(parts[1])
                        print(f"✅ Heartbeats desbloqueados para {parts[1]}")
                        time.sleep(1)
                elif cmd == "disc":
                    self.manager.disconnect_all()
                    self.on_uplink_death() # Força atualização da UI e Hops
                elif cmd == "cls":
                    self.draw_ui()
                elif cmd == "q":
                    self.running = False
                    os._exit(0)
                
                # Redesenhar prompt apenas se não foi 'cls'
                if cmd != "cls":
                    print(f"{C_BOLD}{C_GREEN}node@{MY_NID}# {C_END}", end="", flush=True)

if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    app = NodeApp()
    app.run_cli()