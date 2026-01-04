
import os
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

# Configuração
OUTPUT_DIR = "../certs"
CURVE = ec.SECP521R1() # O projeto pede P-521 (Segurança Elevada)

def generate_private_key(filename):
    """Gera uma chave privada de Curva Elíptica e guarda em ficheiro."""
    key = ec.generate_private_key(CURVE)
    
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    with open(filename, "wb") as f:
        f.write(pem)
    
    return key

def save_certificate(cert, filename):
    """Guarda o certificado em formato PEM."""
    with open(filename, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

def create_root_ca():
    """Cria a Autoridade de Certificação (Auto-assinada)."""
    print("[*] A gerar Root CA...")
    key = generate_private_key(f"{OUTPUT_DIR}/root_ca.key")
    
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"PT"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Projeto SIC"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"SIC Root CA"),
    ])
    
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    
    save_certificate(cert, f"{OUTPUT_DIR}/root_ca.crt")
    return key, subject

def create_entity_cert(name, role, ca_key, ca_subject):
    """Cria um certificado para uma entidade (Sink ou Node), assinado pela CA."""
    print(f"[*] A gerar certificado para: {name} ({role})...")
    key = generate_private_key(f"{OUTPUT_DIR}/{name}.key")
    
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"PT"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Projeto SIC"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, role), # Importante para distinguir Sink de Node
        x509.NameAttribute(NameOID.COMMON_NAME, name),
    ])
    
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_subject) # Assinado pela CA
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    
    save_certificate(cert, f"{OUTPUT_DIR}/{name}.crt")

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    ca_key, ca_subject = create_root_ca()
    
    create_entity_cert("sink", u"Sink", ca_key, ca_subject)
    
    create_entity_cert("node1", u"IoT Device", ca_key, ca_subject)
    create_entity_cert("node2", u"IoT Device", ca_key, ca_subject)
    create_entity_cert("node3", u"IoT Device", ca_key, ca_subject)
    create_entity_cert("node4", u"IoT Device", ca_key, ca_subject)


    
    print("\nSucesso! Certificados guardados na pasta 'certs'.")

if __name__ == "__main__":
    main()