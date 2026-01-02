import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# Constantes DBus
BLUEZ_SERVICE_NAME = 'org.bluez'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

# UUID do Serviço SIC (para ser encontrado pelo Scanner)
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

class SICAdvertiser(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index, local_name):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = 'peripheral'
        self.local_name = local_name
        self.service_uuids = [SIC_SERVICE_UUID]
        self.manufacturer_data = dbus.Dictionary({}, signature='qv')
        self.solicit_uuids = None
        self.service_data = None
        self.include_tx_power = True
        
        # Inicializar objeto DBus
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = dbus.String(self.ad_type)
        properties['LocalName'] = dbus.String(self.local_name)
        properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        
        if self.solicit_uuids:
            properties['SolicitUUIDs'] = dbus.Array(self.solicit_uuids, signature='s')
        if self.manufacturer_data:
            properties['ManufacturerData'] = dbus.Dictionary(self.manufacturer_data, signature='qv')
        if self.service_data:
            properties['ServiceData'] = dbus.Dictionary(self.service_data, signature='sv')
        
        properties['Includes'] = dbus.Array(["tx-power"], signature='s')
        
        # IMPORTANTE: Retornar o dicionário plano para o BlueZ
        return properties

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        return self.get_properties()

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        print(f'[ADV] {self.path}: Released!')

    def register(self):
        """Regista este Anuncio no BlueZ"""
        print(f"[ADV] A registar anúncio para {self.local_name}...")
        adapter_props = self._find_adapter()
        if not adapter_props:
            print("[ADV] ❌ Erro: Nenhum adaptador Bluetooth encontrado.")
            return

        adapter_path = adapter_props.object_path
        ad_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
                                    LE_ADVERTISING_MANAGER_IFACE)

        try:
            ad_manager.RegisterAdvertisement(self.get_path(), {},
                                             reply_handler=self._register_callback,
                                             error_handler=self._register_error_callback)
        except Exception as e:
            print(f"[ADV] ❌ Falha no registo: {e}")

    def unregister(self):
        """(Opcional) Remove o registo"""
        pass 

    def _register_callback(self):
        print('[ADV] ✅ Anúncio registado com sucesso (Visível para outros nós).')

    def _register_error_callback(self, error):
        print(f'[ADV] ❌ Erro no registo: {error}')

    def _find_adapter(self):
        remote_om = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, '/'), DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        for o, props in objects.items():
            if LE_ADVERTISING_MANAGER_IFACE in props:
                return self.bus.get_object(BLUEZ_SERVICE_NAME, o)
        return None