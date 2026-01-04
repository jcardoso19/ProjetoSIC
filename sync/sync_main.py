import asyncio
import time
import os
import threading
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

# Imports do projeto
from common.manageConnections import ConnectionManager
from common.advertiser import NodeAdvertiser
from common.gatt_server import GATTServerManager
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK

class SinkMain:
    def __init__(self):
        print("[SINK] A iniciar...")
        
        # 1. Configurar DBus Loop (Essencial para GATT e Advertiser)
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

        # 2. INICIAR GATT SERVER (A "Loja")
        # Isto cria o serviço real para o Nó encontrar
        try:
            self.gatt_server = GATTServerManager(self.bus)
            self.gatt_server.register()
            self.gatt_server.set_data_callback(self.on_data_received)
        except Exception as e:
            print(f"[ERRO] Falha ao iniciar GATT Server: {e}")

        # 3. INICIAR ADVERTISER (O "Cartaz")
        self.advertiser = NodeAdvertiser("SINK_DEVICE", hops=0)
        
        # Thread para correr o Loop do GLib (mantém o Server e o Advertiser vivos)
        self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
        self.loop_thread.start()
        
        # 4. Connection Manager (Lógica antiga, mantida para compatibilidade)
        self.manager = ConnectionManager(None, None, adapter_index=0)
        
        # Pequena pausa para garantir registo
        time.sleep(2)
        
        # Iniciar o Anúncio
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
        # Converte bytes brutos para objeto Packet
        packet = Packet.from_bytes(data_bytes)

        if not packet: 
            return

        # --- Lógica de Handshake (Já existia) ---
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

        # --- CORREÇÃO: Lógica para Dados (Adicionado) ---
        else:
            # Captura qualquer outro pacote (MSG, E2E_DATA, etc.)
            print(f"\n📨 [DADOS] Recebido pacote tipo '{packet.msg_type}' de {packet.source_nid}")
            print(f"   Payload (Raw/Cifrado): {packet.payload}")
            print("-" * 40)

if __name__ == "__main__":
    app = SinkMain()
    app.start()