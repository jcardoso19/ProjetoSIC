import asyncio
import time
import os
import sys
import threading
import json
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

# Ajustar path para encontrar modulos common se corrido da pasta sync
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.manageConnections import ConnectionManager
from common.advertiser import NodeAdvertiser
from common.gatt_server import GATTServerManager
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK, MSG_TYPE_HEARTBEAT
from common.security import SecurityManager

class SinkMain:
    def __init__(self):
        print(f"[SINK] A iniciar em: {os.getcwd()}")
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()
        self.rx_buffer = bytearray() 

        # --- DIAGNÓSTICO DE CHAVES (CRÍTICO) ---
        # Tenta encontrar as chaves em várias pastas possíveis
        candidates = [
            "certs", 
            "../certs", 
            "ProjetoSIC/certs",
            os.path.join(os.path.dirname(__file__), '../certs')
        ]
        
        cert_dir = None
        for d in candidates:
            if os.path.exists(os.path.join(d, "sink.key")):
                cert_dir = d
                break
        
        if not cert_dir:
            print("\n❌❌❌ ERRO FATAL: Pasta 'certs' NÃO ENCONTRADA! ❌❌❌")
            print("O Sink não consegue carregar as chaves. O Handshake vai falhar.")
            print("Verifica se estás na pasta certa ou se a pasta 'certs' existe.")
            sys.exit(1)

        print(f"[SEC] A carregar chaves de: {cert_dir}")
        try:
            self.sec_manager = SecurityManager(
                f"{cert_dir}/root_ca.crt", 
                f"{cert_dir}/sink.crt", 
                f"{cert_dir}/sink.key"
            )
            print(f"[SEC] ✅ Chaves carregadas com sucesso.")
        except Exception as e:
            print(f"[SEC] ❌ Erro ao carregar chaves: {e}")
            sys.exit(1)

        try:
            self.gatt_server = GATTServerManager(self.bus)
            self.gatt_server.register()
            self.gatt_server.set_data_callback(self.on_data_received)
        except Exception as e: print(f"[ERRO] GATT: {e}")

        # Usei o nome que apareceu no teu log para consistência
        self.advertiser = NodeAdvertiser("SIC_NODE_TEST_SERVER", hops=0)
        
        self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
        self.loop_thread.start()

        self.manager = ConnectionManager(None, None, adapter_index=0)
        time.sleep(2)
        asyncio.run(self.advertiser.run())

        self.hb_running = True
        self.hb_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.hb_thread.start()
        print("[SINK] ✅ Sink PRONTO e a enviar Heartbeats!")

    def start(self):
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            self.hb_running = False
            self.loop.quit()

    def send_packet_to_mesh(self, packet):
        try:
            data_bytes = packet.to_bytes()
            full_payload = len(data_bytes).to_bytes(4, 'big') + data_bytes
            
            # 20 bytes e delay de 0.05s para garantir que o Node processa
            CHUNK_SIZE = 20
            for i in range(0, len(full_payload), CHUNK_SIZE):
                self.gatt_server.send_data(full_payload[i : i + CHUNK_SIZE])
                time.sleep(0.05) 
        except Exception as e:
            print(f"[TX] Erro: {e}")

    def on_data_received(self, data_bytes, *args):
        self.rx_buffer.extend(data_bytes)
        while len(self.rx_buffer) >= 4:
            msg_len = int.from_bytes(self.rx_buffer[:4], 'big')
            if len(self.rx_buffer) < 4 + msg_len: break
            
            packet_bytes = bytes(self.rx_buffer[4 : 4 + msg_len])
            del self.rx_buffer[:4 + msg_len]
            self.process_complete_packet(packet_bytes)

    def process_complete_packet(self, data_bytes):
        try:
            packet = Packet.from_bytes(data_bytes)
            if not packet: return

            if packet.msg_type == MSG_TYPE_HELLO:
                print(f"[SEC] 🤝 Handshake recebido de {packet.source_nid}")
                if self.sec_manager:
                    cert_payload = self.sec_manager.local_cert_pem.decode('utf-8')
                    response = Packet("SINK", packet.source_nid, cert_payload, MSG_TYPE_HELLO_ACK)
                    print(f"[SEC] A enviar HELLO_ACK ({len(response.payload)} bytes)...")
                    self.send_packet_to_mesh(response)
                    print(f"[SEC] ✅ HELLO_ACK enviado.")
                else:
                    print("[SEC] ❌ ERRO: Recebi HELLO mas não tenho chaves para responder!")
            elif packet.msg_type == MSG_TYPE_HEARTBEAT:
                pass
            else:
                print(f"[MSG] Recebido '{packet.msg_type}' de {packet.source_nid}")
        except Exception as e:
            print(f"[PROCESS] Erro: {e}")

    def heartbeat_loop(self):
        seq = 0
        while self.hb_running:
            if self.sec_manager:
                seq += 1
                try:
                    val = str(seq)
                    sig = self.sec_manager.sign_data(val.encode('utf-8'))
                    payload = json.dumps({"val": val, "sig": sig})
                    pkt = Packet("SINK", "BROADCAST", payload, MSG_TYPE_HEARTBEAT, seq_num=seq)
                    self.send_packet_to_mesh(pkt)
                except: pass
            time.sleep(5)

if __name__ == "__main__":
    app = SinkMain()
    app.start()