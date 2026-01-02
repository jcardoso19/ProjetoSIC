import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Tipos de Mensagem
MSG_TYPE_DATA = 1
MSG_TYPE_HEARTBEAT = 2
MSG_TYPE_HELLO = 3      
MSG_TYPE_HELLO_ACK = 4   
MSG_TYPE_E2E_HELLO = 10
MSG_TYPE_E2E_HELLO_ACK = 11
MSG_TYPE_E2E_DATA = 12
MSG_TYPE_KEY_EXCHANGE = 5

class Packet:
    def __init__(self, source_nid, dest_nid, payload, msg_type=MSG_TYPE_DATA, seq_num=0, mac=""):
        self.source_nid = str(source_nid)
        self.dest_nid = str(dest_nid)
        self.msg_type = msg_type
        self.payload = payload 
        
        self.seq_num = seq_num  
        self.mac = mac          

    def to_dict(self):
        """Cria um dicionário (útil para serialização)"""
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
        Retorna os bytes para assinar o KEY_EXCHANGE (Handshake).
        (Não usamos isto para dados normais, pois esses levam AES-GCM)
        """
        data_dict = self.to_dict()
        return json.dumps(data_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')

    def encrypt(self, session_key):
        """
        ENCRIPTAÇÃO AES-GCM:
        1. Gera um Nonce aleatório.
        2. Usa o cabeçalho (src, dst, type, seq) como Dados Associados (AAD) para proteger contra alterações.
        3. Encripta o Payload.
        """
        if not session_key: return

        # AES-GCM requer a chave em bytes
        aesgcm = AESGCM(session_key)
        nonce = os.urandom(12) # 12 bytes é o padrão de segurança para GCM
        
        # O que queremos esconder (Payload)
        plaintext = self.payload.encode('utf-8')
        
        # O que queremos proteger contra adulteração (Cabeçalho)
        # Criamos um esqueleto do pacote com payload vazio para servir de AAD
        aad_dict = self.to_dict()
        aad_dict['pld'] = "" 
        aad = json.dumps(aad_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')
        
        # Encriptar (Gera Ciphertext + Tag de Integridade)
        ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
        
        # Atualizar o pacote: Payload passa a ser "Nonce + Ciphertext" em Hexadecimal
        self.payload = (nonce + ciphertext).hex()
        self.mac = "AES-GCM" # Marcador para quem recebe saber que está encriptado

    def decrypt(self, session_key):
        """
        DESENCRIPTAÇÃO AES-GCM:
        Tenta abrir o pacote. Se a chave estiver errada ou alguém tiver mexido 
        num bit que seja (payload ou cabeçalho), isto lança erro.
        """
        if self.mac != "AES-GCM":
            return False # Não está encriptado, rejeitamos se a sessão for segura

        try:
            aesgcm = AESGCM(session_key)
            
            # Converter de Hex para Bytes
            raw_data = bytes.fromhex(self.payload)
            nonce = raw_data[:12]      # Primeiros 12 bytes são o Nonce
            ciphertext = raw_data[12:] # O resto é a mensagem cifrada
            
            # Reconstruir os Dados Associados (AAD) para verificar o cabeçalho
            aad_dict = self.to_dict()
            aad_dict['pld'] = ""
            aad = json.dumps(aad_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')
            
            # Desencriptar
            plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
            
            # Restaurar o payload original (texto limpo)
            self.payload = plaintext.decode('utf-8')
            return True
            
        except Exception as e:
            print(f"[SEC] ❌ Falha na desencriptação (Chave errada ou dados corrompidos): {e}")
            return False

    def to_bytes(self):
        """Converte o pacote para envio Bluetooth"""
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