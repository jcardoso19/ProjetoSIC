import dbus
import dbus.service
import dbus.mainloop.glib

SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
SIC_RX_CHAR_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CE"

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)
    def get_path(self): return dbus.ObjectPath(self.path)
    def add_service(self, service): self.services.append(service)
    @dbus.service.method(dbus_interface='org.freedesktop.DBus.ObjectManager', out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for chrc in service.get_characteristics():
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
        return {'org.bluez.GattService1': {'UUID': self.uuid, 'Primary': self.primary, 'Characteristics': dbus.Array([c.get_path() for c in self.characteristics], signature='o')}}
    def get_path(self): return dbus.ObjectPath(self.path)
    def add_characteristic(self, characteristic): self.characteristics.append(characteristic)
    def get_characteristics(self): return self.characteristics

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
    def get_properties(self): return {'org.bluez.GattCharacteristic1': {'Service': self.service.get_path(), 'UUID': self.uuid, 'Flags': self.flags, 'Value': dbus.Array(self.value, signature='y')}}
    def get_path(self): return dbus.ObjectPath(self.path)
    def set_callback(self,cb): self.callback = cb

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='aya{sv}')
    def WriteValue(self, value, options):
        data_bytes = bytes(value)
        device_mac = "UNKNOWN"
        if 'device' in options:
            try: device_mac = str(options['device']).split("dev_")[-1].replace('_', ':')
            except: pass
        if self.callback:
            try: self.callback(data_bytes, device_mac)
            except TypeError: self.callback(data_bytes)

    @dbus.service.method('org.bluez.GattCharacteristic1', out_signature='ay')
    def ReadValue(self, options): return self.value

    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='', out_signature='')
    def StartNotify(self): self.notifying = True
    
    @dbus.service.method('org.bluez.GattCharacteristic1', in_signature='', out_signature='')
    def StopNotify(self): self.notifying = False

    def SendNotification(self, data_bytes):
        # Enviar SEMPRE, ignorar flag notifying para não bloquear handshake
        value = dbus.Array([b for b in data_bytes], signature='y')
        self.value = value
        self.PropertiesChanged('org.bluez.GattCharacteristic1', {'Value': value}, [])
        
    @dbus.service.signal('org.freedesktop.DBus.Properties', signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated): pass

class GATTServerManager:
    def __init__(self, bus, adapter_index=0):
        self.bus = bus
        self.app = Application(bus)
        self.sic_service = Service(bus, 0, SIC_SERVICE_UUID, True)
        self.rx_char = Characteristic(bus, 0, SIC_RX_CHAR_UUID, ['read', 'write', 'write-without-response','notify'], self.sic_service)
        self.sic_service.add_characteristic(self.rx_char)
        self.app.add_service(self.sic_service)
        try: self.service_manager = dbus.Interface(bus.get_object('org.bluez', f'/org/bluez/hci{adapter_index}'), 'org.bluez.GattManager1')
        except: pass
        self._data_callback = None
        self._disconnect_callback = None

    def set_data_callback(self,callback):
        self._data_callback = callback
        self.rx_char.set_callback(self._on_rx_data)

    def _on_rx_data(self, data_bytes, device_mac="UNKNOWN"):
        if self._data_callback:
            try: self._data_callback(data_bytes, device_mac)
            except: self._data_callback(data_bytes)

    def set_disconnect_callback(self, cb): self._disconnect_callback = cb
    def send_data(self, data_bytes): self.rx_char.SendNotification(data_bytes)
    def register(self):
        try: self.service_manager.RegisterApplication(self.app.get_path(), {}, reply_handler=lambda:print("[GATT] OK"), error_handler=lambda e:print(f"[GATT] Erro: {e}"))
        except: pass