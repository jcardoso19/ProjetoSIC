import simplepyble
import time

SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
TARGET_NAMES = ["SIC-Node", "SINK_DEVICE", "SINK", "SIC"] # Nomes aceites

FORCE_MAC = None 

def scan_for_candidates(adapter, duration=4000):
    print(f"[SCAN] 📡 A procurar Sink/Nós (UUID ou Nome)...")

    try:
        adapter.scan_for(duration)
    except Exception as e:
        print(f"[WARN] Erro ao iniciar scan: {e}")
    
    results = adapter.scan_get_results()
    candidates = []
    
    print(f"   --- DISPOSITIVOS DETETADOS ---")
    
    for device in results:
        addr = device.address()
        rssi = device.rssi()
        name = device.identifier()  
        services = device.services()
        


        is_candidate = False

        if FORCE_MAC and addr.upper() == FORCE_MAC.upper():
            is_candidate = True
            print(f"      -> Match por MAC Fixo!")

        if not is_candidate:
            for svc in services:
                if str(svc).upper() == SIC_SERVICE_UUID.upper():
                    is_candidate = True
                    print(f"      -> Match por UUID de Serviço!")
                    break
        
        if not is_candidate and name:
            for target in TARGET_NAMES:
                if target.upper() in name.upper():
                    is_candidate = True
                    print(f"      -> Match por Nome do Dispositivo ('{name}')!")
                    break

        if is_candidate:
            print(f"   🎯 ALVO CONFIRMADO: {name} [{addr}]")
            candidates.append({
                "device_obj": device,
                "name": name if name else "Unknown SIC Node",
                "address": addr,
                "hops": 0, 
                "rssi": rssi
            })

    print(f"   ------------------------------")
    
    candidates.sort(key=lambda x: x['rssi'], reverse=True)

    if not candidates:
        print("   ❌ Nenhum dispositivo SIC encontrado.")
    
    return candidates