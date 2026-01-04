import simplepyble
import struct
import time

SIC_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
SIC_CHAR_UUID    = "12345678-1234-5678-1234-56789abcdef1" 

MANUFACTURER_ID = 0xFFFF

class BLELayer:
    def __init__(self):
        adapters = simplepyble.Adapter.get_adapters()
        if not adapters:
            raise Exception("No Bluetooth adapter found")
        self.adapter = adapters[0] 
        print(f"[BLE] A usar adaptador: {self.adapter.identifier()}")

    def scan_for_potential_uplinks(self, duration=3000):

        print("[BLE] A fazer scan...")
        self.adapter.scan_for(duration)
        results = self.adapter.scan_get_results()
        
        candidates = []
        
        for device in results:
            if "SIC_" not in device.identifier():
                continue

            m_data = device.manufacturer_data()
            hops = 99 
            if MANUFACTURER_ID in m_data:
                try:
                    raw_bytes = m_data[MANUFACTURER_ID]
                    hops = int.from_bytes(raw_bytes, 'big')
                except:
                    pass
            
            candidates.append({
                "device": device,
                "name": device.identifier(),
                "mac": device.address(),
                "hops": hops,
                "rssi": device.rssi()
            })
        
        candidates.sort(key=lambda x: (x['hops'], -x['rssi']))
        
        return candidates

    def connect_to(self, target_device):
        print(f"[BLE] A conectar a {target_device.identifier()} [{target_device.address()}]...")
        try:
            target_device.connect()
            return True
        except Exception as e:
            print(f"[BLE] Falha ao conectar: {e}")
            return False

    def send_packet(self, device, packet_bytes):
        try:
            device.write_request(SIC_SERVICE_UUID, SIC_CHAR_UUID, packet_bytes)
            return True
        except Exception as e:
            print(f"[BLE] Erro de envio: {e}")
            return False

    def subscribe_notifications(self, device, callback_func):
        try:
            device.notify(SIC_SERVICE_UUID, SIC_CHAR_UUID, callback_func)
            print("[BLE] Notificações ativas.")
        except Exception as e:
            print(f"[BLE] Erro ao subscrever: {e}")