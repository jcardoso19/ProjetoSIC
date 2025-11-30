import simplepyble
import time

from common.scan import scan_for_candidates

from common.scan import scan_for_candidates
class ConnectionManager:
    def __init__(self):
        self.adapter = self._get_adapter()
        self.uplink = None 
        self.uplink_info = {}

    def _get_adapter(self):
        """Seleciona automaticamente o primeiro adaptador Bluetooth disponível."""
        adapters = simplepyble.Adapter.get_adapters()
        if not adapters:
            raise Exception("ERRO CRÍTICO: Nenhum adaptador Bluetooth encontrado.")
        
        adapter = adapters[0]
        print(f"[INIT] A usar adaptador: {adapter.identifier()} [{adapter.address()}]")
        return adapter

    def find_and_connect_uplink(self):
        """
        Tenta encontrar o melhor pai e conectar-se.
        Retorna True se conectado, False se falhou.
        """
        if self.uplink and self.uplink_is_alive():
            print("[MANAGER] Já temos Uplink. Regra Lazy: manter atual.")
            return True

        print("[MANAGER] A procurar novo Uplink...")
        candidates = scan_for_candidates(self.adapter)

        if not candidates:
            print("[MANAGER] Nenhum nó vizinho encontrado.")
            return False

        for candidate in candidates:
            target_device = candidate['device_obj']
            print(f"[CONNECT] A tentar conectar a {candidate['name']} (Hops: {candidate['hops']})...")
            
            try:
                target_device.connect()
                
                self.uplink = target_device
                self.uplink_info = candidate
                print(f"[SUCCESS] Conectado a {candidate['name']}! (Meu novo uplink)")
                
                target_device.set_callback_on_disconnected(self.on_uplink_lost)
                
                return True
                
            except Exception as e:
                print(f"[FAIL] Falha ao conectar a {candidate['name']}: {e}")
                continue
        
        print("[MANAGER] Falha: Não foi possível conectar a nenhum candidato.")
        return False

    def uplink_is_alive(self):
        if self.uplink:
            try:
                return True 
            except:
                return False
        return False

    def on_uplink_lost(self):
        print("\n[ALERT] UPLINK PERDIDO! A iniciar procedimentos de recuperação...")
        self.uplink = None
        self.uplink_info = {}

    def disconnect_all(self):
        if self.uplink:
            print("[SHUTDOWN] A desconectar do Uplink...")
            try:
                self.uplink.disconnect()
            except:
                pass