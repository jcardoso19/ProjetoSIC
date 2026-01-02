import simplepyble
import time
import threading
import os
from common.scan import scan_for_candidates
from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_DATA, MSG_TYPE_HELLO_ACK

# UUIDs do Projeto
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
SIC_CHAR_UUID    = "51FF12C6-1360-44E9-9577-081E200C0514"

class ConnectionManager:
    def __init__(self, security_manager=None, adapter_index=0):
        self.security_manager = security_manager
        
        # Escolhe o adaptador com base no índice pedido (0=Interno, 1=USB)
        self.adapter = self._get_adapter(adapter_index)
        self.uplink = None 
        self.uplink_info = {}
        self.router_callback = None
        self.session_key = None # Chave de sessão negociada

    def set_router_callback(self, callback):
        """Define quem recebe os pacotes de dados (geralmente o Router)"""
        self.router_callback = callback

    def _get_adapter(self, target_index):
        """Seleciona o adaptador específico para evitar conflitos de hardware"""
        adapters = simplepyble.Adapter.get_adapters()
        if not adapters:
            raise Exception("ERRO CRÍTICO: Nenhum adaptador Bluetooth encontrado.")
        
        # Se pedirmos o índice 1 (USB) e ele existir, usa-o.
        if target_index < len(adapters):
            selected = adapters[target_index]
            print(f"[INIT] 📡 ConnectionManager ligado a: {selected.identifier()} (Index: {target_index})")
            return selected
        else:
            # Fallback: Se pedirmos o 1 mas só houver 0, usa o 0.
            print(f"[WARN] Índice {target_index} indisponível. A usar padrão (0).")
            return adapters[0]

    def find_and_connect_uplink(self):
        """
        Tenta encontrar um Uplink (Sink ou outro Nó) e conectar-se.
        Retorna True se conectar com sucesso.
        """
        # Se já estamos conectados, verificamos se a ligação ainda está viva
        if self.uplink:
            try:
                # Teste simples de vida (opcional)
                pass 
            except:
                self.on_uplink_lost()
                return False
            return True

        print("[MANAGER] A procurar novo Uplink...")
        
        # Usa a função de scan (agora configurada para achar o MAC do Sink)
        candidates = scan_for_candidates(self.adapter) 

        if not candidates:
            return False

        for candidate in candidates:
            device = candidate['device_obj']
            print(f"[CONNECT] A tentar {candidate['name']} (Hops: {candidate['hops']})...")
            
            try:
                # 1. Tentar Conectar
                device.connect()
                
                # --- CORREÇÃO FUNDAMENTAL: PAUSA PARA SERVICE DISCOVERY ---
                print("[DEBUG] Conectado! A aguardar descoberta de serviços (2s)...")
                time.sleep(2) 
                # ----------------------------------------------------------
                
                # 2. Verificar se tem o Serviço SIC
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

                # 3. Ativar Notificações (Para receber dados)
                try:
                    device.notify(SIC_SERVICE_UUID, SIC_CHAR_UUID, self._on_data_received_from_uplink)
                    print("[BLE] Notificações ativadas no Uplink.")
                except Exception as e:
                    print(f"[WARN] Falha ao ativar notify: {e}")

                # 4. Finalizar Configuração
                self.uplink = device
                self.uplink_info = candidate
                device.set_callback_on_disconnected(self.on_uplink_lost)
                
                print(f"[SUCCESS] Conectado a {candidate['name']}!")
                
                # 5. Iniciar Handshake de Segurança
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
        """Envia o certificado logo após a conexão"""
        if not self.security_manager:
            print("[SEC] Sem SecurityManager! Saltando Handshake.")
            return

        print("[HANDSHAKE] A enviar HELLO com Certificado...")
        
        # Obtém bytes do certificado local
        # Assumimos que o security_manager tem acesso ao certificado carregado
        # Vamos adicionar um método ou acessar propriedade. O security_manager tem 'local_cert_bytes' (vamos ter de garantir isto)
        # Como o security_manager no meu código anterior não guardava os bytes crus, vou ler do ficheiro ou adicionar propriedade.
        # Melhor: O security_manager pode ter um método 'get_local_cert_bytes()'
        
        # Vou assumir que o security_manager foi inicializado com um 'local_cert_pem'
        try:
             cert_pem = self.security_manager.local_cert_pem
        except:
             print("[SEC] Erro: Certificado local não disponível no SecurityManager.")
             return

        hello_pkt = Packet(
            source_nid="SELF", # O Router depois corrige isto
            dest_nid="UPLINK",
            msg_type=MSG_TYPE_HELLO,
            payload=cert_pem.decode('utf-8') 
        )
        self.send_packet(hello_pkt)

    def send_packet(self, packet):
        """Envia um pacote Packet() para o Uplink"""
        if not self.uplink:
            return
        try:
            data_bytes = packet.to_bytes()
            # Escreve na característica do Uplink
            self.uplink.write_request(SIC_SERVICE_UUID, SIC_CHAR_UUID, data_bytes)
        except Exception as e:
            print(f"[SEND] Falha no envio BLE: {e}")
            self.on_uplink_lost()

    def _on_data_received_from_uplink(self, data_bytes):
        """Callback chamada quando o Uplink nos manda dados"""
        
        # Tenta interceptar pacotes de Handshake (HELLO_ACK)
        try:
            packet = Packet.from_bytes(data_bytes)
            if packet and packet.msg_type == MSG_TYPE_HELLO_ACK:
                print("[HANDSHAKE] Recebido HELLO_ACK do Uplink.")
                
                if not self.security_manager:
                    print("[SEC] Erro: Recebi HELLO_ACK mas não tenho SecurityManager.")
                    return

                # Payload é o certificado do Uplink (PEM String)
                peer_cert_pem = packet.payload.encode('utf-8')
                
                try:
                    # 1. Verificar Certificado
                    peer_pub_key = self.security_manager.verify_certificate(peer_cert_pem)
                    print("[SEC] Certificado do Uplink validado com sucesso!")
                    
                    # 2. Derivar Chave de Sessão
                    self.session_key = self.security_manager.derive_session_key(
                        self.security_manager.local_private_key,
                        peer_pub_key
                    )
                    print(f"[SEC] 🔐 Chave de Sessão Uplink Negociada: {self.session_key.hex()[:10]}...")
                    
                except Exception as e:
                    print(f"[SEC] FALHA NO HANDSHAKE: {e}")
                    self.disconnect_all()
                
                return # NÃO passa para o Router
                
        except Exception as e:
            print(f"[DEBUG] Erro ao analisar pacote interno: {e}")

        # Se não for handshake, passa para o Router
        if self.router_callback:
            self.router_callback(data_bytes, source_connection=self.uplink)

    def on_uplink_lost(self, device=None):
        """Limpa o estado quando a ligação cai"""
        print("\n⚡ [ALERT] UPLINK PERDIDO!")
        self.uplink = None
        self.uplink_info = {}
        self.session_key = None # Limpa a chave

    def disconnect_all(self):
        """Desconecta de forma limpa"""
        if self.uplink:
            try:
                self.uplink.disconnect()
            except:
                pass