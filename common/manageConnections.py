import simplepyble
import time
import threading
from common.scan import scan_for_candidates
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_DATA, MSG_TYPE_HELLO_ACK

# UUIDs de Referência
REF_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
REF_CHAR_UUID    = "A07498CA-AD5B-474E-940D-16F1FBE7E8CE"

class ConnectionManager:
    def __init__(self, security_manager=None, adapter_index=0):
        self.security_manager = security_manager
        self.adapter = self._get_adapter(adapter_index)
        self.uplink = None 
        self.uplink_info = {}
        self.router_callback = None
        self.session_key = None 
        self.active_service_uuid = None
        self.active_char_uuid = None
        
        # --- NOVO: Buffer para colar mensagens fragmentadas do Sink ---
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
                
                print(f"[BLE] Alvos confirmados: S={found_s} C={found_c}")

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
                
                # Limpa o buffer de lixo antigo antes de começar
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
        print("[HANDSHAKE] 🤝 A enviar HELLO com Certificado...")
        try: cert_pem = self.security_manager.local_cert_pem
        except: 
            with open(self.security_manager.cert_path, "rb") as f: cert_pem = f.read()

        hello_pkt = Packet(
            source_nid="SELF", 
            dest_nid="UPLINK",
            msg_type=MSG_TYPE_HELLO,
            payload=cert_pem.decode('utf-8') 
        )
        self.send_packet(hello_pkt)

    def send_packet(self, packet):
        if not self.uplink or not self.active_service_uuid: return
        try:
            data_bytes = packet.to_bytes()
            
            # FRAGMENTAÇÃO: Prepend tamanho total (4 bytes)
            full_payload = len(data_bytes).to_bytes(4, 'big') + data_bytes
            CHUNK_SIZE = 100 
            
            for i in range(0, len(full_payload), CHUNK_SIZE):
                chunk = full_payload[i : i + CHUNK_SIZE]
                self.uplink.write_request(self.active_service_uuid, self.active_char_uuid, chunk)
                time.sleep(0.05) 
                
        except Exception as e:
            print(f"[SEND] Falha no envio BLE: {e}")
            self.on_uplink_lost()

    def _on_data_received_from_uplink(self, data_bytes):
        """
        Recebe pedaços, cola-os no buffer, e só processa quando tiver a mensagem toda.
        """
        # 1. Adicionar ao Buffer
        self.rx_buffer.extend(data_bytes)
        
        # 2. Processar enquanto houver mensagens completas no buffer
        while True:
            # Precisamos de pelo menos 4 bytes para ler o tamanho
            if len(self.rx_buffer) < 4:
                break
            
            # Ler o tamanho da mensagem (Cabeçalho de 4 bytes)
            msg_len = int.from_bytes(self.rx_buffer[:4], 'big')
            
            # Verificar se já temos a mensagem toda
            if len(self.rx_buffer) < 4 + msg_len:
                # Ainda falta dados, esperar pelo próximo pacote
                break
            
            # Extrair a mensagem completa
            packet_bytes = bytes(self.rx_buffer[4 : 4 + msg_len])
            
            # Remover essa mensagem do buffer
            del self.rx_buffer[:4 + msg_len]
            
            # --- PROCESSAR O PACOTE LIMPO ---
            self._handle_complete_packet(packet_bytes)

    def _handle_complete_packet(self, data_bytes):
        try:
            packet = Packet.from_bytes(data_bytes)
            
            # Intercepta o ACK do Handshake
            if packet and packet.msg_type == MSG_TYPE_HELLO_ACK:
                print("[HANDSHAKE] 📩 Recebido HELLO_ACK do Sink (Completo).")
                if not self.security_manager: return
                
                peer_cert_pem = packet.payload.encode('utf-8')
                try:
                    peer_pub_key = self.security_manager.verify_certificate(peer_cert_pem)
                    print("[SEC] ✅ Certificado do Sink validado!")
                    self.session_key = self.security_manager.derive_session_key(
                        self.security_manager.local_private_key, peer_pub_key
                    )
                    print(f"[SEC] 🔐 CANAL SEGURO ESTABELECIDO!")
                except Exception as e:
                    print(f"[SEC] ❌ ERRO DE SEGURANÇA: {e}")
                    self.disconnect_all()
                return 
        except: pass

        # Passa dados normais para o Router
        if self.router_callback:
            self.router_callback(data_bytes, source_connection=self.uplink)

    def on_uplink_lost(self, device=None):
        print("\n⚡ [ALERT] LIGAÇÃO CAIU!")
        self.uplink = None
        self.uplink_info = {}
        self.session_key = None 
        self.active_service_uuid = None
        self.rx_buffer = bytearray() # Limpar buffer

    def disconnect_all(self):
        if self.uplink:
            try: self.uplink.disconnect()
            except: pass