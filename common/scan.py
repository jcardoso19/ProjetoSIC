import simplepyble
import time

# O TEU MAC FIXO
TARGET_SINK_MAC = "5C:BA:EF:CC:98:10"
TARGET_MAC = "5C:BA:EF:CC:98:10"

def scan_for_candidates(adapter, duration=5000):
    print(f"[SCAN] A procurar EXCLUSIVAMENTE o endereço: {TARGET_SINK_MAC}")
def scan_for_candidates(adapter, duration=5000):
    print(f"[SCAN] A procurar alvo: {TARGET_MAC}")
    
    try:
        adapter.scan_for(duration)
    except Exception as e:
        print(f"[WARN] Erro no scan: {e}")
    except:
        return []

    results = adapter.scan_get_results()
    
    for device in results:
        addr = device.address()
        rssi = device.rssi()
        
        # Comparação direta. Se não for igual, ignora.
        if addr == TARGET_SINK_MAC:
            print(f"   🎯 ALVO ENCONTRADO: {addr} | RSSI: {rssi}")
            return [{
        if device.address() == TARGET_MAC:
            print(f"   ENCONTRADO: {device.address()} RSSI: {device.rssi()}")
            return [{
                "device_obj": device,
                "name": "SINK_DEVICE",
                "address": addr,
                "hops": 0,
                "rssi": rssi
            }]
            
    print(f"   ❌ O MAC {TARGET_SINK_MAC} não está visível no ar.")
    return []
                "name": "SINK_FIXO",
                "address": device.address(),
                "hops": 0,
                "rssi": device.rssi()
            }]
            
    print(f"   NAO ENCONTRADO: {TARGET_MAC}")
    return []