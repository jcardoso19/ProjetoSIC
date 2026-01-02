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
        
        # 1. Segurança
        try:
            self.sec_manager = SecurityManager(ROOT_CA_PATH, CERT_PATH, KEY_PATH)
        except Exception as e:
            print(f"[ERRO] Falha ao carregar segurança: {e}")
            sys.exit(1)

        # 2. Connection Manager
        self.manager = ConnectionManager(security_manager=self.sec_manager, adapter_index=0)
        
        # 3. Router
        self.router = Router(MY_NID, self.manager, security_manager=self.sec_manager)
        self.manager.set_router_callback(self.router.process_packet)
        
        # 4. DTLS
        self.dtls_manager = DTLSManager(MY_NID, self.sec_manager, self.router.forward)
        self.router.set_app_callback(self.dtls_manager.process_packet)

        # 5. Heartbeat
        self.hb_monitor = HeartbeatManager(self.manager, timeout_seconds=7)
        self.router.on_heartbeat = lambda nid: self.hb_monitor.beat_received()
        
        # 6. GATT Server
        self.setup_gatt()
        
        # Estado
        self.handshake_started = False
        self.my_client_id = random.randint(1000, 9999)

    def setup_gatt(self):
        def run_gatt_server():
            try:
                # dbus.mainloop.glib.DBusGMainLoop(set_as_default=True) # Already set in main?
                bus = dbus.SystemBus()
                gatt_server = GATTServerManager(bus)
                gatt_server.set_data_callback(self.router.process_packet)
                gatt_server.register()
                self.router.set_gatt_server(gatt_server)
                
                # Advertise with Hops=99 initially, until connected
                advertiser = NodeAdvertiser(MY_NID, hops=99)
                
                from gi.repository import GLib
                loop = GLib.MainLoop()
                
                async def start_ad():
                    await advertiser.run()
                
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
        print("1. Status (Table, Uplink, Downlinks, Stats)")
        print("2. Scan (Find nearby devices)")
        print("3. Connect (Auto-connect to best Uplink)")
        print("4. Send <msg> (Send secure message to Sink)")
        print("5. Block HB <nid> (Stop forwarding HB to Node)")
        print("6. Unblock HB <nid>")
        print("7. Disconnect")
        print("h. Help")
        print("q. Quit")
        print("="*40)

    def print_status(self):
        print(f"\n--- STATUS ({MY_NID}) ---")
        
        # Uplink
        up_status = "DISCONNECTED"
        up_nid = "N/A"
        if self.manager.uplink:
            up_status = "CONNECTED"
            if self.manager.uplink_info:
                up_nid = self.manager.uplink_info.get('name', 'Unknown')
        print(f"⬆️  Uplink: {up_status} ({up_nid})")
        
        # Downlinks
        downlinks = []
        for nid, conn in self.router.forwarding_table.items():
            if isinstance(conn, str): # É um MAC (Downlink)
                downlinks.append(nid)
        print(f"⬇️  Downlinks: {downlinks}")
        
        # Stats
        print(f"💓 Heartbeats Lost: {self.hb_monitor.missed_count}")
        print(f"📨Routed Messages (Up): {self.router.routed_messages_count}")
        
        # Tables
        print("\n📍 Forwarding Table:")
        for nid, conn in self.router.forwarding_table.items():
            target = "Uplink" if conn == self.manager.uplink else f"Downlink ({conn})"
            print(f"   - {nid} -> {target}")

    def run_cli(self):
        self.print_menu()
        while self.running:
            try:
                cmd_line = input("\n> ").strip().split()
                if not cmd_line:
                    continue
                
                cmd = cmd_line[0].lower()
                
                if cmd == '1' or cmd == 'status':
                    self.print_status()
                    
                elif cmd == '2' or cmd == 'scan':
                    print("[SCAN] Scanning for potential Uplinks...")
                    self.candidates = scan_for_candidates(self.manager.adapter)
                    print(f"[SCAN] Found {len(self.candidates)} candidates:")
                    for idx, c in enumerate(self.candidates):
                        print(f"   {idx}. {c['name']} (Hops: {c['hops']}, RSSI: {c['rssi']})")
                        
                elif cmd == '3' or cmd == 'connect':
                    print("[CLI] Attempting to find and connect to best Uplink...")
                    if self.manager.uplink:
                         print("[CLI] Already connected. Disconnecting first...")
                         self.manager.disconnect_all()
                         time.sleep(1)

                    if self.manager.find_and_connect_uplink():
                         self.hb_monitor.start()
                         self.handshake_started = False
                         print("[CLI] ✅ Connected successfully!")
                    else:
                         print("[CLI] ❌ Failed to connect.")

                elif cmd == '4' or cmd == 'send':
                    msg = " ".join(cmd_line[1:])
                    if not msg:
                        print("Use: send <message>")
                        continue
                    if SINK_NID in self.dtls_manager.sessions:
                        self.dtls_manager.send_data(SINK_NID, msg, client_id=self.my_client_id)
                    else:
                        print("[CLI] No Secure Session with Sink yet. Wait for handshake.")

                elif cmd == '5' or cmd == 'block':
                    if len(cmd_line) < 2:
                         print("Use: block <nid>")
                         continue
                    self.router.block_heartbeat(cmd_line[1])

                elif cmd == '6' or cmd == 'unblock':
                    if len(cmd_line) < 2:
                         print("Use: unblock <nid>")
                         continue
                    self.router.unblock_heartbeat(cmd_line[1])

                elif cmd == '7' or cmd == 'disconnect':
                    self.manager.disconnect_all()
                    self.hb_monitor.stop()
                    print("[CLI] Disconnected.")

                elif cmd == 'q' or cmd == 'quit':
                    self.running = False
                    self.manager.disconnect_all()
                    sys.exit(0)
                    
                elif cmd == 'h' or cmd == 'help':
                    self.print_menu()
                
            except Exception as e:
                print(f"[CLI] Error: {e}")

    def main_loop(self):
        cli_thread = threading.Thread(target=self.run_cli, daemon=True)
        cli_thread.start()
        
        print("[MAIN] Background loop running...")
        while self.running:
            # Auto Handshake logic
            if self.manager.uplink and self.manager.session_key:
                 if not self.handshake_started:
                     self.dtls_manager.start_handshake(SINK_NID)
                     self.handshake_started = True
            
            time.sleep(1)

if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    app = NodeApp()
    app.main_loop()
