import dbus
import dbus.service
import dbus.mainloop.glib

# --- CONFIGURAÇÃO UUIDs ---
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
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

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
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
            GATT_SERVICE_IFACE: {
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
    
    # --- CORREÇÃO: Método register adicionado aqui ---
    def register(self, app_path):
        """Regista a Aplicação inteira no BlueZ GattManager"""
        print(f"[GATT] A registar Aplicação no BlueZ: {app_path}")
        
        # 1. Encontrar o adaptador Bluetooth que tem GattManager1
        remote_om = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, '/'), DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        adapter_path = None
        
        for o, props in objects.items():
            if GATT_MANAGER_IFACE in props:
                adapter_path = o
                break
        
        if not adapter_path:
            print("[GATT] ❌ Erro: Nenhum adaptador Bluetooth com GattManager encontrado.")
            return

        # 2. Obter a interface GattManager1
        gatt_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
                                      GATT_MANAGER_IFACE)

        # 3. Registar a Aplicação
        try:
            gatt_manager.RegisterApplication(app_path, {},
                                             reply_handler=self._register_app_callback,
                                             error_handler=self._register_app_error_callback)
        except Exception as e:
            print(f"[GATT] ❌ Falha ao chamar RegisterApplication: {e}")

    def _register_app_callback(self):
        print("[GATT] ✅ Aplicação GATT registada com sucesso (Serviço Visível).")

    def _register_app_error_callback(self, error):
        print(f"[GATT] ❌ Erro no registo da Aplicação GATT: {error}")


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)
    
    def set_callback(self,cb):
        self.callback = cb

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='aya{sv}')
    def WriteValue(self, value, options):
        data_str = "".join([chr(b) for b in value])
        data_bytes = bytes(value)
        
        device_mac = "UNKNOWN"
        device_path = options.get('device', None)
        if device_path:
            try:
                device_mac = str(device_path).split("dev_")[-1].replace('_', ':')
            except:
                pass

        if self.callback:
            self.callback(data_bytes, device_mac)
        else:
            print(f"\n📨 [GATT SERVER] Recebi dados de {device_mac}: {len(value)} bytes")
        return

    @dbus.service.method('org.bluez.GattCharacteristic1', out_signature='ay')
    def ReadValue(self, options):
        return self.value

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='', out_signature='')
    def StartNotify(self):
        if self.notifying: return
        self.notifying = True
        print("[GATT] Notificações ativadas pelo cliente")

    def StopNotify(self):
        if not self.notifying: return
        self.notifying = False
        print("[GATT] Notificações desativadas")

    def SendNotification(self,data_bytes):
        if not self.notifying: return
        value = dbus.Array([b for b in data_bytes], signature='y')
        self.value = value
        self.PropertiesChanged('org.bluez.GattCharacteristic1', {'Value': value}, [])
        
    @dbus.service.signal('org.freedesktop.DBus.Properties', signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

# --- CLASSE CORRIGIDA ---
class GATTServerManager:
    # Agora aceita adapter_index
    def __init__(self, bus, adapter_index=0):
        self.bus = bus
        self.app = Application(bus)
        
        # 1. Criar o Serviço SIC
        self.sic_service = Service(bus, 0, SIC_SERVICE_UUID, True)
        
        # 2. Criar a Característica RX
        self.rx_char = Characteristic(bus, 0, SIC_RX_CHAR_UUID, 
                                      ['read', 'write', 'write-without-response','notify'], 
                                      self.sic_service)
        
        self.sic_service.add_characteristic(self.rx_char)
        self.app.add_service(self.sic_service)
        
        # A MUDANÇA ESTÁ AQUI: Usa o índice correto (hci0 ou hci1)
        adapter_path = f'/org/bluez/hci{adapter_index}'
        
        try:
            self.service_manager = dbus.Interface(
                bus.get_object('org.bluez', adapter_path),
                'org.bluez.GattManager1'
            )
        except Exception as e:
            print(f"[GATT] ERRO CRÍTICO: Não consegui aceder ao adaptador {adapter_path}: {e}")

    def set_data_callback(self,callback):
        self.rx_char.set_callback(callback)
    
    def send_data(self,data_bytes):
        self.rx_char.SendNotification(data_bytes)

    def register(self):
        print("[GATT] A registar Serviço SIC no BlueZ...")
        try:
            self.service_manager.RegisterApplication(
                self.app.get_path(), {},
                reply_handler=self.register_callback,
                error_handler=self.register_error_callback
            )
        except Exception as e:
            print(f"[GATT] Falha no registo: {e}")

    def register_callback(self):
        print("[GATT] ✅ Serviço SIC Registado com sucesso!")

    def register_error_callback(self, error):
        print(f"[GATT] ❌ Erro ao registar: {error}")