from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK, MSG_TYPE_DATA, MSG_TYPE_HEARTBEAT
import copy

class Router:
    def __init__(self, my_nid, connection_manager, security_manager=None):
        self.my_nid = my_nid
        self.connection_manager = connection_manager
        self.security_manager = security_manager
        
        self.forwarding_table = {} 
        self.downlink_keys = {} # Map: MAC (String) -> SessionKey (Bytes)
        self.gatt_server = None
        self.last_seq_nums = {} # Map: SourceNID -> LastSeqNum (Anti-Replay)
        self.outgoing_seq_nums = {} # Map: TargetConnection(MAC/Obj) -> CurrentSeqNum
        self.app_callback = None
        
        # Stats & Control
        self.routed_messages_count = 0
        self.blocked_nids = set() # NIDs para os quais não enviamos Heartbeats

    def set_app_callback(self, callback):
        self.app_callback = callback

    def set_gatt_server(self, gatt_server):
        self.gatt_server = gatt_server
        
    def block_heartbeat(self, nid):
        self.blocked_nids.add(nid)
        print(f"[CONTROL] Heartbeats bloqueados para {nid}")

    def unblock_heartbeat(self, nid):
        if nid in self.blocked_nids:
            self.blocked_nids.remove(nid)
            print(f"[CONTROL] Heartbeats desbloqueados para {nid}")

    def _get_key_for_connection(self, connection):
        # Se for o objeto Uplink (conexão raw)
        if self.connection_manager.uplink and connection == self.connection_manager.uplink:
            return self.connection_manager.session_key
        
        # Se for um MAC address (Downlink)
        if isinstance(connection, str) and connection in self.downlink_keys:
            return self.downlink_keys[connection]
            
        return None

    def process_packet(self, raw_bytes, source_connection):
        """Recebe bytes crus, descodifica e decide o destino"""
        packet = Packet.from_bytes(raw_bytes)
        if not packet:
            return

        # --- 1. Handshake (Plaintext) ---
        if packet.msg_type in [MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK]:
            self.handle_handshake(packet, source_connection)
            return

        # --- 2. Security Check (Decryption) ---
        if self.security_manager:
            session_key = self._get_key_for_connection(source_connection)
            
            if not session_key:
                # Pode ser um pacote de um nó que ainda não fez handshake?
                print(f"[SEC] ❌ Drop: Mensagem cifrada de fonte desconhecida/sem chave ({source_connection})")
                return

            # Tenta desencriptar
            if not self.security_manager.decrypt_packet(session_key, packet):
                print(f"[SEC] ❌ Drop: Falha na autenticação/desencriptação de {packet.source_nid}")
                return
            
            # --- Freshness Check (Anti-Replay) ---
            last_seq = self.last_seq_nums.get(packet.source_nid, -1)
            if packet.seq_num <= last_seq:
                print(f"[SEC] ❌ Drop: Replay Detectado de {packet.source_nid} (Seq: {packet.seq_num} <= {last_seq})")
                return
            
            self.last_seq_nums[packet.source_nid] = packet.seq_num
        
        print(f"[ROUTER] Packet recebido de {packet.source_nid} para {packet.dest_nid} (Seq: {packet.seq_num})")

        # --- 3. Routing ---
        # Aprender Rota
        if packet.source_nid not in self.forwarding_table:
            self.forwarding_table[packet.source_nid] = source_connection
            print(f"[TABLE] Nova rota aprendida: {packet.source_nid} via {source_connection}")

        if packet.dest_nid == self.my_nid:
            # Passa para a aplicação (DTLS Manager, etc)
            if self.app_callback:
                self.app_callback(packet)
            else:
                print(f"📥 [INBOX] Mensagem recebida: {packet.payload}")
            
            # Se for Heartbeat, avisar HeartbeatManager E propagar
            if packet.msg_type == MSG_TYPE_HEARTBEAT:
                if hasattr(self, 'on_heartbeat'):
                    self.on_heartbeat(packet.source_nid)
                self.propagate_heartbeat(packet)
                
        elif packet.msg_type == MSG_TYPE_HEARTBEAT:
             # Heartbeat que não é para mim? (Geralmente vem para BROADCAST ou MyNID)
             # Se veio do Uplink, devo propagar.
             self.propagate_heartbeat(packet)
        else:
            self.forward(packet)

    def propagate_heartbeat(self, original_packet):
        """Reenvia o Heartbeat para todos os Downlinks"""
        if not self.downlink_keys:
            return

        # Iterar vizinhos Downlink
        # Precisamos mapear MAC -> NID para usar o forward corretamente?
        # A forwarding_table tem NID -> MAC.
        # Vamos inverter temporariamente ou iterar.
        
        reverse_table = {v: k for k, v in self.forwarding_table.items()}
        
        for mac_conn in self.downlink_keys.keys():
            # Descobrir NID deste MAC
            target_nid = reverse_table.get(mac_conn)
            
            if target_nid:
                # Criar cópia e enviar
                # Nota: Sequence Number do pacote original é do Uplink.
                # O forward vai atribuir um novo SeqNum para o Downlink.
                pkt = copy.deepcopy(original_packet)
                pkt.dest_nid = target_nid
                # pkt.msg_type já é HEARTBEAT
                # Payload mantém-se "ALIVE" ou counter
                
                self.forward(pkt)

    def handle_handshake(self, packet, source_connection):
        if packet.msg_type == MSG_TYPE_HELLO:
            print(f"[ROUTER] 🤝 HELLO recebido de {packet.source_nid} (via {source_connection})")
            
            if not self.security_manager:
                print("[SEC] Erro: SecurityManager não configurado no Router.")
                return

            if not isinstance(source_connection, str):
                print("[SEC] Aviso: HELLO recebido de conexão não-string (Uplink?). Ignorando.")
                return
                
            try:
                # 1. Verificar Certificado do Filho
                child_cert_pem = packet.payload.encode('utf-8')
                child_pub_key = self.security_manager.verify_certificate(child_cert_pem)
                print(f"[SEC] Certificado de {packet.source_nid} validado.")
                
                # 2. Derivar Chave
                session_key = self.security_manager.derive_session_key(
                    self.security_manager.local_private_key,
                    child_pub_key
                )
                self.downlink_keys[source_connection] = session_key
                # Reset Sequência para este nó
                self.last_seq_nums[packet.source_nid] = -1
                print(f"[SEC] 🔐 Chave de Sessão para {packet.source_nid} derivada.")
                
                # 3. Enviar HELLO_ACK
                ack_pkt = Packet(
                    source_nid=self.my_nid,
                    dest_nid=packet.source_nid,
                    msg_type=MSG_TYPE_HELLO_ACK,
                    payload=self.security_manager.local_cert_pem.decode('utf-8')
                )
                
                if self.gatt_server:
                    self.gatt_server.send_data(ack_pkt.to_bytes())
                    print(f"[HANDSHAKE] HELLO_ACK enviado para {packet.source_nid}")
                
                self.forwarding_table[packet.source_nid] = source_connection
                self.outgoing_seq_nums[source_connection] = 0 # Inicia contador de saída
                
            except Exception as e:
                print(f"[SEC] Falha no Handshake com {packet.source_nid}: {e}")
            
    def forward(self, packet):
        # CONTROL: Block Heartbeat
        if packet.msg_type == MSG_TYPE_HEARTBEAT and packet.dest_nid in self.blocked_nids:
            # print(f"[CONTROL] Heartbeat bloqueado para {packet.dest_nid}")
            return

        # Clona para não estragar o pacote original se for usado localmente depois (embora aqui não seja)
        # Mas importante: se encaminharmos, temos de cifrar com a chave DO PRÓXIMO HOP.
        pkt_to_send = copy.deepcopy(packet)
        
        target_conn = None
        
        if packet.dest_nid in self.forwarding_table:
            target_conn = self.forwarding_table[packet.dest_nid]
        elif self.connection_manager.uplink:
            # Rota Default -> Uplink
            target_conn = self.connection_manager.uplink
        else:
            print(f"❌ [DROP] Sem rota para {packet.dest_nid}")
            return

        # STATS: Increment routed messages
        # Só conta se for forwarding (não se for origem minha?)
        # Requisito: "messages routed through the uplink".
        # Se eu envio, conta? "Routed" geralmente implica trânsito.
        # Mas "routed through the uplink since it was established".
        # Vamos contar todos os pacotes enviados para Uplink.
        if target_conn == self.connection_manager.uplink:
            self.routed_messages_count += 1

        # --- Update Sequence Number ---
        # Se NÃO for handshake, incrementamos o contador para este link
        if pkt_to_send.msg_type not in [MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK]:
             # Usa id(target_conn) se for objeto, ou a string se for MAC, como chave
             conn_key = target_conn
             if not isinstance(target_conn, str):
                 conn_key = "UPLINK" # Simplificação para o Uplink único
             
             current_seq = self.outgoing_seq_nums.get(conn_key, 0)
             current_seq += 1
             self.outgoing_seq_nums[conn_key] = current_seq
             pkt_to_send.seq_num = current_seq

        # --- Encriptação Hop-by-Hop ---
        if self.security_manager and pkt_to_send.msg_type not in [MSG_TYPE_HELLO, MSG_TYPE_HELLO_ACK]:
            key = self._get_key_for_connection(target_conn)
            if key:
                self.security_manager.encrypt_packet(key, pkt_to_send)
                # print(f"[SEC] Pacote encriptado para {packet.dest_nid}")
            else:
                print(f"[SEC] ⚠️ A enviar em Plaintext para {packet.dest_nid} (Sem Chave!)")

        # --- Envio Físico ---
        if isinstance(target_conn, str):
            # Downlink (GATT)
            if self.gatt_server:
                print(f"⬇️ [FORWARD] A descer para {packet.dest_nid} (Seq: {pkt_to_send.seq_num})")
                self.gatt_server.send_data(pkt_to_send.to_bytes())
        else:
            # Uplink (BLE Object)
            try:
                print(f"➡️ [FORWARD] A enviar para {packet.dest_nid} via Uplink (Seq: {pkt_to_send.seq_num})")
                target_conn.write_request(
                    "A07498CA-AD5B-474E-940D-16F1FBE7E8CD", 
                    "51FF12C6-1360-44E9-9577-081E200C0514", 
                    pkt_to_send.to_bytes()
                )
            except Exception as e:
                print(f"[ROUTER] Erro no forward Uplink: {e}")
                self.connection_manager.on_uplink_lost()

    def send_message(self, dest_nid, message):
        """Função para a UI usar (enviar mensagem nova)"""
        pkt = Packet(self.my_nid, dest_nid, message)
        self.forward(pkt)