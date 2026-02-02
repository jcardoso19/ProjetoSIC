import asyncio
import time
import os
import threading
import json
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

from common.manageConnections import ConnectionManager
from common.advertiser import NodeAdvertiser
from common.gatt_server import GATTServerManager
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK, MSG_TYPE_HEARTBEAT
from common.security import SecurityManager

class SinkMain:
    def __init__(self):
        print("[SINK] A iniciar...")
        
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()
        
        # Buffer para remontar mensagens fragmentadas
        self.rx_buffer = bytearray()

        # --- SEGURANÇA: Carregar Chaves ---
        try:
            self.sec_manager = SecurityManager("certs/root_ca.crt", "certs/sink.crt", "certs/sink.key")
            print(f"[SEC] Chaves do Sink carregadas com sucesso.")
        except Exception as e:
            print(f"[ERRO] Falha ao carregar segurança do Sink: {e}")
            self.sec_manager = None

        # --- BLUETOOTH: GATT Server ---
        try:
            self.gatt_server = GATTServerManager(self.bus)
            self.gatt_server.register()
            self.gatt_server.set_data_callback(self.on_data_received)
        except Exception as e:
            print(f"[ERRO] Falha ao iniciar GATT Server: {e}")

        # --- BLUETOOTH: Advertiser (Hops = 0 porque sou o Sink) ---
        self.advertiser = NodeAdvertiser("SINK_DEVICE", hops=0)
        
        # Iniciar loop do DBus numa thread separada
        self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
        self.loop_thread.start()

        # Manager passivo
        self.manager = ConnectionManager(None, None, adapter_index=0)
        
        time.sleep(2)

        # Iniciar Anúncio BLE
        asyncio.run(self.advertiser.run())

        # --- HEARTBEAT: Iniciar Thread de Envio ---
        self.hb_running = True
        self.hb_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.hb_thread.start()

        print("[SINK] Sink Ativo, Visível e a enviar Heartbeats!")

    def start(self):
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            print("\n[SINK] A desligar.")
            self.hb_running = False
            self.loop.quit()

    def send_packet_to_mesh(self, packet):
        """Função auxiliar para enviar pacotes com o cabeçalho de tamanho correto."""
        try:
            data_bytes = packet.to_bytes()
            # ADICIONAR CABEÇALHO DE 4 BYTES (CRÍTICO: O Nó espera isto!)
            full_payload = len(data_bytes).to_bytes(4, 'big') + data_bytes
            
            # Enviar fragmentado para garantir entrega
            CHUNK_SIZE = 20
            for i in range(0, len(full_payload), CHUNK_SIZE):
                self.gatt_server.send_data(full_payload[i : i + CHUNK_SIZE])
                time.sleep(0.02) # Pequena pausa para o BlueZ respirar
        except Exception as e:
            print(f"[SINK-TX] Erro ao enviar: {e}")

    def heartbeat_loop(self):
        seq_num = 0
        while self.hb_running:
            if self.sec_manager:
                seq_num += 1
                try:
                    val_str = str(seq_num)
                    signature = self.sec_manager.sign_data(val_str.encode('utf-8'))
                    
                    payload_json = json.dumps({
                        "val": val_str,
                        "sig": signature
                    })

                    packet = Packet(
                        source_nid="SINK",
                        dest_nid="BROADCAST",
                        msg_type=MSG_TYPE_HEARTBEAT,
                        seq_num=seq_num,
                        payload=payload_json
                    )

                    self.send_packet_to_mesh(packet)
                    print(f"[HB] 💓 Heartbeat #{seq_num} enviado.")

                except Exception as e:
                    print(f"[HB] Erro ao enviar: {e}")
            
            time.sleep(5)

    def on_data_received(self, data_bytes):
        """Lógica de remontagem de pacotes (igual ao Node)."""
        self.rx_buffer.extend(data_bytes)
        
        while len(self.rx_buffer) >= 4:
            # Ler o tamanho esperado (4 primeiros bytes)
            msg_len = int.from_bytes(self.rx_buffer[:4], 'big')
            
            if len(self.rx_buffer) < 4 + msg_len:
                break # Ainda não chegou tudo
            
            # Extrair pacote completo
            packet_bytes = bytes(self.rx_buffer[4 : 4 + msg_len])
            del self.rx_buffer[:4 + msg_len]
            
            self.process_complete_packet(packet_bytes)

    def process_complete_packet(self, data_bytes):
        packet = Packet.from_bytes(data_bytes)
        if not packet: return

        if packet.msg_type == MSG_TYPE_HELLO:
            print(f"[SEC] 🤝 Pedido de Handshake recebido de {packet.source_nid}")
            
            if self.sec_manager and self.sec_manager.local_cert_pem:
                cert_payload = self.sec_manager.local_cert_pem.decode('utf-8')
                response = Packet("SINK", packet.source_nid, cert_payload, MSG_TYPE_HELLO_ACK)
                
                # Usar a nova função de envio seguro
                self.send_packet_to_mesh(response)
                print(f"[SEC] ✅ HELLO_ACK enviado para {packet.source_nid}")
        
        elif packet.msg_type == MSG_TYPE_E2E_HELLO:
             # Se quisermos implementar o Sink como endpoint DTLS, seria aqui.
             # Para já, apenas faz print.
             print(f"[DTLS] Pedido de túnel E2E de {packet.source_nid}")

        else:
            print(f"\n📨 [DADOS] Recebido '{packet.msg_type}' de {packet.source_nid}")

if __name__ == "__main__":
    app = SinkMain()
    app.start()