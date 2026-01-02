from common.protocol import Packet, MSG_TYPE_E2E_HELLO, MSG_TYPE_E2E_HELLO_ACK, MSG_TYPE_E2E_DATA
from common.security import SecurityManager
import json
import base64

class DTLSSession:
    def __init__(self, peer_nid, session_key):
        self.peer_nid = peer_nid
        self.session_key = session_key
        self.outgoing_seq = 0
        self.incoming_seq = -1 # Accept 0

class DTLSManager:
    def __init__(self, my_nid, security_manager, router_send_func):
        self.my_nid = my_nid
        self.sec_manager = security_manager
        self.send_func = router_send_func # Function to send Packet via Router
        self.sessions = {} # Map: peer_nid -> DTLSSession
        self.pending_handshakes = set()
        self.services = {} # Map: service_name -> callback(source_nid, cid, data)

    def register_service(self, service_name, callback):
        """Regista um serviço para receber dados (Ex: 'Inbox')"""
        self.services[service_name] = callback
        print(f"[DTLS] Serviço '{service_name}' registado.")

    def start_handshake(self, peer_nid):
        """Initiates E2E Handshake with a peer (e.g., Sink)"""
        print(f"[DTLS] A iniciar handshake E2E com {peer_nid}...")
        
        # Create HELLO packet
        # Payload: Local Certificate
        if not self.sec_manager.local_cert_pem:
            print("[DTLS] Erro: Sem certificado local.")
            return

        pkt = Packet(
            source_nid=self.my_nid,
            dest_nid=peer_nid,
            msg_type=MSG_TYPE_E2E_HELLO,
            payload=self.sec_manager.local_cert_pem.decode('utf-8')
        )
        
        self.pending_handshakes.add(peer_nid)
        self.send_func(pkt)

    def process_packet(self, packet):
        """Processes incoming E2E packets (Handshake or Data)"""
        
        # --- HANDSHAKE: HELLO ---
        if packet.msg_type == MSG_TYPE_E2E_HELLO:
            print(f"[DTLS] 🤝 E2E HELLO recebido de {packet.source_nid}")
            try:
                # 1. Verify Peer Cert
                peer_cert_pem = packet.payload.encode('utf-8')
                peer_pub_key = self.sec_manager.verify_certificate(peer_cert_pem)
                
                # 2. Derive Session Key
                session_key = self.sec_manager.derive_session_key(
                    self.sec_manager.local_private_key,
                    peer_pub_key
                )
                
                # 3. Store Session
                self.sessions[packet.source_nid] = DTLSSession(packet.source_nid, session_key)
                print(f"[DTLS] Sessão E2E estabelecida com {packet.source_nid}")
                
                # 4. Send ACK (with my Cert)
                ack_pkt = Packet(
                    source_nid=self.my_nid,
                    dest_nid=packet.source_nid,
                    msg_type=MSG_TYPE_E2E_HELLO_ACK,
                    payload=self.sec_manager.local_cert_pem.decode('utf-8')
                )
                self.send_func(ack_pkt)
                
            except Exception as e:
                print(f"[DTLS] Falha no Handshake E2E: {e}")

        # --- HANDSHAKE: HELLO_ACK ---
        elif packet.msg_type == MSG_TYPE_E2E_HELLO_ACK:
            if packet.source_nid not in self.pending_handshakes:
                # print("[DTLS] Aviso: ACK inesperado ou duplicado.")
                pass
            
            print(f"[DTLS] 🤝 E2E HELLO_ACK recebido de {packet.source_nid}")
            try:
                # 1. Verify Peer Cert
                peer_cert_pem = packet.payload.encode('utf-8')
                peer_pub_key = self.sec_manager.verify_certificate(peer_cert_pem)
                
                # 2. Derive Session Key
                session_key = self.sec_manager.derive_session_key(
                    self.sec_manager.local_private_key,
                    peer_pub_key
                )
                
                # 3. Store Session
                self.sessions[packet.source_nid] = DTLSSession(packet.source_nid, session_key)
                if packet.source_nid in self.pending_handshakes:
                    self.pending_handshakes.remove(packet.source_nid)
                
                print(f"[DTLS] Sessão E2E estabelecida com {packet.source_nid} (Active)")
                
            except Exception as e:
                print(f"[DTLS] Falha no Handshake E2E (ACK): {e}")

        # --- DATA ---
        elif packet.msg_type == MSG_TYPE_E2E_DATA:
            self._handle_data(packet)

    def send_data(self, peer_nid, message_str, service="Inbox", client_id=0):
        """Sends application data securely to peer"""
        if peer_nid not in self.sessions:
            print(f"[DTLS] Erro: Sem sessão com {peer_nid}. Faça handshake primeiro.")
            return

        session = self.sessions[peer_nid]
        
        # 1. Construct Service Payload (Section 5.7)
        # Structure: Service|ClientID|Data
        payload_dict = {
            "srv": service,
            "cid": client_id,
            "dat": message_str
        }
        payload_bytes = json.dumps(payload_dict).encode('utf-8')
        
        # 2. Encrypt (Using the same logic as Link Layer but with E2E Key)
        e2e_pkt = Packet(
            source_nid=self.my_nid,
            dest_nid=peer_nid,
            msg_type=MSG_TYPE_E2E_DATA,
            seq_num=session.outgoing_seq,
            payload=payload_bytes # Raw bytes initially
        )
        
        # Encrypt
        self.sec_manager.encrypt_packet(session.session_key, e2e_pkt)
        
        # Update Seq
        session.outgoing_seq += 1
        
        # Send
        self.send_func(e2e_pkt)
        print(f"[DTLS] 📤 Mensagem E2E enviada para {peer_nid} (Seq {e2e_pkt.seq_num})")

    def _handle_data(self, packet):
        session = self.sessions.get(packet.source_nid)
        if not session:
            print(f"[DTLS] ❌ Drop: Dados E2E de desconhecido {packet.source_nid}")
            return

        # 1. Decrypt
        if not self.sec_manager.decrypt_packet(session.session_key, packet):
            print(f"[DTLS] ❌ Drop: Falha decifragem E2E de {packet.source_nid}")
            return

        # 2. Freshness
        if packet.seq_num <= session.incoming_seq:
            print(f"[DTLS] ❌ Drop: Replay E2E {packet.source_nid} (Seq {packet.seq_num})")
            return
        session.incoming_seq = packet.seq_num

        # 3. Parse Service Payload & Dispatch
        try:
            data = json.loads(packet.payload)
            service_name = data.get('srv')
            client_id = data.get('cid')
            content = data.get('dat')
            
            print(f"\n🔐 [E2E MESSAGE] De: {packet.source_nid} -> Serviço: '{service_name}' (Client {client_id})")
            
            if service_name in self.services:
                self.services[service_name](packet.source_nid, client_id, content)
            else:
                print(f"   ⚠️ Serviço '{service_name}' não encontrado/registado.")

        except Exception as e:
            print(f"[DTLS] Erro processamento payload de {packet.source_nid}: {e}")
