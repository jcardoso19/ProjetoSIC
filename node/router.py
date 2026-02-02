from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK, MSG_TYPE_DATA, MSG_TYPE_HEARTBEAT
import copy
import time
import json
import threading 

class Router:
    def __init__(self, my_nid, connection_manager, security_manager=None):
        self.my_nid = my_nid
        self.connection_manager = connection_manager
        self.security_manager = security_manager
        # Tabela: NID_Destino -> MAC_Vizinho (Next Hop)
        self.forwarding_table = {} 
        self.downlink_keys = {} 
        self.gatt_server = None
        self.last_seq_nums = {} 
        self.outgoing_seq_nums = {} 
        self.app_callback = None
        self.routed_messages_count = 0
        self.blocked_nids = set()
        self.rx_buffers = {} 

    def set_app_callback(self, callback): self.app_callback = callback
    def set_gatt_server(self, gatt_server): self.gatt_server = gatt_server
    def reset_buffer(self, connection):
        conn_key = connection if isinstance(connection, str) else id(connection)
        self.rx_buffers[conn_key] = bytearray()
        
    def block_heartbeat(self, nid): self.blocked_nids.add(nid)
    def unblock_heartbeat(self, nid): 
        if nid in self.blocked_nids: self.blocked_nids.remove(nid)

    def _get_key_for_connection(self, connection):
        if self.connection_manager.uplink and connection == self.connection_manager.uplink:
            return self.connection_manager.session_key
        if isinstance(connection, str) and connection in self.downlink_keys:
            return self.downlink_keys[connection]
        return None

    def process_packet(self, raw_bytes, source_connection):
        conn_key = source_connection if isinstance(source_connection, str) else id(source_connection)
        if conn_key not in self.rx_buffers: self.rx_buffers[conn_key] = bytearray()
        self.rx_buffers[conn_key].extend(raw_bytes)
        
        while True:
            buf = self.rx_buffers[conn_key]
            if len(buf) < 4: break
            msg_len = int.from_bytes(buf[:4], 'big')
            if len(buf) < 4 + msg_len: break
            packet_bytes = bytes(buf[4 : 4 + msg_len])
            del buf[:4 + msg_len]
            self._handle_complete_packet(packet_bytes, source_connection)

    def _handle_complete_packet(self, packet_bytes, source_connection):
        packet = Packet.from_bytes(packet_bytes)
        if not packet: return
        if packet.source_nid == self.my_nid: return
        
        # 1. Routing Learning (Simples): Se recebo algo de X por esta conexão, X está aqui.
        if packet.source_nid not in self.forwarding_table:
             self.forwarding_table[packet.source_nid] = source_connection

        if packet.msg_type in [MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK]:
            self.handle_handshake(packet, source_connection)
            return

        if self.security_manager:
            session_key = self._get_key_for_connection(source_connection)
            if not session_key or not self.security_manager.decrypt_packet(session_key, packet):
                return
            last_seq = self.last_seq_nums.get(packet.source_nid, -1)
            if packet.seq_num <= last_seq: return
            self.last_seq_nums[packet.source_nid] = packet.seq_num
        
        if packet.msg_type == MSG_TYPE_HEARTBEAT:
            if hasattr(self, 'on_heartbeat'): self.on_heartbeat(packet.source_nid)
            self.propagate_heartbeat(packet)
            return 
            
        if packet.dest_nid == self.my_nid:
            if self.app_callback: self.app_callback(packet)
        else:
            self.forward(packet)

    def handle_handshake(self, packet, source_connection):
        if packet.msg_type == MSG_TYPE_HELLO:
            # print(f"[ROUTER] 🤝 HELLO de {packet.source_nid}")
            try:
                self.reset_buffer(source_connection)
                child_pub_key = self.security_manager.verify_certificate(packet.payload.encode('utf-8'))
                session_key = self.security_manager.derive_session_key(self.security_manager.local_private_key, child_pub_key)
                
                # Registar Downlink
                self.downlink_keys[source_connection] = session_key
                self.last_seq_nums[packet.source_nid] = -1
                self.forwarding_table[packet.source_nid] = source_connection
                
                ack_pkt = Packet(source_nid=self.my_nid, dest_nid=packet.source_nid, msg_type=MSG_TYPE_HELLO_ACK, payload=self.security_manager.local_cert_pem.decode('utf-8'))
                threading.Timer(0.5, lambda: self.forward(ack_pkt)).start()
            except Exception as e: pass

    def forward(self, packet):
        if packet.msg_type == MSG_TYPE_HEARTBEAT and packet.dest_nid in self.blocked_nids: return
        
        # Lógica de Forwarding: 
        # 1. Tenta encontrar na tabela.
        # 2. Se não estiver na tabela, manda para o UPLINK (Default Gateway).
        target_conn = self.forwarding_table.get(packet.dest_nid)
        if not target_conn:
            target_conn = self.connection_manager.uplink
        
        if not target_conn: return # Packet drop (nowhere to go)

        if packet.msg_type not in [MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK]:
            self.routed_messages_count += 1
            conn_key = target_conn if isinstance(target_conn, str) else "UPLINK"
            packet.seq_num = self.outgoing_seq_nums.get(conn_key, 0) + 1
            self.outgoing_seq_nums[conn_key] = packet.seq_num
            key = self._get_key_for_connection(target_conn)
            if key: self.security_manager.encrypt_packet(key, packet)

        data_bytes = packet.to_bytes()
        full_payload = len(data_bytes).to_bytes(4, 'big') + data_bytes
        CHUNK_SIZE = 100

        if isinstance(target_conn, str): 
            if self.gatt_server:
                for i in range(0, len(full_payload), CHUNK_SIZE):
                    self.gatt_server.send_data(full_payload[i : i + CHUNK_SIZE])
                    time.sleep(0.15)
        else: 
            self.connection_manager.send_packet(packet)
            
    def propagate_heartbeat(self, original_packet):
        for mac_conn in self.downlink_keys.keys():
            pkt = copy.deepcopy(original_packet)
            # Propaga para todos os filhos (Downlinks)
            # Como é broadcast na sub-árvore, o dest_nid não é critico aqui se usarmos flooding,
            # mas vamos manter a lógica de enviar para os MACs conhecidos.
            self.forward_to_mac(pkt, mac_conn)

    def forward_to_mac(self, packet, mac_conn):
        """Helper para enviar diretamente para um MAC específico (usado no flood de HB)"""
        # (Reutiliza lógica do forward mas força o destino)
        conn_key = mac_conn
        packet.seq_num = self.outgoing_seq_nums.get(conn_key, 0) + 1
        self.outgoing_seq_nums[conn_key] = packet.seq_num
        key = self.downlink_keys.get(mac_conn)
        if key: self.security_manager.encrypt_packet(key, packet)
        
        data_bytes = packet.to_bytes()
        full_payload = len(data_bytes).to_bytes(4, 'big') + data_bytes
        CHUNK_SIZE = 100
        if self.gatt_server:
            for i in range(0, len(full_payload), CHUNK_SIZE):
                self.gatt_server.send_data(full_payload[i : i + CHUNK_SIZE])
                time.sleep(0.15)

    def send_message(self, dest_nid, message):
        pkt = Packet(self.my_nid, dest_nid, message)
        self.forward(pkt)

    def drop_connection(self, device_mac: str):
        if not device_mac: return
        try:
            if device_mac in self.downlink_keys: del self.downlink_keys[device_mac]
            to_remove = [nid for nid, conn in self.forwarding_table.items() if conn == device_mac]
            for nid in to_remove:
                if nid in self.forwarding_table: del self.forwarding_table[nid]
            if device_mac in self.rx_buffers: del self.rx_buffers[device_mac]
        except: pass