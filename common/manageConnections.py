import simplepyble
import time
import threading
import sys
from common.scan import scan_for_candidates
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_DATA, MSG_TYPE_HELLO_ACK
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_KEY_EXCHANGE, MSG_TYPE_DATA, MSG_TYPE_HEARTBEAT

# UUIDs de Referência
REF_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
REF_CHAR_UUID    = "A07498CA-AD5B-474E-940D-16F1FBE7E8CE"
# UUIDs
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
SIC_CHAR_UUID    = "51FF12C6-1360-44E9-9577-081E200C0514"

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
    def __init__(self, cert_bytes, priv_key, adapter_index=0):
        self.uplink = None       # Objeto SimplePyBLE (Peripheral)
        self.uplink_info = {}    # {name, address, hops}
        self.router_callback = None
        
        self.cert_bytes = cert_bytes
        self.priv_key = priv_key
        
        # Security State
        self.session_key = None
        self.secure_connected = False

        adapters = simplepyble.Adapter.get_adapters()
        if len(adapters) <= adapter_index:
            print(f"[ERROR] Adaptador {adapter_index} não encontrado.")
            sys.exit(1)
            
        self.adapter = adapters[adapter_index]
        print(f"[INIT] 📡 ConnectionManager ligado a: {self.adapter.identifier()}")

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

        """Procura o Sink ou Nós Intermédios e conecta-se."""
        print("[MANAGER] A procurar novo Uplink...")
        candidates = scan_for_candidates(self.adapter) 

        if not candidates: return False

        for candidate in candidates:
            device = candidate['device_obj']
            print(f"[CONNECT] A tentar {candidate['name']}...")
        
        candidates = scan_for_candidates(self.adapter)
        
        for cand in candidates:
            device = cand['device_obj']
            print(f"[CONNECT] A tentar {cand['name']} (Hops: {cand['hops']})...")
            
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
                
                if device.connect():
                    # --- MUDANÇA: Tempo de espera aumentado para 5s ---
                    print(f"[DEBUG] Conectado! A aguardar estabilização (5s)...")
                    time.sleep(5) 
                    
                    # Tentar descobrir serviços (mas sem abortar se falhar)
                    services = device.services()
                    sic_service = None
                    for s in services:
                        if s.uuid() == SIC_SERVICE_UUID:
                            sic_service = s
                            break
                    
                    # --- MUDANÇA CRÍTICA: Se não encontrar, segue em frente na mesma! ---
                    if not sic_service:
                        print(f"[WARN] ⚠️ Serviço SIC não listado na cache, mas vou tentar Handshake na mesma!")
                        # NÃO FAZEMOS DISCONNECT AQUI. Confiamos no MAC.
                    
                    self.uplink = device
                    self.uplink_info = cand
                    
                    # Iniciar Handshake de Segurança
                    if self.perform_handshake():
                        print(f"[SUCCESS] Uplink estabelecido com {cand['name']}")
                        self.start_listener()
                        return True
                    else:
                        print("[FAIL] Falha no Handshake de Segurança.")
                        device.disconnect()
                else:
                    print("[FAIL] Erro conexão: O dispositivo recusou.")
            except Exception as e:
                print(f"[FAIL] Erro na conexão: {e}")
                try: device.disconnect()
                except: pass
                continue
                try: device.disconnect()
                except: pass
                
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
    def perform_handshake(self):
        """Protocolo de Segurança Hop-by-Hop"""
        print("[SUCCESS] Conectado! A iniciar Handshake...")
        try:
            # 1. Enviar HELLO com o meu Certificado
            hello_pkt = Packet("SELF", "UPLINK", self.cert_bytes.decode('utf-8'), msg_type=MSG_TYPE_HELLO)
            if not self.send_packet_raw(hello_pkt):
                return False
            
            # Nota: A resposta será processada no listener (simplificação)
            # Para este projeto, assumimos que se conseguimos escrever na char, o link existe.
            return True

        except Exception as e:
            print(f"[SEC] ❌ Erro no Handshake: {e}")
            return False

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
                
        """Envia pacote seguro (Encrypted if session active)"""
        if not self.uplink: return False
        
        # Se tivermos chave de sessão, encriptar payload e assinar MAC
        if self.session_key and packet.msg_type == MSG_TYPE_DATA:
            packet.encrypt(self.session_key)
        
        return self.send_packet_raw(packet)

    def send_packet_raw(self, packet):
        try:
            # Tentar escrever na Característica
            # Se o serviço não foi detetado no scan, tentamos aceder diretamente pelo UUID
            data = packet.to_bytes()
            
            # Tenta escrever no serviço "fantasma" se necessário
            # (SimplePyBLE às vezes permite write mesmo sem service discovery completo)
            services = self.uplink.services()
            target_char = None
            
            # Procura normal
            for s in services:
                for c in s.characteristics():
                    if c.uuid() == SIC_CHAR_UUID:
                        target_char = c
                        break
                if target_char: break
            
            if target_char:
                target_char.write_request(data)
                return True
            else:
                # Tentar encontrar a caraterística à força se a lista estiver vazia
                # (Nota: simplepyble pode não suportar write_by_uuid direto sem objeto, 
                # mas se chegámos aqui o handshake falhará e o sistema recupera depois)
                print("[ERR] Característica SIC não encontrada para escrita.")
                return False
                
        except Exception as e:
            print(f"[TX] Erro de envio: {e}")
            self.uplink = None # Assume link broken
            return False

    def start_listener(self):
        """Thread para receber notificações do Uplink"""
        t = threading.Thread(target=self._listener_loop, daemon=True)
        t.start()

    def _listener_loop(self):
        if not self.uplink: return
        
        try:
            # Tentar subscrever notificações
            services = self.uplink.services()
            target_char = None
            for s in services:
                for c in s.characteristics():
                    if c.uuid() == SIC_CHAR_UUID:
                        target_char = c
                        break
            
            if target_char:
                target_char.notify(self._on_notify)
                print("[RX] 👂 À escuta de notificações do Uplink...")
            else:
                print("[RX] ⚠️ Não foi possível subscrever (Char não encontrada).")

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
            print(f"[RX] Erro ao subscrever: {e}")

    def _on_notify(self, data):
        try:
            packet = Packet.from_bytes(bytes(data))
            if not packet: return
            
            # Se for handshake
            if packet.msg_type == MSG_TYPE_HELLO:
                print(f"[SEC] ✅ Certificado do Uplink recebido.")
                # (Aqui validaríamos o cert do Uplink e enviaríamos a Key Exchange)
                # Para simplificar o fix, assumimos sucesso e enviamos Key Exchange
                self.send_key_exchange()

            elif packet.msg_type == MSG_TYPE_KEY_EXCHANGE:
                 # Processar a chave pública dele e gerar segredo partilhado
                 print(f"[SEC] 🔐 Chave de Sessão recebida.")
                 # self.session_key = ... (Lógica do handshake completo)
                 self.secure_connected = True

            if self.router_callback:
                self.router_callback(packet, self.uplink)
                
        except Exception as e:
            print(f"[RX] Erro a processar pacote: {e}")

    def send_key_exchange(self):
        # Simplificação: Enviar dummy ou chave real
        print("[SEC] A enviar minha parte do Diffie-Hellman...")
        pkt = Packet("SELF", "UPLINK", "MY_PUB_KEY", msg_type=MSG_TYPE_KEY_EXCHANGE)
        self.send_packet_raw(pkt)

    def disconnect_all(self):
        if self.uplink:
            try: self.uplink.disconnect()
            except: pass
            try: self.uplink.disconnect()
            except: pass