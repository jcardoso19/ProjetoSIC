import sys
import time
import os
import threading
import select
import json
import dbus.mainloop.glib
from gi.repository import GLib

# --- Módulos do Projeto ---
from common.advertiser import SICAdvertiser
from common.gatt_server import Application, SICService
from common.protocol import Packet, MSG_TYPE_HEARTBEAT, MSG_TYPE_DATA

# --- Criptografia ---
from cryptography import x509
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend

# Configurações
SINK_ID = "SINK_DEVICE"
CERT_PATH = "support/certs/sink.crt"
KEY_PATH  = "support/certs/sink.key"

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
    return cert_bytes, priv_key

class SinkApp:
    def __init__(self):
        self.cert_bytes, self.priv_key = load_credentials()
        
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.mainloop = GLib.MainLoop()

        self.app = Application(self.bus)
        self.service = SICService(self.bus, 0, self.on_data_received, self.cert_bytes, self.priv_key)
        self.app.add_service(self.service)

        self.advertiser = SICAdvertiser(self.bus, 0, SINK_ID)
        
        self.running = True
        self.sending_heartbeats = True

    def start(self):
        print(f"[SYSTEM] {SINK_ID} iniciado com SEGURANÇA TOTAL (E2E + Hop-by-Hop).")
        self.service.register(self.app.get_path())
        self.advertiser.register()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        threading.Thread(target=self.input_loop, daemon=True).start()
        try:
            self.mainloop.run()
        except KeyboardInterrupt:
            self.stop()

    def decrypt_e2e(self, payload_str):
        """
        Tenta abrir o envelope E2E usando a Chave Privada do Sink.
        """
        try:
            envelope = json.loads(payload_str)
            if not isinstance(envelope, dict) or "e2e" not in envelope:
                return payload_str # Não estava encriptado E2E

            # 1. Recuperar chave efemera do remetente
            sender_eph_pub = serialization.load_pem_public_key(
                envelope['k'].encode('utf-8'), default_backend()
            )

            # 2. Recriar o segredo partilhado (ECDH)
            shared_secret = self.priv_key.exchange(ec.ECDH(), sender_eph_pub)
            key_e2e = HKDF(
                algorithm=hashes.SHA256(), length=32, salt=None, info=b'sic-e2e', backend=default_backend()
            ).derive(shared_secret)

            # 3. Desencriptar (AES-GCM)
            aes = AESGCM(key_e2e)
            nonce = bytes.fromhex(envelope['n'])
            ciphertext = bytes.fromhex(envelope['c'])
            plaintext = aes.decrypt(nonce, ciphertext, None)
            
            return f"🔓 {plaintext.decode('utf-8')} (Desencriptado E2E com Sucesso)"
        
        except Exception as e:
            return f"❌ Erro ao desencriptar E2E: {e} | Raw: {payload_str}"

    def input_loop(self):
        print("[CONTROL] 'h' + Enter para Pausar Heartbeats.")
        while self.running:
            try:
                if sys.stdin in select.select([sys.stdin], [], [], 1)[0]:
                    if sys.stdin.readline().strip() == 'h':
                        self.sending_heartbeats = not self.sending_heartbeats
                        status = "ATIVOS" if self.sending_heartbeats else "PAUSADOS"
                        print(f"\n[CONTROL] Heartbeats: {status}")
            except: pass

    def heartbeat_loop(self):
        seq = 0
        while self.running:
            time.sleep(5)
            if not self.sending_heartbeats: continue
            
            sic_char = self.service.characteristics[0]
            if not sic_char.sessions: continue

            try:
                pkt = Packet(SINK_ID, "BROADCAST", "HEARTBEAT", msg_type=MSG_TYPE_HEARTBEAT, seq_num=seq)
                first_session = list(sic_char.sessions.values())[0]
                session_key = first_session.get('session_key')
                if session_key:
                    pkt.sign(session_key)
                    sic_char.send_notification(pkt)
                    print(f"[SINK] ❤️ Heartbeat enviado (Seq: {seq})")
                    seq += 1
            except: pass

    def on_data_received(self, packet, device_path):
        """Processa dados. Tenta desencriptar E2E se necessário."""
        decoded_content = self.decrypt_e2e(packet.payload)
        print(f"[INBOX] 📩 De {packet.source_nid}: {decoded_content}")

    def stop(self):
        print("[SYSTEM] A encerrar...")
        self.advertiser.unregister()
        self.mainloop.quit()
        sys.exit(0)

if __name__ == "__main__":
    app = SinkApp()
    app.start()