import simplepyble
import struct


PROJECT_DEVICE_PREFIX = "iPhone de João" # <---- MUDAR AQUI

MANUFACTURER_ID = 0xFFFF 

def scan_for_candidates(adapter, timeout=3000):
    """
    Faz scan e retorna uma lista de dicionários com potenciais uplinks,
    ordenados pelo critério do projeto (menor hops, melhor sinal).
    """
    print(f"[SCAN] A procurar dispositivos '{PROJECT_DEVICE_PREFIX}...' por {timeout}ms")
    
    adapter.scan_for(timeout)
    results = adapter.scan_get_results()
    
    candidates = []

    for device in results:
        name = device.identifier()
        mac = device.address()
        rssi = device.rssi()
        
        if not name.startswith(PROJECT_DEVICE_PREFIX):
            continue

        m_data = device.manufacturer_data()
        hops = 99

        if MANUFACTURER_ID in m_data:

            raw_bytes = m_data[MANUFACTURER_ID]

            if len(raw_bytes) > 0:
                hops = int(raw_bytes[0]) 

        if "SINK" in name:
            hops = 0

        print(f"[FOUND] {name} ({mac}) | Hops: {hops} | RSSI: {rssi}")

        candidates.append({
            "device_obj": device,
            "name": name,
            "mac": mac,
            "hops": hops,
            "rssi": rssi
        })
    candidates.sort(key=lambda x: (x['hops'], -x['rssi']))

    return candidates