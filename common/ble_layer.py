import simplepyble
import struct

PROJECT_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"

class BLELayer:
    def __init__(self):
        adapters = simplepyble.Adapter.get_adapters()
        if not adapters:
            raise Exception("No Bluetooth adapter found")
        self.adapter = adapters[0] 
        
    def scan_for_potential_uplinks(self, duration=5000):
        """
        Retorna lista de dicionários: {'mac': str, 'hops': int, 'device': obj}
        """
        self.adapter.scan_for(duration)
        results = self.adapter.scan_get_results()
        
        potential_uplinks = []
        
        for device in results:
            
            services = device.services()


            m_data = device.manufacturer_data()

            hops = 99
            if m_data:

                 pass

            if "SIC_NODE" in device.identifier():
                potential_uplinks.append({
                    "device": device,
                    "mac": device.address(),
                    "hops": hops,
                    "rssi": device.rssi()
                })
                
        return potential_uplinks

    def connect_to(self, target_device):
        print(f"Connecting to {target_device.address()}...")
        try:
            target_device.connect()
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False