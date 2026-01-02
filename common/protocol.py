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
        src_bytes = self.source_nid.encode('utf-8')
        dst_bytes = self.dest_nid.encode('utf-8')
        typ_bytes = self.msg_type.encode('utf-8')
        seq_bytes = self.seq_num.to_bytes(4, byteorder='big')  # 4 bytes fixos

        return src_bytes + dst_bytes + typ_bytes + seq_bytes



    @staticmethod
    def from_bytes(data_bytes):
        """
        Reconstrói um objeto Packet a partir de bytes, com limpeza de ruído 
        da transmissão Bluetooth.
        """
        try:
            # Converte bytes para string
            raw_str = data_bytes.decode('utf-8')
            
            # --- LIMPEZA DE LIXO ---
            # Remove caracteres nulos (\x00) e espaços invisíveis que corrompem o JSON
            clean_str = raw_str.strip().replace('\x00', '')
            
            # Tenta descodificar o JSON limpo
            data = json.loads(clean_str)
            
            return Packet(
                source_nid=data.get("src"),
                dest_nid=data.get("dst"),
                payload=data.get("pld"),
                msg_type=data.get("typ"),
                seq_num=data.get("seq", 0),
                mac=data.get("mac")
            )
        except Exception as e:
            print(f"[PROTOCOL] Erro ao descodificar: {e}")
            return None

# --- CONSTANTES DE PROTOCOLO (Hop-by-Hop) ---
MSG_TYPE_HELLO = "HELLO"
MSG_TYPE_HELLO_ACK = "HELLO_ACK"
MSG_TYPE_DATA = "DATA"
MSG_TYPE_HEARTBEAT = "HEARTBEAT"

# --- CONSTANTES DE PROTOCOLO (End-to-End / DTLS) ---
# Estas são as que estavam a faltar e causaram o erro
MSG_TYPE_E2E_HELLO = "E2E_HELLO"
MSG_TYPE_E2E_HELLO_ACK = "E2E_HELLO_ACK"
MSG_TYPE_E2E_DATA = "E2E_DATA"