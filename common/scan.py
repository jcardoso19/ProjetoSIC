import simplepyble
import time

SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
TARGET_NAMES = ["SIC-Node", "SINK_DEVICE", "SINK", "SIC"] # Nomes aceites

MANUFACTURER_ID = 0xFFFF
MFG_SIGNATURE = (0xFF, 0xFF)  # prefixo usado no advertiser

FORCE_MAC = None 

def scan_for_candidates(adapter, duration=4000):
    try:
        print(f"[SCAN] 📡 A procurar Sink/Nós (UUID/Nome/MFG)... (Adapter: {adapter.identifier()})")
    except Exception:
        print(f"[SCAN] 📡 A procurar Sink/Nós (UUID/Nome/MFG)...")

    try:
        adapter.scan_for(duration)
    except Exception as e:
        print(f"[WARN] Erro ao iniciar scan: {e}")
    
    results = adapter.scan_get_results()
    candidates = []

    if not results:
        print("   ⚠️  Scan não detetou nenhum dispositivo BLE.")
        print("      Dica: confirma se escolheste o adaptador correto (hci0/hci1), se está Powered/UP, e se o Sink está a anunciar.")
    
    print(f"   --- DISPOSITIVOS DETETADOS ---")
    
    for device in results:
        addr = device.address()
        rssi = device.rssi()
        name = device.identifier()  
        services = device.services()

        hops = 0
        # Alguns stacks não expõem serviços/nome no scan, mas expõem manufacturer data.
        try:
            mfg = device.manufacturer_data()
        except Exception:
            mfg = {}
        


        is_candidate = False

        if FORCE_MAC and addr.upper() == FORCE_MAC.upper():
            is_candidate = True
            print(f"      -> Match por MAC Fixo!")

        if not is_candidate:
            # Match robusto: assinatura no ManufacturerData
            try:
                if MANUFACTURER_ID in mfg:
                    raw = mfg[MANUFACTURER_ID]
                    raw_list = list(raw) if raw is not None else []
                    if len(raw_list) >= 3 and tuple(raw_list[:2]) == MFG_SIGNATURE:
                        hops = int(raw_list[2])
                        is_candidate = True
                        print(f"      -> Match por ManufacturerData (Hops: {hops})!")
            except Exception:
                pass

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
                "hops": hops, 
                "rssi": rssi
            })

    print(f"   ------------------------------")

    # Preferência: menor número de hops, e em empate maior RSSI
    candidates.sort(key=lambda x: (x.get('hops', 99), -x.get('rssi', -999)))

    if not candidates:
        print("   ❌ Nenhum dispositivo SIC encontrado.")
    
    return candidates