import simplepyble
import time

REF_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"

def scan_for_candidates(adapter, duration=3000):
    print(f"[SCAN] A procurar dispositivos com Serviço: {REF_SERVICE_UUID}...")
    
    try:
        adapter.scan_for(duration)
    except Exception as e:
        print(f"[WARN] Erro no scan BLE: {e}")
        return []

    results = adapter.scan_get_results()
    candidates = []
    
    for device in results:
        try:
            uuids_no_ar = device.services()
            
            uuids_normalizados = [u.lower() for u in uuids_no_ar]
            
            if REF_SERVICE_UUID.lower() in uuids_normalizados:
                print(f"   ✅ ALVO VÁLIDO ENCONTRADO: {device.identifier()} [{device.address()}] | RSSI: {device.rssi()}")
                
                candidates.append({
                    "device_obj": device,
                    "name": device.identifier(),
                    "address": device.address(),
                    "hops": 0,
                    "rssi": device.rssi()
                })
        except:
            continue
            
    if not candidates:
        print("   ❌ Nenhum dispositivo compatível encontrado.")
        
    return candidates