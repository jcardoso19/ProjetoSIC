import uuid

class NID:
    
    def __init__(self,value = None):
        if value == None:
            self.uuid = uuid.uuid4()
        elif isinstance(value,uuid.UUID):
            self.uuid = value
        elif isinstance(value,str):
            self.uuid = uuid.UUID(value)
        else:
            print("NID value inválido!")
    def __str__(self):
        return str(self.uuid)
    
    def uuidBytes(self):
        return self.uuid.bytes
    def BytesUUID(b):
        if len(b) != 16:
            print("NID value inválido")
        return NID(uuid.UUID(bytes=b))
    