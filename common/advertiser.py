import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib
import threading

BLUEZ_SERVICE_NAME = 'org.bluez'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

class TestAdvertisement(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index, advertising_type, local_name, hops, release_callback=None):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.local_name = local_name
        self.service_uuids = [SIC_SERVICE_UUID]
        self.manufacturer_data = dbus.Dictionary({}, signature='qv')
        self.manufacturer_data[0xFFFF] = dbus.Array([0xFF, 0xFF, hops], signature='y')
        self.include_tx_power = True
        self.release_callback = release_callback
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = dbus.String(self.ad_type)
        if self.local_name:
            properties['LocalName'] = dbus.String(self.local_name)
        if self.service_uuids:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        if self.manufacturer_data:
            properties['ManufacturerData'] = dbus.Dictionary(self.manufacturer_data, signature='qv')
        properties['Discoverable'] = dbus.Boolean(True)
        properties['Includes'] = dbus.Array(["tx-power"], signature='s')
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
        print(f'[ADV] {self.path}: Advertising Released (Stop).')
        if self.release_callback:
            self.release_callback()

class NodeAdvertiser:
    def __init__(self, advertiser_name, hops=99, adapter_index=0):
        self.name = advertiser_name
        self.hops = hops
        self.adapter_index = adapter_index
        self.bus = None
        self.ad = None
        self.ad_manager = None
        self.is_running = False

    async def run(self):
        target_adapter = f"hci{self.adapter_index}"
        print(f"[ADVERTISER] A configurar GATT Server em {target_adapter}... (Hops: {self.hops})")
        
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()

        adapter_props = self.find_adapter(self.bus, target_adapter)
        if not adapter_props:
            print(f"[ADVERTISER] ERRO CRÍTICO: Não encontrei o adaptador {target_adapter}!")
            return

        adapter_path = adapter_props.object_path

        self.ad_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
                                         LE_ADVERTISING_MANAGER_IFACE)

        self.ad = TestAdvertisement(self.bus, 0, 'peripheral', self.name, self.hops, release_callback=self._handle_release)

        self._register()

    def _register(self):
        try:
            self.ad_manager.RegisterAdvertisement(self.ad.get_path(), {},
                                                  reply_handler=self.register_ad_callback,
                                                  error_handler=self.register_ad_error_callback)
            self.is_running = True
        except Exception as e:
            print(f"[ADVERTISER] Falha ao registar: {e}")

    def _handle_release(self):
        if not self.is_running:
            return
        print("[ADV] Advertisement interrompido pelo sistema (conexão). A reiniciar em 2s...")
        threading.Timer(2.0, self._restart_after_release).start()

    def _restart_after_release(self):
        if not self.is_running:
            return
        try:
            self.ad_manager.RegisterAdvertisement(self.ad.get_path(), {},
                                                  reply_handler=self.register_ad_callback,
                                                  error_handler=self.register_ad_error_callback)
        except Exception as e:
            print(f"[ADV] Falha ao reiniciar (busy?): {e}. Nova tentativa em 3s.")
            threading.Timer(3.0, self._restart_after_release).start()

    def stop(self):
        self.is_running = False
        try:
            if self.ad_manager and self.ad:
                self.ad_manager.UnregisterAdvertisement(self.ad.get_path())
        except Exception:
            pass

    def register_ad_callback(self):
        print(f"[ADV] ✅ Anúncio registado com sucesso (hci{self.adapter_index})")

    def register_ad_error_callback(self, uuid):
        print(f'[ADVERTISER] Erro ao registar: {uuid}')

    def find_adapter(self, bus, target_name):
        remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'), DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        
        for o, props in objects.items():
            if LE_ADVERTISING_MANAGER_IFACE in props and f"/{target_name}" in o:
                return bus.get_object(BLUEZ_SERVICE_NAME, o)
        return None