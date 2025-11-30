from common.protocol import Packet

class Router:
    def __init__(self, my_nid, connection_manager):
        self.my_nid = my_nid
        self.connection_manager = connection_manager
    
        self.forwarding_table = {} 

    def process_packet(self, raw_bytes, source_connection):
        """Recebe bytes crus, descodifica e decide o destino"""
        packet = Packet.from_bytes(raw_bytes)
        if not packet:
            return

        print(f"[ROUTER] Packet recebido de {packet.source_nid} para {packet.dest_nid}")

        if packet.source_nid not in self.forwarding_table:
            self.forwarding_table[packet.source_nid] = source_connection
            print(f"[TABLE] Nova rota aprendida: {packet.source_nid} via {source_connection.address()}")

        if packet.dest_nid == self.my_nid:
            print(f"📥 [INBOX] Mensagem recebida: {packet.payload}")
        else:
            self.forward(packet)

    def forward(self, packet):
        if packet.dest_nid in self.forwarding_table:
            target_conn = self.forwarding_table[packet.dest_nid]
            print(f"➡️ [FORWARD] A enviar para {packet.dest_nid} via {target_conn.address()}")
        
        elif self.connection_manager.uplink:
            print(f"⬆️ [DEFAULT] Rota desconhecida. A subir para o Uplink...")
        else:
            print(f"❌ [DROP] Sem rota e sem Uplink. Pacote descartado.")

    def send_message(self, dest_nid, message):
        """Função para a UI usar (enviar mensagem nova)"""
        pkt = Packet(self.my_nid, dest_nid, message)
        self.forward(pkt)