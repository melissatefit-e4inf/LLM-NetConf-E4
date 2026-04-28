import socket, time

def wait_for_prompt(s, expected, timeout=30):
    """Attend un texte spécifique dans la réponse du routeur"""
    buffer = ""
    start = time.time()
    while time.time() - start < timeout:
        try:
            data = s.recv(4096).decode(errors="ignore")
            buffer += data
            print(data, end="", flush=True)
            if expected in buffer:
                return True
        except socket.timeout:
            pass
    return False

def force_r1(port=5000):
    print(f"Connexion a R1 sur port {port}...")
    
    with socket.create_connection(("127.0.0.1", port), timeout=15) as s:
        s.settimeout(3)
        
        # Etape 1 : Repondre 'no' au wizard si present
        print("\n--- Etape 1 : Gestion du wizard Cisco ---")
        s.sendall(b"\n")
        time.sleep(2)
        
        buf = ""
        try:
            buf = s.recv(4096).decode(errors="ignore")
            print(buf)
        except: pass
        
        if "yes/no" in buf or "configuration dialog" in buf:
            print("Wizard detecte ! Envoi de 'no'...")
            s.sendall(b"no\n")
            time.sleep(2)
            try:
                print(s.recv(4096).decode(errors="ignore"))
            except: pass
        
        # Etape 2 : Attendre le prompt Router>
        print("\n--- Etape 2 : Passage en mode privilege ---")
        s.sendall(b"\n")
        time.sleep(1)
        s.sendall(b"enable\n")
        time.sleep(1)
        try:
            print(s.recv(4096).decode(errors="ignore"))
        except: pass
        
        # Etape 3 : Configuration des interfaces
        print("\n--- Etape 3 : Configuration des interfaces ---")
        commands = [
            "conf t",
            "int f0/0",
            "ip address 192.168.1.254 255.255.255.0",
            "no shutdown",
            "exit",
            "int f1/1",
            "ip address 192.168.2.254 255.255.255.0", 
            "no shutdown",
            "exit",
            "end",
            "write memory"
        ]
        
        for cmd in commands:
            print(f"  -> {cmd}")
            s.sendall((cmd + "\n").encode())
            time.sleep(0.8)
            try:
                out = s.recv(4096).decode(errors="ignore")
                if "Invalid" in out or "Error" in out:
                    print(f"  ERREUR: {out}")
                else:
                    print(f"  OK")
            except: pass
        
        # Etape 4 : Verification
        print("\n--- Etape 4 : Verification ---")
        s.sendall(b"show ip interface brief\n")
        time.sleep(2)
        try:
            result = s.recv(4096).decode(errors="ignore")
            print(result)
        except: pass
        
        print("\nR1 configure ! Lance le ping depuis PC1 !")

force_r1()
