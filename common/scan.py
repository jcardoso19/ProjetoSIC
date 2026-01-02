import simplepyble
import time

TARGET_MAC = "5C:BA:EF:CC:98:10"

def scan_for_candidates(adapter, duration=5000):
    print(f"[SCAN] A procurar alvo: {TARGET_MAC}")
    
    try:
        adapter.scan_for(duration)
    except:
        return []

    results = adapter.scan_get_results()
    
    for device in results:
        if device.address() == TARGET_MAC:
            print(f"   ENCONTRADO: {device.address()} RSSI: {device.rssi()}")
            return [{
                "device_obj": device,
                "name": "SINK_FIXO",
                "address": device.address(),
                "hops": 0,
                "rssi": device.rssi()
            }]
            
    print(f"   NAO ENCONTRADO: {TARGET_MAC}")
    return []