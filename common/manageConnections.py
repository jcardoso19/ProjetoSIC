import simplepyble
import time
import threading
import os
from common.scan import scan_for_candidates
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_DATA

# UUIDs definidos no advertiser.py
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
SIC_CHAR_UUID    = "51FF12C6-1360-44E9-9577-081E200C0514"

class ConnectionManager:
    def __init__(self, cert_bytes=None, priv_key=None):
        """
        :param cert_bytes: Os bytes do certificado X.509 deste dispositivo.
        :param priv_key: A chave privada (objeto cryptography) deste dispositivo.
        """
        self.cert_bytes = cert_bytes
        self.priv_key = priv_key
        
        self.adapter = self._get_adapter()
        self.uplink = None 
        self.uplink_info = {}
        
        self.router_callback = None

    def set_router_callback(self, callback):
        """O Router passa aqui a sua função process_packet"""
        self.router_callback = callback

    def _get_adapter(self):
        adapters = simplepyble.Adapter.get_adapters()
        if not adapters:
            raise Exception("ERRO CRÍTICO: Nenhum adaptador Bluetooth encontrado.")
        print(f"[INIT] A usar adaptador: {adapters[0].identifier()}")
        return adapters[0]

    def find_and_connect_uplink(self):
        """Lógica Lazy: Só procura se não tiver Uplink vivo."""
        if self.uplink:
            try:
                pass 
            except:
                self.on_uplink_lost()
                return False
            return True

        print("[MANAGER] A procurar novo Uplink...")
        candidates = scan_for_candidates(self.adapter) # Usa o teu scan.py

        if not candidates:
            return False

        for candidate in candidates:
            device = candidate['device_obj']
            print(f"[CONNECT] A tentar {candidate['name']} (Hops: {candidate['hops']})...")
            
            try:
                device.connect()
                
                # VERIFICAÇÃO CRÍTICA: O serviço existe?
                services = device.services()
                service_found = False
                for s in services:
                    if s.uuid() == SIC_SERVICE_UUID:
                        service_found = True
                        break
                
                if not service_found:
                    print(f"[FAIL] {candidate['name']} não tem o serviço SIC. A desconectar.")
                    device.disconnect()
                    continue

                # 1. Configurar Callback de Receção (NOTIFY)
                # Isto permite ouvir o Heartbeat e respostas do Pai
                try:
                    device.notify(SIC_SERVICE_UUID, SIC_CHAR_UUID, self._on_data_received_from_uplink)
                    print("[BLE] Notificações ativadas no Uplink.")
                except Exception as e:
                    print(f"[WARN] Falha ao ativar notify: {e}")

                self.uplink = device
                self.uplink_info = candidate
                
                # Define callback de desconexão
                device.set_callback_on_disconnected(self.on_uplink_lost)
                
                print(f"[SUCCESS] Conectado a {candidate['name']}!")

                # 2. INICIAR HANDSHAKE DE SEGURANÇA
                self._start_handshake()

                return True
                
            except Exception as e:
                print(f"[FAIL] Erro na conexão: {e}")
                try:
                    device.disconnect()
                except:
                    pass
                continue
        
        return False

    def _start_handshake(self):
        """Envia o pacote HELLO com o nosso Certificado"""
        if not self.cert_bytes:
            print("[SEC] Sem certificado carregado! Saltando Handshake (Modo Inseguro).")
            return

        print("[HANDSHAKE] A enviar HELLO com Certificado...")
        # Payload do HELLO é o certificado em PEM
        hello_pkt = Packet(
            source_nid="SELF", # O Router vai preencher isto melhor
            dest_nid="UPLINK",
            msg_type=MSG_TYPE_HELLO,
            payload=self.cert_bytes.decode('utf-8') # Envia o Cert como String
        )
        
        self.send_packet(hello_pkt)

    def send_packet(self, packet):
        """Envia um objeto Packet para o Uplink"""
        if not self.uplink:
            print("[SEND] Erro: Sem Uplink conectado.")
            return

        try:
            # Serializa usando o protocolo
            data_bytes = packet.to_bytes()
            

            self.uplink.write_request(SIC_SERVICE_UUID, SIC_CHAR_UUID, data_bytes)
            
        except Exception as e:
            print(f"[SEND] Falha no envio BLE: {e}")
            self.on_uplink_lost()

    def _on_data_received_from_uplink(self, data_bytes):
        """Chamado automaticamente pelo simplepyble quando o Pai envia dados (Notify)"""
        if self.router_callback:
            self.router_callback(data_bytes, source_connection=self.uplink)

    def on_uplink_lost(self, device=None):
        print("\n⚡ [ALERT] UPLINK PERDIDO!")
        self.uplink = None
        self.uplink_info = {}

    def disconnect_all(self):
        if self.uplink:
            try:
                self.uplink.disconnect()
            except:
                pass