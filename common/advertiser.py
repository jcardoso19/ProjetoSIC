import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

# Constantes DBus
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

    def __init__(self, bus, index, advertising_type, local_name, hops):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.local_name = local_name
        self.service_uuids = [SIC_SERVICE_UUID]
        self.manufacturer_data = dbus.Dictionary({}, signature='qv')
        
        # Dados do Fabricante com Hops (Key=0xFFFF)
        # Nota: Usamos dbus.UInt16 para a chave ser explicita
        self.manufacturer_data[0xFFFF] = dbus.Array([0xFF, 0xFF, hops], signature='y')
        
        self.include_tx_power = True

        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        
        # --- CORREÇÃO DE TIPOS EXPLICITOS ---
        properties['Type'] = dbus.String(self.ad_type)
        
        if self.local_name:
            properties['LocalName'] = dbus.String(self.local_name)
        
        if self.service_uuids:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
            
        if self.manufacturer_data:
            properties['ManufacturerData'] = dbus.Dictionary(self.manufacturer_data, signature='qv')
            
        properties['Discoverable'] = dbus.Boolean(True)
        properties['Includes'] = dbus.Array(["tx-power"], signature='s')
        
        # --- A GRANDE CORREÇÃO AQUI ---
        # Antes retornavamos: {LE_ADVERTISEMENT_IFACE: properties}
        # Agora retornamos apenas: properties
        return properties

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        # O GetAll ja espera o dicionario plano que corrigimos acima
        return self.get_properties()

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature='', out_signature='')
    def Release(self):
        print(f'[ADV] {self.path}: Released!')

class NodeAdvertiser:
    def __init__(self, advertiser_name, hops=99):
        self.name = advertiser_name
        self.hops = hops
        self.bus = None
        self.ad = None
        self.ad_manager = None
        self.is_running = False

    async def run(self):
        print(f"[ADVERTISER] A configurar GATT Server... (Hops: {self.hops})")
        
        # Configurar DBus Loop
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()

        adapter_props = self.find_adapter(self.bus)
        if not adapter_props:
            print("[ADVERTISER] Erro: Adaptador não encontrado.")
            return

        adapter_path = adapter_props.object_path
        self.ad_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
                                         LE_ADVERTISING_MANAGER_IFACE)

        self.ad = TestAdvertisement(self.bus, 0, 'peripheral', self.name, self.hops)

        print(f"[ADVERTISER] A anunciar: {self.name} | Hops: {self.hops}")
        
        try:
            self.ad_manager.RegisterAdvertisement(self.ad.get_path(), {},
                                                  reply_handler=self.register_ad_callback,
                                                  error_handler=self.register_ad_error_callback)
            self.is_running = True
            
            # Loop GLib para manter o anuncio vivo
            loop = GLib.MainLoop()
            loop.run()
            
        except Exception as e:
            print(f"[ADVERTISER] Falha ao registar: {e}")

    def stop(self):
        self.is_running = False

    def register_ad_callback(self):
        pass 

    def register_ad_error_callback(self, uuid):
        print(f'[ADVERTISER] Erro ao registar: {uuid}')

    def find_adapter(self, bus):
        remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'), DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        for o, props in objects.items():
            if LE_ADVERTISING_MANAGER_IFACE in props:
                return bus.get_object(BLUEZ_SERVICE_NAME, o)
        return None