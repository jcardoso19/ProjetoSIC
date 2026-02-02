import os
import base64
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class SecurityManager:
    def __init__(self, root_ca_path="certs/root_ca.crt", local_cert_path=None, local_key_path=None):
        self.root_ca_cert = self._load_cert(root_ca_path)
        self.root_ca_public_key = self.root_ca_cert.public_key()
        
        self.local_cert_pem = None
        self.local_private_key = None
        
        if local_cert_path and local_key_path:
            self.local_private_key = self.load_private_key(local_key_path)
            with open(local_cert_path, "rb") as f:
                self.local_cert_pem = f.read()
                
    def encrypt_packet(self, session_key, packet):
        if not session_key:
            raise ValueError("Session Key is None")

        aesgcm = AESGCM(session_key)
        nonce = os.urandom(12)
        aad = packet.get_header_bytes()
        
        
        if isinstance(packet.payload, str):
            data = packet.payload.encode('utf-8')
        else:
            data = packet.payload 

        ct_and_tag = aesgcm.encrypt(nonce, data, aad)
        
        tag = ct_and_tag[-16:]
        ciphertext = ct_and_tag[:-16]
        
        packet.payload = base64.b64encode(nonce + ciphertext).decode('utf-8')
        packet.mac = base64.b64encode(tag).decode('utf-8')

    def decrypt_packet(self, session_key, packet):
        if not session_key:
            raise ValueError("Session Key is None")
            
        aesgcm = AESGCM(session_key)
        aad = packet.get_header_bytes()
        
        try:
            enc_payload = base64.b64decode(packet.payload)
            tag = base64.b64decode(packet.mac)
            
            nonce = enc_payload[:12]
            ciphertext = enc_payload[12:]
            
            ct_and_tag = ciphertext + tag
            
            plaintext = aesgcm.decrypt(nonce, ct_and_tag, aad)
            
            packet.payload = plaintext.decode('utf-8')
            return True
        except Exception as e:

            return False

    def _load_cert(self, path):
        if not os.path.exists(path):
            if os.path.exists(f"../{path}"): path = f"../{path}"
            elif os.path.exists(f"support/{path}"): path = f"support/{path}"
            else: raise FileNotFoundError(f"Root CA not found at {path}")

        with open(path, "rb") as f:
            return x509.load_pem_x509_certificate(f.read(), default_backend())

    def load_private_key(self, path):
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
            
    def load_certificate(self, path):
        with open(path, "rb") as f:
            return x509.load_pem_x509_certificate(f.read(), default_backend())

    def verify_certificate(self, cert_pem_bytes):
        try:
            cert = x509.load_pem_x509_certificate(cert_pem_bytes, default_backend())
            self.root_ca_public_key.verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                ec.ECDSA(hashes.SHA256())
            )
            return cert.public_key()
        except Exception as e:
            print(f"[SEC] Certificate Verification Failed: {e}")
            raise e

    def derive_session_key(self, local_private_key, peer_public_key):
        shared_secret = local_private_key.exchange(ec.ECDH(), peer_public_key)
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b'sic_protocol_session_key',
            backend=default_backend()
        ).derive(shared_secret)
    
    def sign_data(self,data_bytes):
        signature = self.local_private_key.sign(
            data_bytes,
            ec.ECDSA(hashes.SHA256())
        )
        return base64.b64encode(signature).decode('utf-8')
    
    def verify_signature_with_cert(self, cert_pem_bytes, data_bytes, signature_b64):
        try:
            cert = x509.load_pem_x509_certificate(cert_pem_bytes)
            public_key = cert.public_key()
            signature = base64.b64decode(signature_b64)
            public_key.verify(
                signature,
                data_bytes,
                ec.ECDSA(hashes.SHA256())
            )
            return True
        except Exception as e:
            return False

    def get_sink_certificate(self):
        try:
            path = "certs/sink.crt"
            if not os.path.exists(path):
                path = "support/certs/sink.crt"
            with open(path, "rb") as f:
                return f.read()
        except:
            return None