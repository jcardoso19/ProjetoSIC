import asyncio
from bless import (
    BlessServer,
    BlessGATTCharacteristic,
    GATTCharacteristicProperties,
    GATTAttributePermissions
)

SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
SIC_CHAR_UUID    = "51FF12C6-1360-44E9-9577-081E200C0514" 

class NodeAdvertiser:
    def __init__(self, my_name):
        self.my_name = my_name
        self.server = None
        self.trigger = asyncio.Event()
        self.current_hops = -1 

    def set_hops(self, hops):
        """Atualiza os hops e reinicia o anuncio se necessário"""
        self.current_hops = hops
        print(f"[ADVERTISER] Hops atualizados para: {self.current_hops}")

    async def run(self):
        self.server = BlessServer(name=self.my_name, loop=asyncio.get_running_loop())
        
        print(f"[ADVERTISER] A iniciar Bluetooth como '{self.my_name}'...")
        
        await self.server.add_new_service(SIC_SERVICE_UUID)
        
        char_flags = (GATTCharacteristicProperties.read | GATTCharacteristicProperties.write | GATTCharacteristicProperties.notify)
        permissions = (GATTAttributePermissions.readable | GATTAttributePermissions.writeable)
        
        await self.server.add_new_characteristic(
            SIC_SERVICE_UUID, SIC_CHAR_UUID, char_flags, b"Status: Init", permissions
        )

        self.server.read_request_func = self.on_read
        self.server.write_request_func = self.on_write

        if await self.server.start():
            print(f"📡 [ADVERTISER] Visível como '{self.my_name}'")
        
        await self.trigger.wait()
        
        await self.server.stop()
        print("[ADVERTISER] Parado.")

    def on_write(self, characteristic, value, **kwargs):
        msg = value.decode('utf-8')
        print(f"📥 [DOWNLINK] Recebi: {msg}")

    def on_read(self, characteristic, **kwargs):
        return str(self.current_hops).encode('utf-8')

    def stop(self):
        self.trigger.set()