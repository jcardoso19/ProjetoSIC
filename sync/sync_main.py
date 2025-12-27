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
# IMPORT NOVO:
from common.gatt_server import GATTServerManager

class SinkMain:
    def __init__(self):
        print("[SINK] A iniciar...")
        
        # 1. Configurar DBus Loop (Essencial para GATT e Advertiser)
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()

        # 2. INICIAR GATT SERVER (A "Loja")
        # Isto cria o serviço real para o Nó encontrar
        try:
            self.gatt_server = GATTServerManager(self.bus)
            self.gatt_server.register()
        except Exception as e:
            print(f"[ERRO] Falha ao iniciar GATT Server: {e}")

        # 3. INICIAR ADVERTISER (O "Cartaz")
        self.advertiser = NodeAdvertiser("SINK_DEVICE", hops=0)
        
        # Thread para correr o Loop do GLib (mantém o Server e o Advertiser vivos)
        self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
        self.loop_thread.start()
        
        # 4. Connection Manager (Lógica antiga, mantemos para compatibilidade)
        # Nota: Agora o GATT Server trata dos dados recebidos via BLE direto
        # Mas mantemos isto caso uses lógica de rede mesh
        self.manager = ConnectionManager(None, None, adapter_index=0)
        
        # Pequena pausa para garantir registo
        time.sleep(2)
        
        # Iniciar o Anuncio
        # Nota: O Advertiser agora só precisa de registar, o loop já corre
        asyncio.run(self.advertiser.run())

        print("[SINK] ✅ Sink Ativo, Visível e com Serviço SIC!")

    def start(self):
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            print("\n[SINK] A desligar.")
            self.loop.quit()

if __name__ == "__main__":
    app = SinkMain()
    app.start()