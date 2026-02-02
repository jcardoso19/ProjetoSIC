import asyncio
import time
import os
import sys
import threading
import json
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

# Ajuste de path para imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.manageConnections import ConnectionManager
from common.advertiser import NodeAdvertiser
from common.gatt_server import GATTServerManager
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK, MSG_TYPE_HEARTBEAT, MSG_TYPE_DATA
from common.security import SecurityManager
from common.dtls import DTLSManager # IMPORTANTE: Adicionado suporte DTLS

class SinkMain:
    def __init__(self):
        print(f"[SINK] A iniciar...")
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()
        self.rx_buffer = bytearray() 
        self.my_nid = "SINK"

        # --- CHAVES ---
        self.sec_manager = self._load_keys()
        if not self.sec_manager:
            print("[SINK] ❌ ERRO: Chaves não encontradas!")
            sys.exit(1)

        # --- DTLS MANAGER (Para responder a 'msg <texto>') ---
        # send_callback: define como o DTLS envia pacotes de volta para a rede
        self.dtls_manager = DTLSManager(self.my_nid, self.sec_manager, self.send_packet_to_mesh)

        # --- GATT ---
        try:
            self.gatt_server = GATTServerManager(self.bus)
            self.gatt_server.register()
            self.gatt_server.set_data_callback(self.on_data_received)
        except Exception as e:
             print(f"[ERRO] GATT: {e}")
             sys.exit(1)

        self.advertiser = NodeAdvertiser("SIC_SINK_PRIMARY", hops=0)
        
        self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
        self.loop_thread.start()
        
        # Manager passivo
        self.manager = ConnectionManager(None, None, adapter_index=0)
        
        time.sleep(1)
        asyncio.run(self.advertiser.run())

        self.hb_running = True
        self.hb_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.hb_thread.start()
        print("[SINK] ✅ PRONTO (Link Layer + DTLS Ativo)")

    def _load_keys(self):
        candidates = ["certs", "../certs", "ProjetoSIC/certs", "sync/certs"]
        for d in candidates:
            if os.path.exists(os.path.join(d, "sink.key")):
                return SecurityManager(f"{d}/root_ca.crt", f"{d}/sink.crt", f"{d}/sink.key")
        return None

    def send_packet_to_mesh(self, packet):
        """Envia pacotes para a rede (seja resposta DTLS, Heartbeat, etc)."""
        # Se o pacote não tiver origem/destino definidos pelo DTLS, define aqui
        if not packet.source_nid: packet.source_nid = self.my_nid
        
        try:
            data_bytes = packet.to_bytes()
            full_payload = len(data_bytes).to_bytes(4, 'big') + data_bytes
            
            # Envio lento e seguro (20 bytes + delay)
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
        packet = Packet.from_bytes(data_bytes)
        if not packet: return

        # 1. Handshake Link Layer
        if packet.msg_type == MSG_TYPE_HELLO:
            print(f"[LINK] 🤝 Handshake Link-Layer de {packet.source_nid}")
            cert_pem = self.sec_manager.local_cert_pem.decode('utf-8')
            response = Packet("SINK", packet.source_nid, cert_pem, MSG_TYPE_HELLO_ACK)
            self.send_packet_to_mesh(response)

        # 2. Dados de Aplicação / DTLS
        elif packet.msg_type == MSG_TYPE_DATA:
            # Passa para o DTLS Manager processar (Handshake E2E ou Dados Cifrados)
            # Se for handshake, o DTLSManager gera a resposta e chama send_packet_to_mesh automaticamente
            decrypted_msg = self.dtls_manager.process_packet(packet)
            
            if decrypted_msg:
                # Se process_packet devolver algo, é uma mensagem de texto já decifrada
                print(f"{C_GREEN}[APP] 📩 MENSAGEM RECEBIDA de {packet.source_nid}: {decrypted_msg}{C_END}")
                
                # Opcional: Enviar eco de volta
                # self.dtls_manager.send_data(packet.source_nid, f"Recebido: {decrypted_msg}")

        elif packet.msg_type == MSG_TYPE_HEARTBEAT:
            pass
        else:
            print(f"[?] Msg desconhecida: {packet.msg_type}")

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
                    # Enviar heartbeat (descomentar se necessário, consome largura de banda)
                    self.send_packet_to_mesh(pkt) 
                except: pass
            time.sleep(5)

# Códigos de cor para o log do Sink ficar bonito
C_GREEN = "\033[92m"
C_END = "\033[0m"

if __name__ == "__main__":
    app = SinkMain()
    app.start()