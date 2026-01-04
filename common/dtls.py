from common.protocol import Packet, MSG_TYPE_E2E_HELLO, MSG_TYPE_E2E_HELLO_ACK, MSG_TYPE_E2E_DATA
from common.security import SecurityManager
import json
import base64
import time

class DTLSSession:
    def __init__(self, peer_nid, session_key):
        self.peer_nid = peer_nid
        self.session_key = session_key
        self.outgoing_seq = 0
        self.incoming_seq = -1 

class DTLSManager:
    def __init__(self, my_nid, security_manager, router_send_func):
        self.my_nid = my_nid
        self.sec_manager = security_manager
        self.send_func = router_send_func 
        self.sessions = {} 
        self.pending_handshakes = set()
        self.services = {} 

    def register_service(self, service_name, callback):
        self.services[service_name] = callback
        print(f"[DTLS] Serviço '{service_name}' registado.")

    def start_handshake(self, peer_nid):
        if peer_nid in self.sessions: 
            return # Já ligado
        
        # --- CORREÇÃO: Evitar spam de pedidos ---
        if peer_nid in self.pending_handshakes:
            print(f"[DTLS] Handshake com {peer_nid} já em curso. Aguarde...")
            return
        # ----------------------------------------

        print(f"[DTLS] A iniciar handshake E2E com {peer_nid}...")
        
        if not self.sec_manager.local_cert_pem: return

        pkt = Packet(
            source_nid=self.my_nid,
            dest_nid=peer_nid,
            msg_type=MSG_TYPE_E2E_HELLO,
            payload=self.sec_manager.local_cert_pem.decode('utf-8')
        )
        self.pending_handshakes.add(peer_nid)
        self.send_func(pkt)

    def process_packet(self, packet):
        if packet.msg_type == MSG_TYPE_E2E_HELLO:
            print(f"[DTLS] 🤝 E2E HELLO recebido de {packet.source_nid}")
            try:
                peer_cert_pem = packet.payload.encode('utf-8')
                peer_pub_key = self.sec_manager.verify_certificate(peer_cert_pem)
                session_key = self.sec_manager.derive_session_key(
                    self.sec_manager.local_private_key, peer_pub_key
                )
                self.sessions[packet.source_nid] = DTLSSession(packet.source_nid, session_key)
                print(f"[DTLS] Sessão E2E estabelecida com {packet.source_nid}")
                
                ack_pkt = Packet(
                    source_nid=self.my_nid,
                    dest_nid=packet.source_nid,
                    msg_type=MSG_TYPE_E2E_HELLO_ACK,
                    payload=self.sec_manager.local_cert_pem.decode('utf-8')
                )
                self.send_func(ack_pkt)
            except Exception as e:
                print(f"[DTLS] Falha no Handshake E2E: {e}")

        elif packet.msg_type == MSG_TYPE_E2E_HELLO_ACK:
            print(f"[DTLS] 🤝 E2E HELLO_ACK recebido de {packet.source_nid}")
            try:
                peer_cert_pem = packet.payload.encode('utf-8')
                peer_pub_key = self.sec_manager.verify_certificate(peer_cert_pem)
                session_key = self.sec_manager.derive_session_key(
                    self.sec_manager.local_private_key, peer_pub_key
                )
                self.sessions[packet.source_nid] = DTLSSession(packet.source_nid, session_key)
                if packet.source_nid in self.pending_handshakes:
                    self.pending_handshakes.remove(packet.source_nid)
                print(f"[DTLS] Sessão E2E estabelecida com {packet.source_nid} (Active)")
            except Exception as e:
                print(f"[DTLS] Falha no Handshake E2E (ACK): {e}")

        elif packet.msg_type == MSG_TYPE_E2E_DATA:
            self._handle_data(packet)

    def send_data(self, peer_nid, message_str, service="Inbox", client_id=0):
        if peer_nid not in self.sessions:
            print(f"[DTLS] Erro: Sem sessão. A iniciar handshake...")
            self.start_handshake(peer_nid)
            return

        session = self.sessions[peer_nid]
        
        payload_dict = { "srv": service, "cid": client_id, "dat": message_str }
        payload_bytes = json.dumps(payload_dict).encode('utf-8')
        
        e2e_pkt = Packet(
            source_nid=self.my_nid,
            dest_nid=peer_nid,
            msg_type=MSG_TYPE_E2E_DATA,
            seq_num=session.outgoing_seq,
            payload=payload_bytes
        )
        
        self.sec_manager.encrypt_packet(session.session_key, e2e_pkt)
        e2e_pkt.payload = f"{e2e_pkt.seq_num}::{e2e_pkt.mac}::{e2e_pkt.payload}"

        session.outgoing_seq += 1
        self.send_func(e2e_pkt)
        print(f"[DTLS] 📤 Mensagem E2E enviada para {peer_nid} (Seq {e2e_pkt.seq_num})")

    def _handle_data(self, packet):
        session = self.sessions.get(packet.source_nid)
        if not session: return

        try:
            if isinstance(packet.payload, str) and "::" in packet.payload:
                parts = packet.payload.split("::", 2)
                if len(parts) == 3:
                    packet.seq_num = int(parts[0])
                    packet.mac = parts[1]
                    packet.payload = parts[2]
        except: pass

        if not self.sec_manager.decrypt_packet(session.session_key, packet):
            print(f"[DTLS] ❌ Drop: Falha decifragem E2E de {packet.source_nid}")
            return

        if packet.seq_num <= session.incoming_seq: return
        session.incoming_seq = packet.seq_num

        try:
            data = json.loads(packet.payload)
            print(f"\n🔐 [E2E] {packet.source_nid}: {data.get('dat')}\n")
            if data.get('srv') in self.services:
                self.services[data.get('srv')](packet.source_nid, data.get('cid'), data.get('dat'))
        except: pass