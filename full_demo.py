import requests
import json
import telnetlib
import time
import sys
sys.path.append('.')
from dotenv import load_dotenv
load_dotenv()
from api.app.chains.chain_v4 import chain

GNS3_URL = "http://localhost:3080/v2"

print("="*60)
print("DEMO COMPLETE S-WITCH + GNS3")
print("="*60)

# Etape 1 - Recuperer topologie GNS3
print("\n[1/4] Recuperation de la topologie GNS3...")
projects = requests.get(f"{GNS3_URL}/projects").json()
project_id = projects[0]["project_id"]
nodes = requests.get(f"{GNS3_URL}/projects/{project_id}/nodes").json()
links = requests.get(f"{GNS3_URL}/projects/{project_id}/links").json()

topology = {
    "node_info": [],
    "link_info": []
}
for node in nodes:
    ports = [{"name": p.get("name",""), "port_number": p.get("port_number",0), "link_type": "ethernet"} for p in node.get("ports",[])]
    topology["node_info"].append({
        "node_id": node["node_id"],
        "name": node["name"],
        "node_type": node["node_type"],
        "console": node.get("console"),
        "console_host": node.get("console_host","127.0.0.1"),
        "ports": ports
    })
for link in links:
    topology["link_info"].append({
        "link_id": link["link_id"],
        "link_type": "ethernet",
        "nodes": [{"node_id": n["node_id"], "port_number": n.get("port_number",0)} for n in link.get("nodes",[])]
    })

print(f"Topologie recup: {len(nodes)} equipements, {len(links)} liens")

# Etape 2 - LLM genere les commandes
print("\n[2/4] Envoi au LLM (Groq)...")
question = "Configure all PCs to ping each other. Assign IPs in 192.168.1.0/24 subnet."

result = chain.invoke({
    "topology": topology,
    "chat_history": [],
    "question": question
})

print(f"LLM a genere: {result}")

# Etape 3 - Appliquer les commandes via Telnet
print("\n[3/4] Application des commandes sur GNS3...")

node_map = {n["name"]: n for n in topology["node_info"]}

def send_telnet_command(host, port, commands, device_name):
    try:
        print(f"  Connexion Telnet a {device_name} (port {port})...")
        tn = telnetlib.Telnet(host, port, timeout=5)
        time.sleep(1)
        tn.read_very_eager()
        
        for cmd in commands:
            if cmd.strip():
                tn.write(cmd.encode('ascii') + b'\n')
                time.sleep(0.5)
        
        time.sleep(1)
        output = tn.read_very_eager().decode('ascii', errors='ignore')
        tn.close()
        print(f"  {device_name}: commandes appliquees !")
        return output
    except Exception as e:
        print(f"  Erreur {device_name}: {e}")
        return None

device_name = result.get("device", "")
command = result.get("command", "")

if device_name and command and device_name in node_map:
    node = node_map[device_name]
    if node.get("console"):
        commands = command.replace("\\n", "\n").split("\n")
        send_telnet_command("127.0.0.1", node["console"], commands, device_name)

# Etape 4 - Test ping
print("\n[4/4] Test de connectivite...")
print("Connexion a PC1 pour tester le ping...")

pc1 = node_map.get("PC1")
if pc1 and pc1.get("console"):
    try:
        tn = telnetlib.Telnet("127.0.0.1", pc1["console"], timeout=5)
        time.sleep(1)
        tn.read_very_eager()
        tn.write(b"ping 192.168.1.2\n")
        time.sleep(3)
        output = tn.read_very_eager().decode('ascii', errors='ignore')
        tn.close()
        if "bytes from" in output:
            print("PING REUSSI ! La demonstration est complete !")
        else:
            print(f"Reponse PC1: {output[:200]}")
    except Exception as e:
        print(f"Erreur ping: {e}")

print("\n" + "="*60)
print("DEMO TERMINEE !")
print("="*60)