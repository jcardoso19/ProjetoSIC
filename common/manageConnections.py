import simplepyble
import time
import threading
import os
from common.scan import scan_for_candidates
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_DATA, MSG_TYPE_HELLO_ACK

# UUIDs de Referência
REF_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
REF_CHAR_UUID    = "A07498CA-AD5B-474E-940D-16F1FBE7E8CE"

class ConnectionManager:
    def __init__(self, security_manager=None, adapter_index=0, my_nid="Unknown"):
        self.my_nid = my_nid
        self.security_manager = security_manager
        self.adapter = self._get_adapter(adapter_index)
        self.uplink = None 
        self.uplink_info = {}
        self.router_callback = None
        self.session_key = None 
        self.active_service_uuid = None
        self.active_char_uuid = None
        self.rx_buffer = bytearray()

    def set_router_callback(self, callback):
        self.router_callback = callback

    def _get_adapter(self, target_index):
        adapters = simplepyble.Adapter.get_adapters()
        if not adapters:
            raise Exception("ERRO CRÍTICO: Nenhum adaptador Bluetooth encontrado.")
        if target_index < len(adapters):
            print(f"[INIT] 📡 ConnectionManager ligado a: {adapters[target_index].identifier()} (Index: {target_index})")
            return adapters[target_index]
        return adapters[0]

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
                print("[DEBUG] Conectado! A mapear serviços (3s)...")
                time.sleep(3) 
                
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
                    print(f"[FAIL] Serviço/Característica não encontrados.")
                    device.disconnect()
                    continue

                self.active_service_uuid = found_s
                self.active_char_uuid = found_c
                
                try:
                    device.notify(self.active_service_uuid, self.active_char_uuid, self._on_data_received_from_uplink)
                    print("[BLE] ✅ Notificações ativadas.")
                except Exception as e:
                    print(f"[WARN] Falha ao ativar notify: {e}")
                    device.disconnect()
                    continue

                self.uplink = device
                self.uplink_info = candidate
                device.set_callback_on_disconnected(self.on_uplink_lost)
                
                print(f"[SUCCESS] 🔗 LIGADO A {candidate['name']}!")
                self.rx_buffer = bytearray()
                self._start_handshake()
                return True
                
            except Exception as e:
                print(f"[FAIL] Erro na conexão: {e}")
                try: device.disconnect()
                except: pass
                continue
        return False

    def _start_handshake(self):
        if not self.security_manager: return
        print(f"[HANDSHAKE] 🤝 A enviar HELLO de {self.my_nid}...")
        try: cert_pem = self.security_manager.local_cert_pem
        except: 
            with open(self.security_manager.cert_path, "rb") as f: cert_pem = f.read()

        hello_pkt = Packet(
            source_nid=self.my_nid, # Usa o nome real (node1)
            dest_nid="UPLINK",
            msg_type=MSG_TYPE_HELLO,
            payload=cert_pem.decode('utf-8') 
        )
        self.send_packet(hello_pkt)

    def send_packet(self, packet):
        if not self.uplink or not self.active_service_uuid: return
        try:
            data_bytes = packet.to_bytes()
            full_payload = len(data_bytes).to_bytes(4, 'big') + data_bytes
            CHUNK_SIZE = 100 
            for i in range(0, len(full_payload), CHUNK_SIZE):
                chunk = full_payload[i : i + CHUNK_SIZE]
                self.uplink.write_request(self.active_service_uuid, self.active_char_uuid, chunk)
                time.sleep(0.06) 
        except Exception as e:
            print(f"[SEND] Falha no envio BLE: {e}")
            self.on_uplink_lost()

    def _on_data_received_from_uplink(self, data_bytes):
        self.rx_buffer.extend(data_bytes)
        while True:
            if len(self.rx_buffer) < 4: break
            msg_len = int.from_bytes(self.rx_buffer[:4], 'big')
            if len(self.rx_buffer) < 4 + msg_len: break
            packet_bytes = bytes(self.rx_buffer[4 : 4 + msg_len])
            del self.rx_buffer[:4 + msg_len]
            self._handle_complete_packet(packet_bytes)

    # No ficheiro common/manageConnections.py

    def _handle_complete_packet(self, data_bytes):
        try:
            packet = Packet.from_bytes(data_bytes)
            if packet and packet.msg_type == MSG_TYPE_HELLO_ACK:
                print(f"[HANDSHAKE] 📩 Recebido HELLO_ACK de {packet.source_nid}")
                
                # Derivar a chave IMEDIATAMENTE
                peer_cert_pem = packet.payload.encode('utf-8')
                peer_pub_key = self.security_manager.verify_certificate(peer_cert_pem)
                self.session_key = self.security_manager.derive_session_key(
                    self.security_manager.local_private_key, peer_pub_key
                )
                
                # A chave TEM de estar ativa antes de sair desta função
                print(f"[SEC] 🔐 CANAL SEGURO ESTABELECIDO!")
                return
        except: pass
        if self.router_callback:
            self.router_callback(data_bytes, source_connection=self.uplink)

    def on_uplink_lost(self, device=None):
        print("\n⚡ [ALERT] LIGAÇÃO CAIU!")
        self.uplink = None
        self.session_key = None 
        self.rx_buffer = bytearray()

    def disconnect_all(self):
        if self.uplink:
            try: self.uplink.disconnect()
            except: pass