import dbus
import dbus.service
import dbus.mainloop.glib

# --- CONFIGURAÇÃO UUIDs ---
# Tem de bater certo com o que o Nó procura
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
# Uma Característica para escrita (RX) - Incrementamos 1 no final
SIC_RX_CHAR_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CE"

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(dbus_interface='org.freedesktop.DBus.ObjectManager',
                         out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
        return response

class Service(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            'org.bluez.GattService1': {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    [c.get_path() for c in self.characteristics],
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristics(self):
        return self.characteristics

class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = []
        self.notifying = False
        self.callback = None
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):   
        return {
            'org.bluez.GattCharacteristic1': {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Value': dbus.Array(self.value, signature='y')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)
    
    def set_callback(self,cb):
        self.callback = cb

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='aya{sv}')
    def WriteValue(self, value, options):
        # AQUI É ONDE RECEBEMOS OS DADOS DO NÓ!
        data_str = "".join([chr(b) for b in value])
        data_bytes = bytes(value)
        
        device_path = options.get('device', None)
        device_mac = "UNKNOWN"
        if device_path:
            # device_path ex: /org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF
            try:
                device_mac = str(device_path).split("dev_")[-1].replace('_', ':')
            except:
                pass

        if self.callback:
            self.callback(data_bytes, device_mac)
        else:
            print(f"\n📨 [GATT SERVER] Recebi dados de {device_mac}: {len(value)} bytes")
        # Vamos tentar imprimir o texto
        try:
            print(f"   Conteúdo: {data_str}")
        except:
            print(f"   (Binário): {list(value)}")
            
            
        return

    @dbus.service.method('org.bluez.GattCharacteristic1', out_signature='ay')
    def ReadValue(self, options):
        return self.value
    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='', out_signature='')
    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        print("[GATT] Notificações ativadas pelo cliente")
    def StopNotify(self):
        if not self.notifying:
            return
        self.notifying = False
        print("[GATT] Notificações desativadas")
    def SendNotification(self,data_bytes):
        if not self.notifying:
            return
        value = dbus.Array([b for b in data_bytes], signature='y')
        self.value = value
        self.PropertiesChanged('org.bluez.GattCharacteristic1', {'Value': value}, [])
        
    @dbus.service.signal('org.freedesktop.DBus.Properties', signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):                           #envia um sinal que acorda o DBUS
        pass

# Classe Principal para Iniciar o Serviço
class GATTServerManager:
    def __init__(self, bus):
        self.bus = bus
        self.app = Application(bus)
        
        # 1. Criar o Serviço SIC
        self.sic_service = Service(bus, 0, SIC_SERVICE_UUID, True)
        
        # 2. Criar a Característica RX (Write)
        # Flags: 'write' e 'write-without-response' para ser rápido
        self.rx_char = Characteristic(bus, 0, SIC_RX_CHAR_UUID, 
                                      ['read', 'write', 'write-without-response','notify'], 
                                      self.sic_service)
        
        self.sic_service.add_characteristic(self.rx_char)
        self.app.add_service(self.sic_service)
        
        self.service_manager = dbus.Interface(
            bus.get_object('org.bluez', '/org/bluez/hci0'), # Força hci1
            'org.bluez.GattManager1'
        )
    def set_data_callback(self,callback):
        self.rx_char.set_callback(callback)
    
    def send_data(self,data_bytes):
        self.rx_char.SendNotification(data_bytes)

    def register(self):
        print("[GATT] A registar Serviço SIC no BlueZ...")
        self.service_manager.RegisterApplication(
            self.app.get_path(), {},
            reply_handler=self.register_callback,
            error_handler=self.register_error_callback
        )

    def register_callback(self):
        print("[GATT] ✅ Serviço SIC Registado com sucesso!")

    def register_error_callback(self, error):
        print(f"[GATT] ❌ Erro ao registar: {error}")