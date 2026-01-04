from common.security import SecurityManager
from common.dtls import DTLSManager
from common.gatt_server import GATTServerManager
from common.advertiser import NodeAdvertiser
from common.protocol import Packet, MSG_TYPE_HEARTBEAT
from node.router import Router
import dbus.mainloop.glib
import threading
import time
import asyncio
import sys
import json
from gi.repository import GLib

# --- CONFIGURAÇÃO ---
SINK_NID = "sink" 
CERT_PATH = "certs/sink.crt"
KEY_PATH = "certs/sink.key"
ROOT_CA_PATH = "certs/root_ca.crt"

class SinkCore:
    def __init__(self):
        print(f"[*] A iniciar Sink Core ({SINK_NID})...")
        
        self.sec_manager = SecurityManager(ROOT_CA_PATH, CERT_PATH, KEY_PATH)
        
        from common.manageConnections import ConnectionManager
        # MUDANÇA: adapter_index=0 para o Sink
        self.conn_manager = ConnectionManager(security_manager=self.sec_manager, adapter_index=0) 
        
        self.router = Router(SINK_NID, self.conn_manager, security_manager=self.sec_manager)
        
        self.bus = dbus.SystemBus()
        
        # --- MUDANÇA CRÍTICA: adapter_index=0 ---
        self.gatt_server = GATTServerManager(self.bus, adapter_index=0)
        
        self.gatt_server.set_data_callback(self.router.process_packet)
        self.router.set_gatt_server(self.gatt_server)
        
        # Advertiser também no 0
        self.advertiser = NodeAdvertiser(SINK_NID, hops=0, adapter_index=0)
        
        self.hb_running = False
        self.hb_thread = None

        self.dtls_manager = DTLSManager(SINK_NID, self.sec_manager, self.router.forward)
        self.router.set_app_callback(self.dtls_manager.process_packet)
        self.dtls_manager.register_service("Inbox", self.on_inbox_message)

    def on_inbox_message(self, source_nid, client_id, message):
        print(f"\n\U0001f4e8 [INBOX SERVICE] Recebido de {source_nid} (Client {client_id})")
        print(f"   Conteúdo: {message}")
        print("-" * 40)

    def start_background(self):
        self.gatt_server.register()
        self._start_advertiser()
        self._start_heartbeat()
        
        print("[SINK] ✅ Sistema Operacional. A aguardar conexões...")
        
        def run_loop():
            loop = GLib.MainLoop()
            try:
                loop.run()
            except:
                pass
        
        t = threading.Thread(target=run_loop, daemon=True)
        t.start()

    def _start_advertiser(self):
        def run_ad():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            new_loop.run_until_complete(self.advertiser.run())
        
        t = threading.Thread(target=run_ad, daemon=True)
        t.start()

    def _start_heartbeat(self):
        self.hb_running = True
        self.hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.hb_thread.start()

    def _heartbeat_loop(self):
        time.sleep(2)
        seq = 0
        while self.hb_running:
            time.sleep(5)
            if not self.router.downlink_keys:
                continue
            val_str = str(seq)
            
            try:
                signature = self.sec_manager.sign_data(val_str.encode('utf-8'))
                
                payload_dict = {
                    "val": val_str,
                    "sig": signature
                }
                payload_json = json.dumps(payload_dict)
                
            except Exception as e:
                print(f"[ERRO] Falha ao assinar Heartbeat: {e}")
                continue
                
            active_links = list(self.router.downlink_keys.keys())
            
            for neighbor_mac in active_links:
                pkt = Packet(
                    source_nid=SINK_NID,
                    dest_nid="BROADCAST", 
                    msg_type=MSG_TYPE_HEARTBEAT,
                    payload=payload_json,
                    seq_num=seq
                )
                target_nid = None
                for nid, mac in self.router.forwarding_table.items():
                    if mac == neighbor_mac:
                        target_nid = nid
                        break
                if target_nid:
                    pkt.dest_nid = target_nid
                    self.router.forward(pkt)
            seq += 1

    def stop(self):
        self.hb_running = False
        self.advertiser.stop()

    def print_menu(self):
        print("\n=== SINK CONTROL ===")
        print("1. Status")
        print("2. Block HB <nid>")
        print("3. Unblock HB <nid>")
        print("q. Quit")

    def run_cli(self):
        self.print_menu()
        while True:
            try:
                cmd_line = input("> ").strip().split()
                if not cmd_line: continue
                cmd = cmd_line[0].lower()
                
                if cmd == '1' or cmd == 'status':
                    print(f"Neighbors: {list(self.router.downlink_keys.keys())}")
                    print(f"Table: {self.router.forwarding_table}")
                    print(f"Blocked: {self.router.blocked_nids}")
                elif cmd == '2' or cmd == 'block':
                    if len(cmd_line) > 1: self.router.block_heartbeat(cmd_line[1])
                elif cmd == '3' or cmd == 'unblock':
                    if len(cmd_line) > 1: self.router.unblock_heartbeat(cmd_line[1])
                elif cmd == 'q':
                    self.stop()
                    sys.exit(0)
            except Exception as e:
                print(e)

if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    core = SinkCore()
    core.start_background()
    core.run_cli()