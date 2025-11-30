import simplepyble
from scan import makeScan

def connect () :

    # Parte inicial de escolha de adaptador pode depois ser retirada caso exista um apenas
    # por componente ou já existir predefenido para o mesmo
    # O mesmo se aplica caso produto final seja rede de ligações ja predefinidas
    
    adapters = simplepyble.Adapter.get_adapters()

    if len(adapters) == 0 :
        print("No adapters found")

    # Escolher adaptador a ser usado
    print("Chose and adapter:\n")
    for i, adapter in enumerate(adapters) :
        print(f"{i}: {adapter.identifier()} [{adapter.address()}]")
    
    adapter = adapters[( int( input("Enter choise:") ) )]

    # Escolher target a ser usado
    targets = makeScan(adapter, 5000)

    print("Chose target:\n ")
    for i, target in enumerate(targets) :
        print(f"{i}: {target.identifier()} [{target.address()}]")

    target = targets[( int( input("Enter choise: ") ) )]

    # Executing the connection
    print("Connecting...")
    try:
        target.connect()
    except:
        print("Target was't able to establish connection")
        return None

    print("Connected!")
    return target

def disconnect ( target ) :
    try :
        target.disconnect()
    except:
        print("Target wasn't disconnected")
