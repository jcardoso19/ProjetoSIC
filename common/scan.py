import simplepyble
import time

# UUID do Serviço do Projeto
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"

# --- ATENÇÃO: ESTE É O MAC DA TUA PEN USB (O NOVO SINK) ---
TARGET_SINK_MAC = "E0:D3:62:D7:32:17"

def scan_for_candidates(adapter, duration=10000):
    print(f"[SCAN] A procurar SINK ({TARGET_SINK_MAC}) ou Serviço SIC durante {duration}ms...")
    
    try:
        adapter.scan_for(duration)
    except Exception as e:
        print(f"[WARN] Erro ao iniciar scan: {e}")
        return []

    results = adapter.scan_get_results()
    candidates = []
    
    for device in results:
        dev_name = device.identifier()
        dev_addr = device.address()
        
        # DEBUG: Ver o que estamos a apanhar
        print(f"   🔎 Vi: {dev_addr} | Nome: {dev_name} | RSSI: {device.rssi()}")

        is_valid = False
        
        # 1. É o MAC da Pen USB?
        if dev_addr == TARGET_SINK_MAC:
            print(f"   🎯 [ALVO] ENCONTREI O SINK PELO MAC!")
            is_valid = True
            dev_name = "SINK_DEVICE" 
            
        # 2. Tem o serviço SIC?
        if not is_valid:
            for s in device.services():
                if s.uuid() == SIC_SERVICE_UUID:
                    is_valid = True
                    break
        
        # 3. Tem o nome certo?
        if not is_valid and ("SIC_" in dev_name or "SINK_" in dev_name):
            is_valid = True

        if is_valid:
            candidates.append({
                "device_obj": device,
                "name": dev_name if dev_name else "UNKNOWN_SIC_NODE",
                "address": dev_addr,
                "hops": 0 if (dev_addr == TARGET_SINK_MAC or "SINK" in dev_name) else 99,
                "rssi": device.rssi()
            })
    
    candidates.sort(key=lambda x: (x['hops'], -x['rssi']))
    return candidates