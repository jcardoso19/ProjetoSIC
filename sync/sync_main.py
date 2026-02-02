import asyncio
import time
import os
import threading
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

from common.manageConnections import ConnectionManager
from common.advertiser import NodeAdvertiser
from common.gatt_server import GATTServerManager
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK

class SinkMain:
    def __init__(self):
        print("[SINK] A iniciar...")
        
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()
        self.sink_cert_bytes = b"ERRO_SEM_CERT"
        try:
            with open("certs/sink.crt", "rb") as f:
                self.sink_cert_bytes = f.read()
            print(f"[SEC] Certificado carregado ({len(self.sink_cert_bytes)} bytes).")
        except Exception as e:
            print(f"[ERRO] Não encontrei o certificado do sink: {e}")

        try:
            self.gatt_server = GATTServerManager(self.bus)
            self.gatt_server.register()
            self.gatt_server.set_data_callback(self.on_data_received)
        except Exception as e:
            print(f"[ERRO] Falha ao iniciar GATT Server: {e}")

        self.advertiser = NodeAdvertiser("SINK_DEVICE", hops=0)
        
        self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
        self.loop_thread.start()
        

        self.manager = ConnectionManager(None, None, adapter_index=0)
        
        time.sleep(2)

        asyncio.run(self.advertiser.run())

        print("[SINK] Sink Ativo, Visível e com Serviço SIC!")

    def start(self):
        try:
            print("[SINK] Loop principal a correr...")
            self.loop.run()
        except KeyboardInterrupt:
            print("\n[SINK] A desligar.")
            self.loop.quit()

    def on_data_received(self, data_bytes):
        packet = Packet.from_bytes(data_bytes)

        if not packet: 
            return

        if packet.msg_type == MSG_TYPE_HELLO:
            print(f"[SEC] Recebi Pedido de Handshake (HELLO) de {packet.source_nid}!")
            
            cert_payload = self.sink_cert_bytes.decode('utf-8') 

            response = Packet(
                source_nid="SINK",
                dest_nid=packet.source_nid,
                msg_type=MSG_TYPE_HELLO_ACK,
                payload=cert_payload
            )
            print("[SINK] A enviar HELLO_ACK")
            self.gatt_server.send_data(response.to_bytes())

        else:
            print(f"\n📨 [DADOS] Recebido pacote tipo '{packet.msg_type}' de {packet.source_nid}")
            print(f"   Payload (Raw/Cifrado): {packet.payload}")
            print("-" * 40)

if __name__ == "__main__":
    app = SinkMain()
    app.start()