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
        
        # --- SEGURANÇA: Carregar Chaves ---
        try:
            # O Sink usa o SecurityManager para assinar os heartbeats
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

        # Manager para (eventuais) conexões, embora o Sink seja passivo maioritariamente
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

    def heartbeat_loop(self):
        """Envia um Heartbeat assinado a cada 5 segundos para todos os vizinhos."""
        seq_num = 0
        while self.hb_running:
            if self.sec_manager:
                seq_num += 1
                try:
                    # Payload: Valor do contador + Assinatura Digital
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

                    # Envia para todos os dispositivos ligados via Notificação BLE
                    # (O GATTServerManager trata de enviar para quem subscreveu)
                    self.gatt_server.send_data(packet.to_bytes())
                    print(f"[HB] 💓 Heartbeat #{seq_num} enviado (Assinado).")

                except Exception as e:
                    print(f"[HB] Erro ao enviar: {e}")
            
            time.sleep(5)

    def on_data_received(self, data_bytes):
        packet = Packet.from_bytes(data_bytes)
        if not packet: return

        if packet.msg_type == MSG_TYPE_HELLO:
            print(f"[SEC] Pedido de Handshake de {packet.source_nid}")
            
            # Enviar HELLO_ACK com o certificado do Sink
            if self.sec_manager and self.sec_manager.local_cert_pem:
                cert_payload = self.sec_manager.local_cert_pem.decode('utf-8')
                response = Packet("SINK", packet.source_nid, cert_payload, MSG_TYPE_HELLO_ACK)
                self.gatt_server.send_data(response.to_bytes())
        else:
            print(f"\n📨 [DADOS] Recebido '{packet.msg_type}' de {packet.source_nid} | Payload: {packet.payload[:50]}...")

if __name__ == "__main__":
    app = SinkMain()
    app.start()