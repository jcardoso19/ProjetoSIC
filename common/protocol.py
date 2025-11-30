import struct
import json
#consts
MSG_TYPE_DATA = 1
MSG_TYPE_HEARTBEAT = 2

class Packet:
    def __init__(self, source_nid, dest_nid, payload, msg_type=MSG_TYPE_DATA):
        self.source_nid = source_nid 
        self.dest_nid = dest_nid    
        self.msg_type = msg_type    
        self.payload = payload        

    def to_bytes(self):
        """Converte o objeto Packet em bytes para enviar pelo Bluetooth"""

        data = {
            "src": self.source_nid,
            "dst": self.dest_nid,
            "type": self.msg_type,
            "pld": self.payload
        }
        return json.dumps(data).encode('utf-8')

    @staticmethod
    def from_bytes(data_bytes):
        """Reconstrói o Packet a partir dos bytes recebidos"""
        try:
            data = json.loads(data_bytes.decode('utf-8'))
            return Packet(data['src'], data['dst'], data['pld'], data['type'])
        except Exception as e:
            print(f"[PROTOCOL] Erro ao descodificar pacote: {e}")
            return None