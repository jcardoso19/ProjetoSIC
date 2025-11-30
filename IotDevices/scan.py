import simplepyble

def makeScan (adapter,time) :
    
    adapter.set_callback_on_scan_start(lambda: print("Scan started."))
    adapter.set_callback_on_scan_stop(lambda: print("Scan complete."))

    adapter.scan_for(time)
    return adapter.scan_get_results()

