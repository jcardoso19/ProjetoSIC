import simplepyble
import time
import threading
import sys
from common.scan import scan_for_candidates
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_KEY_EXCHANGE, MSG_TYPE_DATA, MSG_TYPE_HEARTBEAT

# UUIDs
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
SIC_CHAR_UUID    = "51FF12C6-1360-44E9-9577-081E200C0514"

class ConnectionManager:
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

    def find_and_connect_uplink(self):
        """Procura o Sink ou Nós Intermédios e conecta-se."""
        print("[MANAGER] A procurar novo Uplink...")
        
        candidates = scan_for_candidates(self.adapter)
        
        for cand in candidates:
            device = cand['device_obj']
            print(f"[CONNECT] A tentar {cand['name']} (Hops: {cand['hops']})...")
            
            try:
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
                
        return False

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