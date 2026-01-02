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
            # Carregar o certificado e guardar também o PEM cru para envio
            with open(local_cert_path, "rb") as f:
                self.local_cert_pem = f.read()
                
    def encrypt_packet(self, session_key, packet):
        """
        Encrypts the packet payload using AES-GCM.
        Updates packet.payload (Base64 of Nonce+CT) and packet.mac (Base64 of Tag).
        AAD = packet header.
        """
        if not session_key:
            raise ValueError("Session Key is None")

        aesgcm = AESGCM(session_key)
        nonce = os.urandom(12)
        aad = packet.get_header_bytes()
        
        # Payload must be bytes
        if isinstance(packet.payload, str):
            data = packet.payload.encode('utf-8')
        else:
            data = packet.payload # Assume bytes

        # AESGCM.encrypt(nonce, data, aad) returns Ciphertext + Tag.
        ct_and_tag = aesgcm.encrypt(nonce, data, aad)
        
        tag = ct_and_tag[-16:]
        ciphertext = ct_and_tag[:-16]
        
        # Format: Payload = Nonce + Ciphertext (Base64)
        #         MAC     = Tag (Base64)
        packet.payload = base64.b64encode(nonce + ciphertext).decode('utf-8')
        packet.mac = base64.b64encode(tag).decode('utf-8')

    def decrypt_packet(self, session_key, packet):
        """
        Decrypts packet payload. Validates AAD (Header).
        Returns True if success, False otherwise.
        """
        if not session_key:
            raise ValueError("Session Key is None")
            
        aesgcm = AESGCM(session_key)
        aad = packet.get_header_bytes()
        
        try:
            # Decode Base64
            enc_payload = base64.b64decode(packet.payload)
            tag = base64.b64decode(packet.mac)
            
            nonce = enc_payload[:12]
            ciphertext = enc_payload[12:]
            
            # Reconstruct for generic API: standard decrypt expects CT+Tag
            ct_and_tag = ciphertext + tag
            
            plaintext = aesgcm.decrypt(nonce, ct_and_tag, aad)
            
            packet.payload = plaintext.decode('utf-8')
            return True
        except Exception as e:
            print(f"[SEC] Decryption/Auth Failed: {e}")
            return False

    def _load_cert(self, path):
        if not os.path.exists(path):
            # Fallback for different execution contexts
            if os.path.exists(f"../{path}"):
                path = f"../{path}"
            elif os.path.exists(f"support/{path}"): # Sometimes certs are in support/certs
                 path = f"support/{path}"
            else:
                 raise FileNotFoundError(f"Root CA not found at {path}")

        with open(path, "rb") as f:
            return x509.load_pem_x509_certificate(f.read(), default_backend())

    def load_private_key(self, path):
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
            
    def load_certificate(self, path):
        with open(path, "rb") as f:
            return x509.load_pem_x509_certificate(f.read(), default_backend())

    def verify_certificate(self, cert_pem_bytes):
        """
        Verifies a PEM encoded certificate against the Root CA.
        Returns the public key if valid, raises Exception otherwise.
        """
        try:
            cert = x509.load_pem_x509_certificate(cert_pem_bytes, default_backend())
            
            # Verify signature
            self.root_ca_public_key.verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                hashes.SHA256() # Assuming SHA256 was used in pkiGenerator
            )
            
            # Check expiration (simplified)
            # import datetime
            # now = datetime.datetime.now(datetime.timezone.utc)
            # if now < cert.not_valid_before or now > cert.not_valid_after:
            #    raise Exception("Certificate expired")

            return cert.public_key()
        except Exception as e:
            print(f"[SEC] Certificate Verification Failed: {e}")
            raise e

    def derive_session_key(self, local_private_key, peer_public_key):
        """
        Performs ECDH and derives a session key using HKDF.
        """
        shared_secret = local_private_key.exchange(ec.ECDH(), peer_public_key)
        
        # Derive a symmetric key (e.g., for AES or HMAC)
        session_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32, # 256 bits
            salt=None,
            info=b'sic_protocol_session_key',
            backend=default_backend()
        ).derive(shared_secret)
        
        return session_key
