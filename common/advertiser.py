import asyncio
from bless import (
    BlessServer,
    BlessGATTCharacteristic,
    GATTCharacteristicProperties,
    GATTAttributePermissions
)

SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
SIC_CHAR_UUID    = "51FF12C6-1360-44E9-9577-081E200C0514" 

MANUFACTURER_ID = 0xFFFF

class NodeAdvertiser:
    def __init__(self, my_name):
        self.my_name = my_name
        self.server = None
        self.trigger = asyncio.Event()
        self.current_hops = 99 
        self.data_callback = None 

    def set_data_callback(self, callback_func):
        """Define quem processa os dados recebidos (geralmente o ConnectionManager)"""
        self.data_callback = callback_func

    async def update_hops(self, hops):
        """
        Atualiza o número de hops e reinicia o advertising 
        para que os vizinhos vejam a mudança imediatamente.
        """
        if self.current_hops == hops:
            return 

        self.current_hops = hops
        print(f"[ADVERTISER] A atualizar Hops para: {self.current_hops}")
        
        if self.server and self.server.is_advertising:
            await self.server.stop_advertising()
            await self.start_advertising_process()

    async def start_advertising_process(self):
        """Lógica interna para iniciar o anúncio com os dados corretos"""
        hops_bytes = int(self.current_hops).to_bytes(1, byteorder='big')
        
        m_data = {
            MANUFACTURER_ID: hops_bytes
        }

        if await self.server.start_advertising(self.server.services, manufacturer_data=m_data):
            print(f"[ADVERTISER] A anunciar: {self.my_name} | Hops: {self.current_hops}")
        else:
            print(f"[ADVERTISER] Falha ao iniciar advertising.")

    async def run(self):
        self.server = BlessServer(name=self.my_name, loop=asyncio.get_running_loop())
        
        print(f"[ADVERTISER] A configurar GATT Server...")
        
        await self.server.add_new_service(SIC_SERVICE_UUID)
        
        char_flags = (
            GATTCharacteristicProperties.read | 
            GATTCharacteristicProperties.write | 
            GATTCharacteristicProperties.notify
        )
        permissions = (
            GATTAttributePermissions.readable | 
            GATTAttributePermissions.writeable
        )
        
        await self.server.add_new_characteristic(
            SIC_SERVICE_UUID, 
            SIC_CHAR_UUID, 
            char_flags, 
            b"SIC_NODE_READY", 
            permissions
        )

        self.server.read_request_func = self.on_read
        self.server.write_request_func = self.on_write

        await self.server.start()
        
        await self.start_advertising_process()
        
        await self.trigger.wait()
        
        await self.server.stop()
        print("[ADVERTISER] Servidor desligado.")

    def on_write(self, characteristic, value, **kwargs):
        """
        Chamado quando um vizinho (Downlink) nos envia dados.
        """
        
        if self.data_callback:
            self.data_callback(value)
        else:
            print("[ADVERTISER] Aviso: Recebi dados mas não tenho callback configurado!")

    def on_read(self, characteristic, **kwargs):
        """Se alguém tentar ler a característica diretamente"""
        return str(self.current_hops).encode('utf-8')

    def stop(self):
        self.trigger.set()