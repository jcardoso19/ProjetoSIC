import json

class Packet:
    def __init__(self, source_nid, dest_nid, payload, msg_type="DATA", seq_num=0, mac=None):
        self.source_nid = source_nid
        self.dest_nid = dest_nid
        self.payload = payload
        self.msg_type = msg_type
        self.seq_num = seq_num
        self.mac = mac

    def to_bytes(self):
        """Converte o objeto Packet para uma string JSON em bytes."""
        data = {
            "src": self.source_nid,
            "dst": self.dest_nid,
            "pld": self.payload,
            "typ": self.msg_type,
            "seq": self.seq_num
        }
        if self.mac:
            data["mac"] = self.mac
        return json.dumps(data).encode('utf-8')

    def get_header_bytes(self):
        """
        Garante AAD consistente para o AES-GCM (string com pipes).
        """
        try:
            sequence = int(self.seq_num)
        except:
            sequence = 0
            
        header_str = f"{self.source_nid}|{self.dest_nid}|{self.msg_type}|{sequence}"
        return header_str.encode('utf-8')

    @staticmethod
    def from_bytes(data_bytes):
        """
        Versão robusta: Ignora erros de descodificação e limpa lixo.
        """
        try:
            # 1. Decodificar ignorando bytes inválidos (EVITA O CRASH 0x83)
            raw_str = data_bytes.decode('utf-8', errors='ignore')
            
            # 2. Limpar caracteres nulos e espaços extra
            clean_str = raw_str.strip().replace('\x00', '')
            
            # 3. Encontrar o JSON real (ignora lixo antes do '{' e depois do '}')
            start = clean_str.find('{')
            end = clean_str.rfind('}')
            
            if start == -1 or end == -1:
                return None
                
            json_str = clean_str[start : end + 1]
            data = json.loads(json_str)
            
            return Packet(
                source_nid=data.get("src"),
                dest_nid=data.get("dst"),
                payload=data.get("pld"),
                msg_type=data.get("typ"),
                seq_num=data.get("seq", 0),
                mac=data.get("mac")
            )
        except Exception as e:
            # Silenciar erros de parsing para não poluir o log
            # print(f"[PROTOCOL] Erro ignorado: {e}")
            return None

# Constantes
MSG_TYPE_HELLO = "HELLO"
MSG_TYPE_HELLO_ACK = "HELLO_ACK"
MSG_TYPE_DATA = "DATA"
MSG_TYPE_HEARTBEAT = "HEARTBEAT"
MSG_TYPE_E2E_HELLO = "E2E_HELLO"
MSG_TYPE_E2E_HELLO_ACK = "E2E_HELLO_ACK"
MSG_TYPE_E2E_DATA = "E2E_DATA"  