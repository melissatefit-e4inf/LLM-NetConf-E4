import requests, json, socket, time, sys
sys.path.append('.')
from dotenv import load_dotenv
load_dotenv()
from api.app.chains.chain_v4 import chain

GNS3_URL = "http://localhost:3080/v2"
print("="*50)
print("DEMO S-WITCH + GNS3")
print("="*50)

projects = requests.get(f"{GNS3_URL}/projects").json()
project_id = projects[0]["project_id"]
nodes = requests.get(f"{GNS3_URL}/projects/{project_id}/nodes").json()
links = requests.get(f"{GNS3_URL}/projects/{project_id}/links").json()

topology = {"node_info": [], "link_info": []}
for node in nodes:
    ports = [{"name": p.get("name",""), "port_number": p.get("port_number",0), "link_type": "ethernet"} for p in node.get("ports",[])]
    topology["node_info"].append({"node_id": node["node_id"], "name": node["name"], "node_type": node["node_type"], "console": node.get("console"), "console_host": "127.0.0.1", "ports": ports})
for link in links:
    topology["link_info"].append({"link_id": link["link_id"], "link_type": "ethernet", "nodes": [{"node_id": n["node_id"], "port_number": n.get("port_number",0)} for n in link.get("nodes",[])]})

print(f"[1/4] {len(nodes)} equipements trouves")

result = chain.invoke({"topology": topology, "chat_history": [], "question": "Configure all PCs to ping each other in 192.168.1.0/24"})
print(f"[2/4] LLM: {result}")

node_map = {n["name"]: n for n in topology["node_info"]}

def send(host, port, cmds, name):
    try:
        s = socket.socket()
        s.connect((host, port))
        s.settimeout(5)
        time.sleep(1)
        try: s.recv(1024)
        except: pass
        for cmd in cmds:
            if cmd.strip():
                s.send((cmd+"\n").encode())
                time.sleep(0.5)
        time.sleep(1)
        try: out = s.recv(4096).decode(errors="ignore")
        except: out = ""
        s.close()
        print(f"  {name}: OK")
        return out
    except Exception as e:
        print(f"  Erreur {name}: {e}")

print("[3/4] Application commandes...")
dev = result.get("device","")
cmd = result.get("command","")
if dev and cmd and dev in node_map:
    node = node_map[dev]
    if node.get("console"):
        send("127.0.0.1", node["console"], cmd.replace("\\n","\n").split("\n"), dev)

print("[4/4] Test ping...")
pc1 = node_map.get("PC1")
if pc1 and pc1.get("console"):
    try:
        s = socket.socket()
        s.connect(("127.0.0.1", pc1["console"]))
        s.settimeout(5)
        time.sleep(1)
        try: s.recv(1024)
        except: pass
        s.send(b"ping 192.168.1.2\n")
        time.sleep(3)
        try: out = s.recv(4096).decode(errors="ignore")
        except: out = ""
        s.close()
        print("PING REUSSI!" if "bytes" in out else f"Reponse: {out[:100]}")
    except Exception as e:
        print(f"Erreur: {e}")

print("="*50)
print("DEMO TERMINEE!")
