import sys
import time
import os
import signal
import threading
import json
import dbus.mainloop.glib
from gi.repository import GLib

# --- Módulos do Projeto ---
from common.advertiser import SICAdvertiser
from common.gatt_server import Application, SICService
from common.manageConnections import ConnectionManager
from common.protocol import Packet, MSG_TYPE_DATA, MSG_TYPE_HEARTBEAT
from node.heartbeat_manager import HeartbeatManager

# --- Criptografia ---
from cryptography import x509
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend

# Configurações
NODE_ID = "SIC_NODE_01" 
CERT_PATH = "support/certs/node1.crt"
KEY_PATH  = "support/certs/node1.key"
SINK_CERT_PATH = "support/certs/sink.crt"

def load_credentials():
    print(f"[INIT] A carregar identidade de: {CERT_PATH}")
    if not os.path.exists(CERT_PATH):
        sys.exit(f"❌ ERRO: Certificado não encontrado em {CERT_PATH}")
    with open(CERT_PATH, "rb") as f:
        cert_bytes = f.read()

    if not os.path.exists(KEY_PATH):
        sys.exit(f"❌ ERRO: Chave privada não encontrada em {KEY_PATH}")
    with open(KEY_PATH, "rb") as f:
        key_data = f.read()
        priv_key = serialization.load_pem_private_key(
            key_data, password=None, backend=default_backend()
        )
    
    # Carregar Chave Pública do Sink (Para E2E Encryption)
    sink_pub_key = None
    if os.path.exists(SINK_CERT_PATH):
        with open(SINK_CERT_PATH, "rb") as f:
            sink_cert = x509.load_pem_x509_certificate(f.read(), default_backend())
            sink_pub_key = sink_cert.public_key()
            print("[INIT] 🔒 Certificado do Sink carregado (E2E pronto).")
    else:
        print("[WARN] ⚠️ Certificado do Sink não encontrado! E2E falhará.")

    return cert_bytes, priv_key, sink_pub_key

class NodeApp:
    def __init__(self):
        self.cert_bytes, self.priv_key, self.sink_pub_key = load_credentials()
        
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.mainloop = GLib.MainLoop()

        # Cliente (Uplink) - Usa adaptador hci1 (index 1) se disponível
        self.connection_manager = ConnectionManager(
            cert_bytes=self.cert_bytes, 
            priv_key=self.priv_key, 
            adapter_index=1 
        )
        self.connection_manager.set_router_callback(self.on_packet_received)

        # Heartbeat Manager
        self.hb_manager = HeartbeatManager(self.connection_manager, timeout_seconds=16)

        # Servidor (Downlinks)
        self.app = Application(self.bus)
        self.service = SICService(self.bus, 0, self.on_packet_received, self.cert_bytes, self.priv_key)
        self.app.add_service(self.service)

        self.advertiser = SICAdvertiser(self.bus, 0, NODE_ID)
        
        self.running = True
        self.routing_table = {} 
        self.routed_count = 0

    def start(self):
        print(f"\n🚀 [SYSTEM] {NODE_ID} PRONTO! (Segurança E2E + Heartbeats Ativos)")
        self.service.register(self.app.get_path())
        self.advertiser.register()
        threading.Thread(target=self.manage_uplink, daemon=True).start()
        threading.Thread(target=self.menu_loop, daemon=True).start()
        try:
            self.mainloop.run()
        except KeyboardInterrupt:
            self.stop()

    def encrypt_e2e(self, message):
        """
        Cria um túnel seguro (DTLS Simulado).
        """
        if not self.sink_pub_key:
            return f"[UNSECURE] {message}"

        # 1. Gerar minha chave temporária
        eph_priv = ec.generate_private_key(ec.SECP521R1(), default_backend())
        eph_pub_bytes = eph_priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        # 2. Derivar chave
        shared_secret = eph_priv.exchange(ec.ECDH(), self.sink_pub_key)
        key_e2e = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b'sic-e2e', backend=default_backend()
        ).derive(shared_secret)

        # 3. Encriptar
        aes = AESGCM(key_e2e)
        nonce = os.urandom(12)
        ciphertext = aes.encrypt(nonce, message.encode('utf-8'), None)

        # 4. Envelope JSON
        envelope = {
            "e2e": True,
            "k": eph_pub_bytes,
            "n": nonce.hex(),
            "c": ciphertext.hex()
        }
        return json.dumps(envelope)

    def menu_loop(self):
        """Interface que espera pela conexão antes de mostrar opções"""
        time.sleep(1) # Esperar logs de arranque

        # --- FASE 1: BLOQUEIO ATÉ CONECTAR ---
        print("\n⏳ [SYSTEM] A aguardar conexão inicial ao Sink...")
        while self.running and self.connection_manager.uplink is None:
            time.sleep(1)
        
        print("\n✅ [SYSTEM] Conexão Estabelecida! A carregar menu...")
        time.sleep(2) # Pausa para ler os logs de sucesso

        # --- FASE 2: MENU INTERATIVO ---
        while self.running:
            # Se a conexão cair, avisar mas não crashar
            if not self.connection_manager.uplink:
                 print("\n⚠️ [AVISO] Uplink perdido! A tentar reconectar em segundo plano...")
                 # Opcional: Bloquear aqui novamente se quiseres ser estrito
                 while self.running and self.connection_manager.uplink is None:
                    time.sleep(1)
                 print("\n✅ [SYSTEM] Reconectado!")

            print("\n" + "="*30)
            print(f"   MENU PRINCIPAL ({NODE_ID})")
            print("="*30)
            print("1. 📊 Ver Estado do Nó")
            print("2. 📩 Enviar Mensagem para o Sink (E2E)")
            print("3. 🗺️  Ver Tabela de Routing")
            print("4. ❌ Sair")
            print("="*30)
            try:
                choice = input("Escolha uma opção: ")
            except: break

            if choice == '1': self.print_status()
            elif choice == '2': self.send_user_message()
            elif choice == '3': self.print_routing_table()
            elif choice == '4':
                os.kill(os.getpid(), signal.SIGINT)
            else:
                print("Opção inválida.")
            time.sleep(0.5)

    def print_status(self):
        print("\n--- 📊 ESTADO DO NÓ ---")
        up = self.connection_manager.uplink
        if up:
            name = self.connection_manager.uplink_info.get('name', 'Unknown')
            hops = self.connection_manager.uplink_info.get('hops', '?')
            print(f"⬆️  UPLINK: '{name}' (Hops: {hops})")
            print(f"   💓 Heartbeats Perdidos: {self.hb_manager.missed_count}")
        else:
            print(f"⬆️  UPLINK: ❌ Desconectado")
        
        # Downlinks
        sic_char = self.service.characteristics[0]
        sessions = sic_char.sessions
        print(f"⬇️  DOWNLINKS: {len(sessions)} conectados.")
        
        print(f"cp  STATS: Mensagens Reencaminhadas: {self.routed_count}")
        print("-----------------------")

    def print_routing_table(self):
        print("\n--- 🗺️ TABELA DE ROUTING ---")
        if not self.routing_table: print("(Vazia)")
        else:
            for nid, hop in self.routing_table.items():
                print(f"📍 Destino: {nid}  --> Via: {hop}")
        print("----------------------------")

    def send_user_message(self):
        if not self.connection_manager.uplink:
            print("❌ ERRO: Não conectado!")
            return
        msg = input("✍️  Escreve a mensagem: ")
        
        print("🔒 A encriptar End-to-End para o Sink...")
        encrypted_payload = self.encrypt_e2e(msg)
        
        seq = int(time.time()) % 10000 
        pkt = Packet(NODE_ID, "SINK", encrypted_payload, msg_type=MSG_TYPE_DATA, seq_num=seq)
        self.connection_manager.send_packet(pkt)
        print("✅ Pacote Enviado (Hop-by-Hop Seguro + Payload E2E Seguro)!")

    def manage_uplink(self):
        while self.running:
            if not self.connection_manager.uplink:
                self.hb_manager.stop()
                connected = self.connection_manager.find_and_connect_uplink()
                if connected: self.hb_manager.start()
            time.sleep(5)

    def on_packet_received(self, packet, source_connection):
        if packet.msg_type == MSG_TYPE_HEARTBEAT:
            self.hb_manager.beat_received()
            if self.service.characteristics:
                 self.service.characteristics[0].send_notification(packet)
            return

        if packet.source_nid != "SINK" and packet.source_nid != "SELF":
             self.routing_table[packet.source_nid] = "Downlink"

        if packet.dest_nid != NODE_ID and packet.dest_nid != "SELF":
            self.routed_count += 1

        if packet.msg_type == MSG_TYPE_DATA:
            print(f"\n📦 [DATA] De {packet.source_nid} (Reencaminhando...)")
        
        if packet.dest_nid == "SINK" and self.connection_manager.uplink:
            self.connection_manager.send_packet(packet)

    def stop(self):
        print("\n[SYSTEM] A encerrar...")
        self.hb_manager.stop()
        self.advertiser.unregister()
        self.connection_manager.disconnect_all()
        self.mainloop.quit()
        sys.exit(0)

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, lambda x,y: sys.exit(0))
    app = NodeApp()
    app.start()