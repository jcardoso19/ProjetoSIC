import threading
import time

class HeartbeatManager:
    def __init__(self, callback_on_death, interval=5):
        self.callback_on_death = callback_on_death
        self.interval = interval
        self.tolerance = (interval * 0.2) + 2 
        self.running = False
        self.thread = None
        self.last_heartbeat_time = time.time()
        self.missed_count = 0
        self.MAX_MISSES = 3

    def start(self):
        if self.running: return
        self.running = True
        self.last_heartbeat_time = time.time()
        self.missed_count = 0
        self.thread = threading.Thread(target=self._monitor)
        self.thread.daemon = True
        self.thread.start()
        # print(f"[HEARTBEAT] Monitorização iniciada.")

    def stop(self):
        self.running = False

    def heartbeat_received(self):
        """Chamado pelo Router quando chega um HB válido"""
        self.last_heartbeat_time = time.time()
        
        # Se recuperou de uma falha, avisa. Se for normal, fica calado.
        if self.missed_count > 0:
            print(f"💓 [HEARTBEAT] Recuperado! (Contador zerado)")
        # else:
            # print(f"💓 [HEARTBEAT] Recebido. Timer resetado.") # <--- SILENCIADO
            
        self.missed_count = 0

    def _monitor(self):
        while self.running:
            time.sleep(1)
            
            time_since_last = time.time() - self.last_heartbeat_time
            expected_misses = 0
            
            if time_since_last > (self.interval * 3) + self.tolerance:
                expected_misses = 3
            elif time_since_last > (self.interval * 2) + self.tolerance:
                expected_misses = 2
            elif time_since_last > self.interval + self.tolerance:
                expected_misses = 1
            
            if expected_misses > self.missed_count:
                self.missed_count = expected_misses
                print(f"⚠️ [HEARTBEAT] Falhou! ({self.missed_count}/{self.MAX_MISSES}) - {time_since_last:.1f}s sem sinal")
                
                if self.missed_count >= self.MAX_MISSES:
                    print("💀 [HEARTBEAT] UPLINK MORTO! A iniciar desconexão de emergência...")
                    if self.callback_on_death:
                        self.callback_on_death()
                    self.stop()
                    break