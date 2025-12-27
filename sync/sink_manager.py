import time

class SinkManager:
    def __init__(self, connection_manager):
        self.manager = connection_manager
        print("[LOGIC] Gestor de Dados do Sink iniciado.")

    def process_packet(self, data_bytes, source_connection=None):
        """
        Esta função é chamada automaticamente quando recebemos dados de um Nó via Bluetooth.
        """
        try:
            # Tenta descodificar a mensagem (assumindo que é texto)
            message = data_bytes.decode('utf-8')
            
            # Obtém informações de quem enviou (se disponível)
            sender_info = "Desconhecido"
            rssi = "N/A"
            
            if source_connection:
                # Tenta obter o endereço ou nome do dispositivo conectado
                try:
                    sender_info = source_connection.address()
                    rssi = source_connection.rssi()
                except:
                    pass

            print(f"\n📨 [DADOS RECEBIDOS] De: {sender_info} (RSSI: {rssi})")
            print(f"   Conteúdo: {message}")
            print("-" * 40)

        except Exception as e:
            print(f"[ERRO] Falha ao processar pacote: {e}")