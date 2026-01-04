import simplepyble
import time

# O TEU MAC FIXO
TARGET_SINK_MAC = "E0:D3:62:D7:32:17"

def scan_for_candidates(adapter, duration=5000):
    print(f"[SCAN] A procurar EXCLUSIVAMENTE o endereço: {TARGET_SINK_MAC}")
    
    try:
        adapter.scan_for(duration)
    except Exception as e:
        print(f"[WARN] Erro no scan: {e}")
        return []

    results = adapter.scan_get_results()
    
    for device in results:
        addr = device.address()
        rssi = device.rssi()
        
        # Comparação direta. Se não for igual, ignora.
        if addr == TARGET_SINK_MAC:
            print(f"   🎯 ALVO ENCONTRADO: {addr} | RSSI: {rssi}")
            return [{
                "device_obj": device,
                "name": "SINK_DEVICE",
                "address": addr,
                "hops": 0,
                "rssi": rssi
            }]
            
    print(f"   ❌ O MAC {TARGET_SINK_MAC} não está visível no ar.")
    return []