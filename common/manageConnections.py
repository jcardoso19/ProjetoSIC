import simplepyble
import time
import threading
import os
from common.scan import scan_for_candidates
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_DATA, MSG_TYPE_HELLO_ACK

REF_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
REF_CHAR_UUID    = "A07498CA-AD5B-474E-940D-16F1FBE7E8CE"

class ConnectionManager:
    def __init__(self, security_manager=None, adapter_index=0, my_nid="Unknown"):
        self.my_nid = my_nid
        self.security_manager = security_manager
        self.adapter = self._get_adapter(adapter_index)
        self.uplink = None 
        self.uplink_info = {}
        self.router = None
        self.session_key = None 
        self.active_service_uuid = None
        self.active_char_uuid = None
        self.rx_buffer = bytearray()
        self.handshake_running = False

    def set_router(self, router):
        self.router = router

    def _get_adapter(self, target_index):
        adapters = simplepyble.Adapter.get_adapters()
        if not adapters: raise Exception("ERRO CRÍTICO: Bluetooth não encontrado.")
        return adapters[target_index] if target_index < len(adapters) else adapters[0]

    def find_and_connect_uplink(self):
        if self.uplink: return True
        print("[MANAGER] A procurar novo Uplink...")
        candidates = scan_for_candidates(self.adapter) 
        if not candidates: return False

        for candidate in candidates:
            device = candidate['device_obj']
            print(f"[CONNECT] A tentar {candidate['name']}...")
            try:
                device.connect()
                print("[DEBUG] Conectado! A aguardar estabilização (2s)...")
                time.sleep(2) 
                
                services = device.services()
                found_s = None
                found_c = None
                for s in services:
                    if s.uuid().lower() == REF_SERVICE_UUID.lower():
                        found_s = s.uuid()
                        for c in s.characteristics():
                            if c.uuid().lower() == REF_CHAR_UUID.lower():
                                found_c = c.uuid()
                        break
                
                if not found_s or not found_c:
                    device.disconnect()
                    continue

                self.active_service_uuid = found_s
                self.active_char_uuid = found_c
                device.notify(self.active_service_uuid, self.active_char_uuid, self._on_data_received_from_uplink)
                print("[BLE] ✅ Notificações ativadas.")

                self.uplink = device
                self.uplink_info = candidate
                device.set_callback_on_disconnected(self.on_uplink_lost)
                
                print(f"[SUCCESS] 🔗 LIGADO A {candidate['name']}!")
                self.rx_buffer = bytearray()
                self._start_handshake_thread()
                return True
            except:
                try: device.disconnect()
                except: pass
        return False

    def _start_handshake_thread(self):
        if not self.security_manager: return
        self.handshake_running = True
        threading.Thread(target=self._handshake_loop, daemon=True).start()

    def _handshake_loop(self):
        print(f"[HANDSHAKE] 🔄 A iniciar protocolo de ligação...")
        try: cert_pem = self.security_manager.local_cert_pem
        except: 
            with open(self.security_manager.cert_path, "rb") as f: cert_pem = f.read()

        attempt = 1
        while self.handshake_running and self.uplink and self.session_key is None:
            print(f"[HANDSHAKE] 🤝 A enviar HELLO (Tentativa {attempt})...")
            
            hello_pkt = Packet(self.my_nid, "UPLINK", cert_pem.decode('utf-8'), MSG_TYPE_HELLO)
            self.send_packet(hello_pkt)
            
            # Espera 6 segundos (tempo suficiente para o delay de 0.5s do Sink + transmissão)
            for _ in range(60):
                if self.session_key or not self.uplink: break
                time.sleep(0.1)
            
            attempt += 1
            if attempt > 10:
                print("[HANDSHAKE] ❌ O Sink não responde.")
                self.on_uplink_lost()
                return

    def send_packet(self, packet):
        if not self.uplink: return
        try:
            data_bytes = packet.to_bytes()
            full_payload = len(data_bytes).to_bytes(4, 'big') + data_bytes
            
            print(f"[DEBUG-TX] A enviar {len(full_payload)} bytes (Tipo: {packet.msg_type})")
            
            CHUNK_SIZE = 100 # Tamanho médio seguro
            for i in range(0, len(full_payload), CHUNK_SIZE):
                chunk = full_payload[i : i + CHUNK_SIZE]
                self.uplink.write_request(self.active_service_uuid, self.active_char_uuid, chunk)
                time.sleep(0.15) 
        except Exception as e:
            print(f"[DEBUG-ERR] Falha no envio: {e}")
            self.on_uplink_lost()

    def _on_data_received_from_uplink(self, data_bytes):
        self.rx_buffer.extend(data_bytes)
        while len(self.rx_buffer) >= 4:
            msg_len = int.from_bytes(self.rx_buffer[:4], 'big')
            if len(self.rx_buffer) < 4 + msg_len: break
            
            packet_bytes = bytes(self.rx_buffer[4 : 4 + msg_len])
            del self.rx_buffer[:4 + msg_len]
            self._handle_complete_packet(packet_bytes)

    def _handle_complete_packet(self, data_bytes):
        try:
            packet = Packet.from_bytes(data_bytes)
            if not packet: return 

            if packet.msg_type == MSG_TYPE_HELLO_ACK:
                if self.session_key: return
                print(f"[HANDSHAKE] 📩 Recebido HELLO_ACK")
                peer_pub = self.security_manager.verify_certificate(packet.payload.encode('utf-8'))
                self.session_key = self.security_manager.derive_session_key(
                    self.security_manager.local_private_key, peer_pub
                )
                print(f"[SEC] 🔐 CANAL SEGURO ESTABELECIDO!")
                if self.router: self.router.reset_buffer(self.uplink)
                return
        except: pass

        if self.router:
            header = len(data_bytes).to_bytes(4, 'big')
            self.router.process_packet(header + data_bytes, source_connection=self.uplink)

    def on_uplink_lost(self, device=None):
        print("\n⚡ [ALERT] LIGAÇÃO CAIU!")
        self.uplink = None
        self.session_key = None 
        self.handshake_running = False
        self.rx_buffer = bytearray()

    def disconnect_all(self):
        self.handshake_running = False
        if self.uplink:
            try: self.uplink.disconnect()
            except: pass