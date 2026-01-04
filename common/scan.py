import simplepyble
import time

# --- CONFIGURAÇÕES ---
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
TARGET_NAMES = ["SIC-Node", "SINK_DEVICE", "SINK", "SIC"] # Nomes aceites

# Se quiseres forçar um MAC em último caso, mete aqui (ex: "E0:D3..."). Se não, deixa None.
FORCE_MAC = None 

def scan_for_candidates(adapter, duration=4000):
    print(f"[SCAN] 📡 A procurar Sink/Nós (UUID ou Nome)...")

    try:
        adapter.scan_for(duration)
    except Exception as e:
        print(f"[WARN] Erro ao iniciar scan: {e}")
        # Tenta continuar mesmo com erro, às vezes é só um aviso de busy
    
    results = adapter.scan_get_results()
    candidates = []
    
    print(f"   --- DISPOSITIVOS DETETADOS ---")
    
    for device in results:
        addr = device.address()
        rssi = device.rssi()
        name = device.identifier()  # Nome anunciado pelo Bluetooth
        services = device.services()
        
        # Log para saberes o que o teu PC está a ver (DEBUG)
        # print(f"   [?] '{name}' ({addr}) | RSSI: {rssi} | Svcs: {len(services)}")

        is_candidate = False

        # CRITÉRIO 1: MAC Fixo (Batota de emergência)
        if FORCE_MAC and addr.upper() == FORCE_MAC.upper():
            is_candidate = True
            print(f"      -> Match por MAC Fixo!")

        # CRITÉRIO 2: UUID do Serviço (O método ideal)
        if not is_candidate:
            for svc in services:
                if str(svc).upper() == SIC_SERVICE_UUID.upper():
                    is_candidate = True
                    print(f"      -> Match por UUID de Serviço!")
                    break
        
        # CRITÉRIO 3: Nome do Dispositivo (O método robusto para Linux)
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
                "hops": 0, # Assumimos 0 para já, depois o handshake resolve
                "rssi": rssi
            })

    print(f"   ------------------------------")
    
    # Ordena pelo sinal mais forte (RSSI mais próximo de 0)
    candidates.sort(key=lambda x: x['rssi'], reverse=True)

    if not candidates:
        print("   ❌ Nenhum dispositivo SIC encontrado.")
    
    return candidates