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
        try:
            print(f"[BLE] A usar adaptador (SimplePyBLE): {self.adapter.identifier()}")
        except Exception:
            pass
        self.uplink = None 
        self.uplink_info = {}
        self.router = None
        self.session_key = None 
        self.active_service_uuid = None
        self.active_char_uuid = None
        self.rx_buffer = bytearray()
        self.handshake_running = False

    def set_router(self, router): self.router = router

    def _get_adapter(self, target_index):
        adapters = simplepyble.Adapter.get_adapters()
        if not adapters:
            raise Exception("ERRO CRÍTICO: Bluetooth não encontrado.")

        want = f"hci{target_index}"
        for a in adapters:
            try:
                if want in str(a.identifier()).lower():
                    return a
            except Exception:
                continue

        return adapters[target_index] if target_index < len(adapters) else adapters[0]

    def _call_with_timeout(self, fn, timeout_s, label):
        result = {}
        error = {}

        def runner():
            try:
                result["value"] = fn()
            except Exception as e:
                error["exc"] = e

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        t.join(timeout_s)

        if t.is_alive():
            raise TimeoutError(f"Timeout em '{label}' ({timeout_s}s)")
        if "exc" in error:
            raise error["exc"]
        return result.get("value")

    def find_and_connect_uplink(self):
        if self.uplink: return True
        print("[MANAGER] A procurar novo Uplink...")
        candidates = scan_for_candidates(self.adapter) 
        if not candidates: return False

        for candidate in candidates:
            device = candidate['device_obj']
            print(f"[CONNECT] A tentar {candidate['name']}...")
            try:
                print("[CONNECT] A chamar device.connect()...")
                # Aumentei timeout para 15s para dar tempo ao sistema
                self._call_with_timeout(device.connect, 15, "device.connect")
                
                # ESTABILIZAÇÃO CRÍTICA: Bluetooth precisa de tempo após conectar
                print("[DEBUG] Conectado! A aguardar estabilização (2s)...")
                time.sleep(2.0)

                print("[CONNECT] A descobrir serviços...")
                services = self._call_with_timeout(device.services, 10, "device.services")
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
                    print("[CONNECT] Serviço SIC não encontrado neste dispositivo.")
                    device.disconnect()
                    continue

                self.active_service_uuid = found_s
                self.active_char_uuid = found_c
                
                print("[BLE] A ativar notificações...")
                device.notify(self.active_service_uuid, self.active_char_uuid, self._on_data_received_from_uplink)
                
                # ESTABILIZAÇÃO PÓS-NOTIFY: 
                # Muitas vezes o notify retorna antes do callback estar 100% pronto no BlueZ
                time.sleep(1.0) 
                print("[BLE] ✅ Notificações ativadas.")

                self.uplink = device
                self.uplink_info = candidate
                device.set_callback_on_disconnected(self.on_uplink_lost)
                
                print(f"[SUCCESS] 🔗 LIGADO A {candidate['name']}!")
                self.rx_buffer = bytearray()
                self._start_handshake_thread()
                return True
            except Exception as e:
                print(f"[CONNECT] ❌ Falha a conectar em {candidate['name']}: {e}")
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
        # Limpar buffer antes de começar para garantir que não lemos lixo antigo
        self.rx_buffer = bytearray()
        
        while self.handshake_running and self.uplink and self.session_key is None:
            print(f"[HANDSHAKE] 🤝 A enviar HELLO (Tentativa {attempt})...")
            
            hello_pkt = Packet(self.my_nid, "UPLINK", cert_pem.decode('utf-8'), MSG_TYPE_HELLO)
            
            # Tentar enviar. Se falhar o envio (return False), abortamos este ciclo
            if not self.send_packet(hello_pkt):
                print("[HANDSHAKE] Falha crítica no envio. A aguardar recuperação...")
                time.sleep(2)
            
            # Esperar pela resposta (ACK)
            for _ in range(50): # Espera até 5 segundos
                if self.session_key or not self.uplink: break
                time.sleep(0.1)
            
            attempt += 1
            if attempt > 10:
                print("[HANDSHAKE] ❌ O Sink não responde após 10 tentativas.")
                self.on_uplink_lost()
                return
            
            # Pequena pausa antes da próxima tentativa
            time.sleep(1.0)

    def send_packet(self, packet):
        if not self.uplink: return False
        try:
            data_bytes = packet.to_bytes()
            # 4 bytes de cabeçalho indicando o tamanho total
            full_payload = len(data_bytes).to_bytes(4, 'big') + data_bytes
            
            # --- CORREÇÃO DE ESTABILIDADE ---
            # Reduzir CHUNK_SIZE para 50 (mais seguro que 100 para evitar drops de MTU)
            CHUNK_SIZE = 50 
            
            total_chunks = (len(full_payload) + CHUNK_SIZE - 1) // CHUNK_SIZE
            
            for i in range(0, len(full_payload), CHUNK_SIZE):
                chunk = full_payload[i : i + CHUNK_SIZE]
                
                # Mecanismo de Retry por Chunk
                chunk_sent = False
                for retry in range(3):
                    try:
                        # write_request espera confirmação do receptor (mais lento, mas fiável)
                        self.uplink.write_request(self.active_service_uuid, self.active_char_uuid, chunk)
                        chunk_sent = True
                        break # Sucesso, sai do retry
                    except Exception as e:
                        print(f"[BLE-W] Falha chunk {i//CHUNK_SIZE}/{total_chunks} (Retry {retry+1}): {e}")
                        time.sleep(0.2)
                
                if not chunk_sent:
                    print("[BLE] Falha crítica: Não foi possível enviar chunk após 3 tentativas.")
                    return False

                # Pausa para não engasgar o controlador Bluetooth
                time.sleep(0.05) 
            
            return True
            
        except Exception as e:
            print(f"[BLE] ❌ Erro geral no send_packet: {e}")
            # Não chamamos on_uplink_lost imediatamente para dar chance de retry na app
            return False

    def _on_data_received_from_uplink(self, data_bytes):
        # Callback assíncrono
        try:
            self.rx_buffer.extend(data_bytes)
            
            # Processar stream de bytes
            while len(self.rx_buffer) >= 4:
                msg_len = int.from_bytes(self.rx_buffer[:4], 'big')
                
                # Se ainda não temos a mensagem toda, esperamos mais bytes
                if len(self.rx_buffer) < 4 + msg_len: 
                    break
                
                # Extrair o pacote completo
                packet_bytes = bytes(self.rx_buffer[4 : 4 + msg_len])
                del self.rx_buffer[:4 + msg_len] # Remover do buffer
                
                self._handle_complete_packet(packet_bytes)
        except Exception as e:
            print(f"[BLE-RX] Erro ao processar dados: {e}")

    def _handle_complete_packet(self, data_bytes):
        try:
            packet = Packet.from_bytes(data_bytes)
            if not packet: return 

            if packet.msg_type == MSG_TYPE_HELLO_ACK:
                if self.session_key: return # Já temos chave, ignorar duplicados
                
                print(f"[HANDSHAKE] 📩 Recebido HELLO_ACK de {packet.source_nid}")
                
                # Verificar e derivar chave
                peer_pub = self.security_manager.verify_certificate(packet.payload.encode('utf-8'))
                self.session_key = self.security_manager.derive_session_key(
                    self.security_manager.local_private_key, peer_pub
                )
                
                print(f"[SEC] 🔐 CANAL SEGURO ESTABELECIDO!")
                # Limpar buffer do router para evitar processar lixo antigo
                if self.router: self.router.reset_buffer(self.uplink)
                return
        except Exception as e: 
            print(f"[RX-Process] Erro: {e}")

        # Se não for handshake, passa para o Router
        if self.router and self.session_key:
            header = len(data_bytes).to_bytes(4, 'big')
            self.router.process_packet(header + data_bytes, source_connection=self.uplink)

    def on_uplink_lost(self, device=None):
        # Só reporta se realmente tínhamos um uplink
        if self.uplink is not None:
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
        self.uplink = None