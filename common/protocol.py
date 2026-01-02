import json

MSG_TYPE_DATA = 1
MSG_TYPE_HEARTBEAT = 2
MSG_TYPE_HELLO = 3      
MSG_TYPE_HELLO_ACK = 4   
MSG_TYPE_E2E_HELLO = 10
MSG_TYPE_E2E_HELLO_ACK = 11
MSG_TYPE_E2E_DATA = 12

class Packet:
    def __init__(self, source_nid, dest_nid, payload, msg_type=MSG_TYPE_DATA, seq_num=0, mac=""):
        self.source_nid = str(source_nid)
        self.dest_nid = str(dest_nid)
        self.msg_type = msg_type
        self.payload = payload 
        
        self.seq_num = seq_num  
        self.mac = mac          

    def to_dict(self):
        """Cria um dicionário (útil para assinar apenas os dados, ignorando o campo mac atual)"""
        return {
            "src": self.source_nid,
            "dst": self.dest_nid,
            "type": self.msg_type,
            "seq": self.seq_num,
            "pld": self.payload
        }

    def get_header_bytes(self):
        """Retorna bytes do cabeçalho (Src, Dst, Type, Seq) para AAD (Authenticated Encryption)"""
        header = {
            "src": self.source_nid,
            "dst": self.dest_nid,
            "type": self.msg_type,
            "seq": self.seq_num
        }
        return json.dumps(header, sort_keys=True, separators=(',', ':')).encode('utf-8')

    def get_bytes_for_signing(self):
        """
        Retorna a sequência de bytes exata que deve ser assinada.
        Garantes que a ordem das chaves no JSON é sempre a mesma (sort_keys=True).
        """
        data_dict = self.to_dict()
        return json.dumps(data_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')

    def to_bytes(self):
        """Converte o pacote completo (com MAC) para envio Bluetooth"""
        data = self.to_dict()
        data['mac'] = self.mac
        return json.dumps(data, separators=(',', ':')).encode('utf-8')

    @staticmethod
    def from_bytes(data_bytes):
        try:
            data = json.loads(data_bytes.decode('utf-8'))
            
            return Packet(
                source_nid=data.get('src'),
                dest_nid=data.get('dst'),
                payload=data.get('pld'),
                msg_type=data.get('type', MSG_TYPE_DATA),
                seq_num=data.get('seq', 0),
                mac=data.get('mac', "")
            )
        except Exception as e:
            print(f"[PROTOCOL] Erro ao descodificar: {e}")
            return None