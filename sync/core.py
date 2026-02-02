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
import os
from gi.repository import GLib

SINK_NID = "sink" 
CERT_PATH = "certs/sink.crt"
KEY_PATH = "certs/sink.key"
ROOT_CA_PATH = "certs/root_ca.crt"

C_BOLD    = "\033[1m"
C_GREEN   = "\033[92m"
C_BLUE    = "\033[94m"
C_YELLOW  = "\033[93m"
C_RED     = "\033[91m"
C_CYAN    = "\033[96m"
C_END     = "\033[0m"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

class SinkCore:
    def __init__(self):
        self.sec_manager = SecurityManager(ROOT_CA_PATH, CERT_PATH, KEY_PATH)
        
        from common.manageConnections import ConnectionManager
        self.conn_manager = ConnectionManager(security_manager=self.sec_manager, adapter_index=0) 
        
        self.router = Router(SINK_NID, self.conn_manager, security_manager=self.sec_manager)
        
        self.bus = dbus.SystemBus()
        self.gatt_server = GATTServerManager(self.bus, adapter_index=0)
        self.gatt_server.set_data_callback(self.router.process_packet)
        self.gatt_server.set_disconnect_callback(self.router.drop_connection)
        self.router.set_gatt_server(self.gatt_server)
        
        self.advertiser = NodeAdvertiser(SINK_NID, hops=0, adapter_index=0)
        
        self.hb_running = False
        self.hb_thread = None

        self.dtls_manager = DTLSManager(SINK_NID, self.sec_manager, self.router.forward)
        self.router.set_app_callback(self.dtls_manager.process_packet)
        self.dtls_manager.register_service("Inbox", self.on_inbox_message)
        self.dtls_manager.register_service("NetworkManager", self.handle_network_query)
        

    def draw_ui(self):
        clear_screen()
        
        n_neighbors = len(self.router.downlink_keys)
        neigh_status = f"{C_GREEN}{n_neighbors} Active{C_END}" if n_neighbors > 0 else f"{C_YELLOW}0 Waiting{C_END}"
        
        adv_status = f"{C_GREEN}ON (Hops: 0){C_END}" if self.advertiser.is_running else f"{C_RED}OFF{C_END}"
        
        print(f"{C_BOLD}{C_CYAN}══════════════════════════════════════════════════════════{C_END}")
        print(f"       {C_BOLD}SIC PROTOCOL - SINK GATEWAY{C_END}")
        print(f"       Node ID: {SINK_NID} | Role: Root Authority")
        print(f"{C_BOLD}{C_CYAN}══════════════════════════════════════════════════════════{C_END}")
        print(f" Status: [Neighbors: {neigh_status}] [Advertiser: {adv_status}] [Sec: {C_GREEN}READY{C_END}]")
        print(f"{C_CYAN}──────────────────────────────────────────────────────────{C_END}")
        print(f" MENU: {C_YELLOW}status{C_END}, {C_YELLOW}block <id>{C_END}, {C_YELLOW}unblock <id>{C_END}, {C_YELLOW}cls{C_END}, {C_YELLOW}q{C_END}")
        print(f"{C_CYAN}──────────────────────────────────────────────────────────{C_END}")

    def safe_print(self, msg):
        """Imprime sem destruir o prompt (Igual ao _print_safe do Router)"""
        prompt = f"{C_BOLD}{C_RED}sink#{C_END} "
        sys.stdout.write(f"\r{msg}\n{prompt}")
        sys.stdout.flush()

    def on_inbox_message(self, source_nid, client_id, message):
        msg_box =  f"\n {C_GREEN}╔══════════════════════════════════════════════════╗{C_END}\n"
        msg_box += f" {C_GREEN}║ 📩 INBOX MESSAGE RECEIVED                        ║{C_END}\n"
        msg_box += f" {C_GREEN}╠══════════════════════════════════════════════════╣{C_END}\n"
        msg_box += f" ║ {C_BOLD}From:{C_END} {source_nid:<39}    ║\n"
        msg_box += f" ║ {C_BOLD}Text:{C_END} {message:<39}    ║\n"
        msg_box += f" {C_GREEN}╚══════════════════════════════════════════════════╝{C_END}"
        
        self.safe_print(msg_box)

    def start_background(self):
        self.gatt_server.register()
        self._start_advertiser()
        self._start_heartbeat()
        
        def run_loop():
            loop = GLib.MainLoop()
            try: loop.run()
            except: pass
        
        t = threading.Thread(target=run_loop, daemon=True)
        t.start()
        
        self.draw_ui()

    def _start_advertiser(self):
        def run_ad():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                self.advertiser.is_running = True # Flag para UI
                new_loop.run_until_complete(self.advertiser.run())
            except:
                self.advertiser.is_running = False
        
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
                payload_dict = {"val": val_str, "sig": signature}
                payload_json = json.dumps(payload_dict)
            except Exception as e:
                self.safe_print(f"{C_RED}[ERROR] Sign Fail: {e}{C_END}")
                continue
                
            active_links = list(self.router.downlink_keys.keys())
            for neighbor_mac in active_links:
                pkt = Packet(SINK_NID, "BROADCAST", payload_json, MSG_TYPE_HEARTBEAT)
                pkt.seq_num = seq
                
                target_nid = next((nid for nid, mac in self.router.forwarding_table.items() if mac == neighbor_mac), None)
                if target_nid:
                    pkt.dest_nid = target_nid
                    self.router.forward(pkt)

            seq += 1

    def stop(self):
        self.hb_running = False
        self.advertiser.stop()

    def run_cli(self):
        while True:
            try:
                cmd_line = input(f"{C_BOLD}{C_RED}sink#{C_END} ").strip().split()
                
                if not cmd_line: continue
                cmd = cmd_line[0].lower()
                
                if cmd == 'status':
                    print(f"\n{C_CYAN}--- NETWORK STATUS ---{C_END}")
                    if not self.router.forwarding_table:
                        print(" No nodes connected.")
                    else:
                        for nid, conn in self.router.forwarding_table.items():
                            print(f" > {C_BOLD}{nid}{C_END} (Link: {conn})")
                    print(f"{C_CYAN}----------------------{C_END}")
                    
                elif cmd == 'block':
                    if len(cmd_line) > 1: 
                        self.router.block_heartbeat(cmd_line[1])
                        print(f"{C_YELLOW}[TEST] Blocked HB for {cmd_line[1]}{C_END}")
                        
                elif cmd == 'unblock':
                    if len(cmd_line) > 1: 
                        self.router.unblock_heartbeat(cmd_line[1])
                        print(f"{C_GREEN}[TEST] Unblocked HB for {cmd_line[1]}{C_END}")

                elif cmd == 'cls':
                    self.draw_ui()

                elif cmd == 'q':
                    print(f"Shutting down...")
                    self.stop()
                    sys.exit(0)
            except Exception as e:
                print(f"{C_RED}Error: {e}{C_END}")
    def handle_network_query(self, source_nid, client_id, message):
        if message == "LIST_NODES":
            all_nodes = list(self.router.forwarding_table.keys())
            if SINK_NID not in all_nodes:
                all_nodes.append(SINK_NID)
        
            response_payload = json.dumps(all_nodes)
        
            self.safe_print(f"[REDE] Nó {source_nid} pediu a lista de membros.")
        
            self.dtls_manager.send_data(source_nid, response_payload, service="NetworkManager")
if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    core = SinkCore()
    core.start_background()
    core.run_cli()