import sys
import os
import asyncio
from cryptography import x509
from cryptography.hazmat.primitives import serialization

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../support/')))

from common.advertiser import BLEAdvertiser
from common.manageConnections import ConnectionManager

async def main():
    print("[SINK] A iniciar...")
    

    with open("certs/sink.crt", "rb") as f:
        my_cert_bytes = f.read()
    with open("certs/sink.key", "rb") as f:
        my_private_key = serialization.load_pem_private_key(f.read(), password=None)
        
    print(f"[SINK] Identidade carregada. Tamanho do cert: {len(my_cert_bytes)} bytes")


    connection_manager = ConnectionManager(my_cert_bytes, my_private_key)

    advertiser = BLEAdvertiser()
    

    print("[SINK] À espera de conexões Bluetooth...")
    await advertiser.start_advertising()

    while True:
        await asyncio.sleep(10)
        print("[SINK] Heartbeat (simulado)...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[SINK] A desligar.")