import time
import threading

class HeartbeatManager:
    def __init__(self, connection_manager, timeout_seconds=5, max_missed=3):
        self.connection_manager = connection_manager
        self.interval = timeout_seconds
        self.max_missed = max_missed
        self.missed_count = 0
        self.running = False
        self.timer_thread = None

    def start(self):
        """Inicia a monitorização"""
        print("[HEARTBEAT] Monitorização iniciada.")
        self.running = True
        self.missed_count = 0
        self._schedule_check()

    def stop(self):
        self.running = False
        if self.timer_thread:
            self.timer_thread.cancel()

    def _schedule_check(self):
        if not self.running:
            return
        self.timer_thread = threading.Timer(self.interval, self._check_pulse)
        self.timer_thread.start()

    def _check_pulse(self):
        """Chamado automaticamente quando o tempo acaba"""
        if not self.running:
            return

        self.missed_count += 1
        print(f"⚠️ [HEARTBEAT] Falhou! ({self.missed_count}/{self.max_missed})")

        if self.missed_count >= self.max_missed:
            print("💀 [HEARTBEAT] UPLINK MORTO! A iniciar desconexão de emergência...")
            self.connection_manager.on_uplink_lost()
            self.stop()
        else:

            self._schedule_check()

    def beat_received(self):
        """Esta função deve ser chamada quando o Router recebe uma msg do tipo HEARTBEAT"""
        if self.running:
            print("💓 [HEARTBEAT] Recebido. Timer resetado.")
            self.missed_count = 0