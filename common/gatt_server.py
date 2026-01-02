import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import json
import sys
import os
import threading
import array

# Criptografia
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from common.protocol import Packet, MSG_TYPE_HELLO, MSG_TYPE_KEY_EXCHANGE, MSG_TYPE_DATA, MSG_TYPE_HEARTBEAT

BLUEZ_SERVICE_NAME = 'org.bluez'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'

# UUIDs do Projeto
SIC_SERVICE_UUID = "A07498CA-AD5B-474E-940D-16F1FBE7E8CD"
SIC_CHAR_UUID    = "51FF12C6-1360-44E9-9577-081E200C0514"

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

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return self.value

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        pass

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        pass

# --- IMPLEMENTAÇÃO DO SIC ---

class SICCharacteristic(Characteristic):
    def __init__(self, bus, index, service, app_callback, cert_bytes=None, priv_key=None):
        Characteristic.__init__(self, bus, index, SIC_CHAR_UUID, ['read', 'write', 'notify'], service)
        self.app_callback = app_callback
        self.notifying = False
        
        # Credenciais
        self.cert_bytes = cert_bytes
        self.priv_key = priv_key
        
        # Gestão de Sessões
        self.sessions = {}
        
        self.root_ca = self._load_root_ca()

    def _load_root_ca(self):
        candidates = ["certs/root_ca.crt", "support/certs/root_ca.crt", "../certs/root_ca.crt"]
        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        return x509.load_pem_x509_certificate(f.read(), default_backend())
                except:
                    pass
        return None

    def _get_device_mac(self, device_path):
        return device_path.split('_')[-1].replace('_', ':')

    def WriteValue(self, value, options):
        try:
            data_bytes = bytes(value)
            packet = Packet.from_bytes(data_bytes)
            if not packet: return

            device_path = options.get('device')
            if not device_path: return
            
            if device_path not in self.sessions:
                self.sessions[device_path] = {'session_key': None}

            session = self.sessions[device_path]
            src_mac = self._get_device_mac(device_path)

            # --- HANDSHAKE ---
            if packet.msg_type == MSG_TYPE_HELLO:
                print(f"[SEC] 📩 Recebido HELLO de {src_mac}")
                try:
                    client_cert = x509.load_pem_x509_certificate(packet.payload.encode('utf-8'), default_backend())
                    if self.root_ca:
                        self.root_ca.public_key().verify(
                            client_cert.signature,
                            client_cert.tbs_certificate_bytes,
                            ec.ECDSA(hashes.SHA256())
                        )
                    
                    session['peer_pub_key'] = client_cert.public_key()
                    
                    if self.cert_bytes:
                        reply = Packet("SERVER", src_mac, self.cert_bytes.decode('utf-8'), msg_type=MSG_TYPE_HELLO)
                        self.send_notification(reply)
                    
                except Exception as e:
                    print(f"[SEC] ❌ Erro ao validar cliente: {e}")
                    del self.sessions[device_path]

            elif packet.msg_type == MSG_TYPE_KEY_EXCHANGE:
                print(f"[SEC] 📩 Recebido KEY_EXCHANGE de {src_mac}")
                if 'peer_pub_key' not in session: return

                try:
                    # Verificar assinatura do Handshake (Integridade)
                    session['peer_pub_key'].verify(
                        bytes.fromhex(packet.mac),
                        packet.get_bytes_for_signing(),
                        ec.ECDSA(hashes.SHA256())
                    )
                    
                    peer_ephemeral = serialization.load_pem_public_key(
                        packet.payload.encode('utf-8'), default_backend()
                    )
                    
                    my_ephemeral_priv = ec.generate_private_key(ec.SECP521R1(), default_backend())
                    shared_secret = my_ephemeral_priv.exchange(ec.ECDH(), peer_ephemeral)
                    
                    session_key = HKDF(
                        algorithm=hashes.SHA256(), length=32, salt=None, info=b'sic-protocol-v1', backend=default_backend()
                    ).derive(shared_secret)
                    
                    session['session_key'] = session_key
                    print(f"[SEC] 🔐 SESSÃO ENCRIPTADA ESTABELECIDA COM {src_mac}!")
                    
                    my_pub_bytes = my_ephemeral_priv.public_key().public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo
                    ).decode('utf-8')
                    
                    reply = Packet("SERVER", src_mac, my_pub_bytes, msg_type=MSG_TYPE_KEY_EXCHANGE)
                    if self.priv_key:
                        sig = self.priv_key.sign(reply.get_bytes_for_signing(), ec.ECDSA(hashes.SHA256()))
                        reply.mac = sig.hex()
                        self.send_notification(reply)
                        
                except Exception as e:
                    print(f"[SEC] ❌ Falha no Key Exchange: {e}")

            # --- DADOS ENCRIPTADOS ---
            else:
                if not session.get('session_key'):
                    print(f"[SEC] ⛔ Ignorado pacote de {src_mac} (Sem Sessão).")
                    return
                
                # Tentar Desencriptar
                if packet.decrypt(session['session_key']):
                    # Se decrypt funcionar, o payload agora é o texto original
                    if self.app_callback:
                        self.app_callback(packet, device_path)
                else:
                    print(f"[SEC] ⚠️ ERRO DE DESENCRIPTAÇÃO de {src_mac}!")

        except Exception as e:
            print(f"[GATT] Erro geral: {e}")

    def send_notification(self, packet):
        """Envia pacote (já encriptado pelo Manager/App se necessário)"""
        if not self.notifying: return
        data = packet.to_bytes()
        self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': dbus.ByteArray(data)}, [])

    def StartNotify(self):
        print("[GATT] 🔔 Notificações ativas.")
        self.notifying = True

    def StopNotify(self):
        print("[GATT] 🔕 Notificações paradas.")
        self.notifying = False

class SICService(Service):
    def __init__(self, bus, index, app_callback, cert_bytes, priv_key):
        Service.__init__(self, bus, index, SIC_SERVICE_UUID, True)
        self.add_characteristic(SICCharacteristic(bus, 0, self, app_callback, cert_bytes, priv_key))