import os, json, time, socket, math, requests, re
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

load_dotenv()

app = FastAPI(title="S-Witch Network Engine", version="4.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GNS3_URL = os.getenv("GNS3_URL", "http://localhost:3080/v2")
OLLAMA_URL = "http://localhost:11434/api/chat"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a Senior Network Engineer.
Rules:
1. For Cisco routers: use 'conf t', 'interface', 'ip address X.X.X.X 255.255.255.0', 'no shutdown'.
2. For VPCS: use 'ip <address>/<mask> <gateway>'.
3. NEVER truncate commands. NEVER abbreviate 'no shutdown'.
4. Always write complete subnet masks: 255.255.255.0
5. Output ONLY valid JSON array."""

def get_gns3_project():
    try:
        projs = requests.get(f"{GNS3_URL}/projects").json()
        if not projs: return None, None
        pid = projs[0]["project_id"]
        return pid, projs[0]
    except: return None, None

def get_gns3_nodes():
    try:
        pid, _ = get_gns3_project()
        if not pid: return {}
        nodes = requests.get(f"{GNS3_URL}/projects/{pid}/nodes").json()
        return {n["name"]: {"console": n.get("console"), "id": n["node_id"], "type": n.get("node_type")} for n in nodes}
    except Exception as e:
        print(f"Erreur GNS3: {e}")
        return {}

def normalize_cisco_command(cmd: str) -> str:
    cmd = cmd.strip()
    if not cmd: return ""
    if re.match(r'^(n|no\s*s|no\s*shu|no\s*shut)$', cmd, re.I):
        return "no shutdown"
    if "ip address" in cmd.lower():
        parts = cmd.split()
        if len(parts) >= 4 and parts[3] == "255" and len(parts) < 5:
            return f"{parts[0]} {parts[1]} {parts[2]} 255.255.255.0"
        elif len(parts) == 3 and re.match(r'\d+\.\d+\.\d+\.\d+', parts[2]):
            return f"{cmd} 255.255.255.0"
    return cmd

def send_to_console(port, command_block: str):
    if not port: return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
            s.settimeout(2)
            time.sleep(1)
            for _ in range(3):
                s.sendall(b"\r\nno\r\n")
                time.sleep(0.5)
            try:
                while s.recv(4096): pass
            except socket.timeout: pass
            s.sendall(b"\nenable\nterminal length 0\n")
            time.sleep(0.5)
            lines = command_block.replace("\\n", "\n").split('\n')
            for line in lines:
                clean = normalize_cisco_command(line)
                if clean and clean.lower() != "enable":
                    s.sendall((clean + '\n').encode('ascii'))
                    delay = 0.8 if any(x in clean.lower() for x in ["ip address", "interface"]) else 0.4
                    time.sleep(delay)
            s.sendall(b"\nend\nwrite\n")
            time.sleep(1)
            return True
    except Exception as e:
        print(f"Erreur Console {port}: {e}")
        return False

def force_configure_r1(pid, node_id, port):
    print(f"Force config R1 sur port {port}...")
    commands = [
        "conf t",
        "no ip domain-lookup",
        "interface FastEthernet0/0",
        "ip address 192.168.1.254 255.255.255.0",
        "no shutdown",
        "exit",
        "interface FastEthernet1/1",
        "ip address 192.168.2.254 255.255.255.0",
        "no shutdown",
        "exit",
        "end",
        "write memory"
    ]
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        print(f"Tentative {attempt}/{max_retries}...")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=120) as s:
                s.settimeout(3)
                print("Attente du prompt Router>...")
                buffer = ""
                deadline = time.time() + 90
                while time.time() < deadline:
                    try:
                        data = s.recv(4096).decode(errors="ignore")
                        buffer += data
                        if "yes/no" in buffer:
                            s.sendall(b"no\r\n")
                            buffer = ""
                            time.sleep(2)
                        if "Router>" in buffer or "Router#" in buffer:
                            print("Prompt detecte !")
                            break
                    except socket.timeout:
                        s.sendall(b"\r\n")
                        time.sleep(1)

                s.sendall(b"enable\r\n")
                time.sleep(1)
                for cmd in commands:
                    print(f"  -> {cmd}")
                    s.sendall((cmd + "\n").encode())
                    delay = 1.2 if any(x in cmd for x in ["interface", "ip address"]) else 0.8
                    time.sleep(delay)

            # Verification
            time.sleep(5)
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
                s.settimeout(3)
                s.sendall(b"\r\nshow ip interface brief\r\n")
                time.sleep(2)
                output = ""
                try:
                    output = s.recv(4096).decode(errors="ignore")
                except: pass
                print(f"Verification R1:\n{output}")
                if "192.168.1.254" in output and "up" in output.lower():
                    print("R1 stable et configure !")
                    return True
                else:
                    print(f"Config absente, nouvelle tentative...")

        except Exception as e:
            print(f"Erreur tentative {attempt}: {e}")

    print("Echec configuration R1 apres 3 tentatives")
    return False

def add_missing_links(pid, created_nodes, node_name_map):
    """Ajoute automatiquement les liens manquants PC<->Switch"""
    print("Ajout des liens manquants...")
    
    # Récupérer les liens existants
    existing_links = requests.get(f"{GNS3_URL}/projects/{pid}/links").json()
    connected_nodes = set()
    for l in existing_links:
        for n in l['nodes']:
            connected_nodes.add(n['node_id'])
    
    # Trouver les switches et les PCs non connectés
    switches = {name: data for name, data in node_name_map.items() if 'Switch' in name}
    pcs = {name: data for name, data in node_name_map.items() if name.startswith('PC')}
    
    links_added = 0
    switch_port_counters = {}
    
    # Initialiser les compteurs de ports (après les liens existants)
    for l in existing_links:
        for n in l['nodes']:
            nid = n['node_id']
            nname = next((name for name, d in node_name_map.items() if d['id'] == nid), None)
            if nname and 'Switch' in nname:
                current = switch_port_counters.get(nname, 0)
                switch_port_counters[nname] = max(current, n['port_number'] + 1)
    
    # Connecter chaque PC à son switch
    pc_switch_map = {
        'PC1': 'Switch1', 'PC2': 'Switch1',
        'PC3': 'Switch2', 'PC4': 'Switch2'
    }
    
    for pc_name, sw_name in pc_switch_map.items():
        if pc_name not in node_name_map or sw_name not in node_name_map:
            continue
        
        pc_id = node_name_map[pc_name]['id']
        sw_id = node_name_map[sw_name]['id']
        
        # Vérifier si déjà connecté
        already_connected = any(
            (n['node_id'] == pc_id)
            for l in existing_links
            for n in l['nodes']
        )
        
        if not already_connected:
            sw_port = switch_port_counters.get(sw_name, 1)
            res = requests.post(f"{GNS3_URL}/projects/{pid}/links", json={
                "nodes": [
                    {"node_id": pc_id, "adapter_number": 0, "port_number": 0},
                    {"node_id": sw_id, "adapter_number": 0, "port_number": sw_port}
                ]
            })
            if res.status_code in [200, 201]:
                links_added += 1
                switch_port_counters[sw_name] = sw_port + 1
                print(f"Lien ajoute: {pc_name} <-> {sw_name} (port {sw_port})")
            else:
                print(f"Echec lien {pc_name}<->{sw_name}: {res.text[:80]}")
    
    return links_added

def call_llm(prompt, system=None):
    api_key = os.getenv("GROQ_API_KEY")
    model = "llama-3.3-70b-versatile" if api_key else "qwen2.5:7b"
    start = time.time()
    try:
        if api_key:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            res = requests.post(GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": messages, "temperature": 0},
                timeout=30)
            content = res.json()['choices'][0]['message']['content']
        else:
            res = requests.post(OLLAMA_URL,
                json={"model": model, "stream": False,
                      "options": {"num_predict": 2048, "temperature": 0},
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=60)
            content = res.json()['message']['content']
        print(f"LLM: {round(time.time()-start,2)}s | {model}")
        return content
    except Exception as e:
        print(f"Erreur LLM: {e}")
        return None

def generate_config(topology, question):
    prompt = f"""Context topology: {json.dumps(topology)}
Request: {question}

Output ONLY JSON array:
[
  {{"device": "PC1", "command": "ip 192.168.1.1/24 192.168.1.254", "comment": "IP PC1"}},
  {{"device": "PC2", "command": "ip 192.168.1.2/24 192.168.1.254", "comment": "IP PC2"}},
  {{"device": "R1", "command": "conf t\\ninterface FastEthernet0/0\\nip address 192.168.1.254 255.255.255.0\\nno shutdown\\ninterface FastEthernet1/1\\nip address 192.168.2.254 255.255.255.0\\nno shutdown\\nend", "comment": "Gateway R1"}}
]"""
    content = call_llm(prompt, system=SYSTEM_PROMPT)
    if not content: return []
    try:
        match = re.search(r'\[.*\]', content, re.DOTALL)
        result = json.loads(match.group()) if match else []
        print(f"Commandes: {len(result)} equipements")
        for r in result:
            print(f"  -> {r.get('device')}: {r.get('command','')[:80]}")
        return result
    except Exception as e:
        print(f"Erreur parsing: {e}")
        return []

@app.get("/")
def root():
    return {"message": "S-Witch Network Engine v4.1", "version": "4.1.0"}

@app.get("/health")
def health():
    return {"status": "ok", "nodes": len(get_gns3_nodes())}

@app.post("/v4/invoke")
async def apply_config(request: Request):
    data = await request.json()
    req = data.get("input", {})
    topology = req.get("topology", {})
    if isinstance(topology, str): topology = json.loads(topology)
    question = req.get("question", "")
    print(f"\n[v4] {question}")
    configs = generate_config(topology, question)
    if not configs:
        return {"output": [], "error": "LLM failed"}
    time.sleep(1)
    node_map = get_gns3_nodes()
    applied = []
    for item in configs:
        name = item.get("device")
        cmds = item.get("command")
        if name in node_map:
            port = node_map[name]["console"]
            print(f"Tentative sur {name} (Port: {port})...")
            if port:
                success = send_to_console(port, cmds)
                item["status"] = "success" if success else "failed"
                if success: applied.append(name)
        else:
            item["status"] = "node_not_found"
    print(f"Applique: {', '.join(applied) if applied else 'RIEN'}")
    return {"output": configs, "applied_to": applied}

@app.post("/v5/invoke")
async def process_config(request: Request):
    data = await request.json()
    req_input = data.get("input", {})
    topology = req_input.get("topology", {})
    if isinstance(topology, str): topology = json.loads(topology)
    question = req_input.get("question", "")
    print(f"\n[v5] {question}")
    configs = generate_config(topology, question)
    if not configs:
        return {"output": [], "error": "LLM failed"}
    time.sleep(1)
    node_map = get_gns3_nodes()
    applied = []
    for item in configs:
        name = item.get("device")
        cmds = item.get("command")
        if name in node_map:
            port = node_map[name]["console"]
            print(f"Tentative sur {name} (Port: {port})...")
            if port:
                success = send_to_console(port, cmds)
                item["status"] = "success" if success else "failed"
                if success: applied.append(name)
        else:
            item["status"] = "node_not_found"
    print(f"Applique: {', '.join(applied) if applied else 'RIEN'}")
    return {"output": configs, "applied_to": applied}

@app.post("/v6/invoke")
async def gen_topology(request: Request):
    data = await request.json()
    question = data.get("input", {}).get("question", "")
    print(f"\n[v6] {question}")
    prompt = f"""Task: {question}
Generate a complete GNS3 topology. Node types: vpcs, ethernet_switch, dynamips.
IMPORTANT: Include ALL links between ALL devices.

Output ONLY valid JSON:
{{
  "node_info": [
    {{"node_id": "auto-1", "type": "dynamips", "name": "R1", "ports": [{{"port_number": 0}}, {{"port_number": 1}}]}},
    {{"node_id": "auto-2", "type": "ethernet_switch", "name": "Switch1", "ports": [{{"port_number": 0}}, {{"port_number": 1}}, {{"port_number": 2}}]}},
    {{"node_id": "auto-3", "type": "ethernet_switch", "name": "Switch2", "ports": [{{"port_number": 0}}, {{"port_number": 1}}, {{"port_number": 2}}]}},
    {{"node_id": "auto-4", "type": "vpcs", "name": "PC1", "ports": [{{"port_number": 0}}]}},
    {{"node_id": "auto-5", "type": "vpcs", "name": "PC2", "ports": [{{"port_number": 0}}]}},
    {{"node_id": "auto-6", "type": "vpcs", "name": "PC3", "ports": [{{"port_number": 0}}]}},
    {{"node_id": "auto-7", "type": "vpcs", "name": "PC4", "ports": [{{"port_number": 0}}]}}
  ],
  "link_info": [
    {{"link_id": "link-1", "node1_id": "auto-1", "node2_id": "auto-2", "node1_port": 0, "node2_port": 0}},
    {{"link_id": "link-2", "node1_id": "auto-1", "node2_id": "auto-3", "node1_port": 1, "node2_port": 0}},
    {{"link_id": "link-3", "node1_id": "auto-4", "node2_id": "auto-2", "node1_port": 0, "node2_port": 1}},
    {{"link_id": "link-4", "node1_id": "auto-5", "node2_id": "auto-2", "node1_port": 0, "node2_port": 2}},
    {{"link_id": "link-5", "node1_id": "auto-6", "node2_id": "auto-3", "node1_port": 0, "node2_port": 1}},
    {{"link_id": "link-6", "node1_id": "auto-7", "node2_id": "auto-3", "node1_port": 0, "node2_port": 2}}
  ]
}}"""
    content = call_llm(prompt)
    if not content: return {"output": None, "error": "LLM failed"}
    try:
        topo = json.loads(content[content.find('{'):content.rfind('}')+1])
        print(f"Topologie: {len(topo.get('node_info',[]))} noeuds, {len(topo.get('link_info',[]))} liens")
        return {"output": topo}
    except Exception as e:
        return {"output": None, "error": str(e)}

@app.post("/v7/invoke")
async def deploy_gns3(request: Request):
    data = await request.json()
    topo = data.get("input", {}).get("topology", {})
    if isinstance(topo, str): topo = json.loads(topo)
    print(f"\n[v7] Deploiement GNS3...")
    try:
        pid, _ = get_gns3_project()
        if not pid: return {"output": None, "error": "No GNS3 project"}
        
        created = {}
        node_name_map = {}
        
        for i, n in enumerate(topo.get("node_info", [])):
            angle = (2 * math.pi * i) / max(len(topo["node_info"]), 1)
            payload = {
                "name": n["name"], "node_type": n["type"], "compute_id": "local",
                "x": int(400 * math.cos(angle)), "y": int(400 * math.sin(angle))
            }
            if n["type"] == "dynamips":
                payload["properties"] = {
                    "platform": "c7200", "ram": 512,
                    "slot0": "C7200-IO-FE", "slot1": "PA-2FE-TX",
                    "image": "c7200-advipservicesk9-mz.152-4.S5.image"
                }
            res = requests.post(f"{GNS3_URL}/projects/{pid}/nodes", json=payload).json()
            created[n["node_id"]] = res
            node_name_map[n["name"]] = {"id": res["node_id"], "type": n["type"], "console": res.get("console")}
            requests.post(f"{GNS3_URL}/projects/{pid}/nodes/{res['node_id']}/start", json={})
            print(f"{n['name']} cree et demarre")

        print("Attente 5s boot GNS3...")
        time.sleep(5)

        adapter_map = {}
        links_ok = 0
        for l in topo.get("link_info", []):
            n1 = created.get(l.get("node1_id"))
            n2 = created.get(l.get("node2_id"))
            if n1 and n2:
                a1 = adapter_map.get(n1['name'], 0)
                a2 = adapter_map.get(n2['name'], 0)
                res = requests.post(f"{GNS3_URL}/projects/{pid}/links", json={
                    "nodes": [
                        {"node_id": n1["node_id"], "adapter_number": a1, "port_number": 0},
                        {"node_id": n2["node_id"], "adapter_number": a2, "port_number": 0}
                    ]
                })
                if res.status_code in [200, 201]:
                    links_ok += 1
                    if n1.get("node_type") == "dynamips" or "R" in n1.get("name", ""):
                        adapter_map[n1['name']] = a1 + 1
                    if n2.get("node_type") == "dynamips" or "R" in n2.get("name", ""):
                        adapter_map[n2['name']] = a2 + 1
                    print(f"Lien: {n1['name']}(a={a1}) <-> {n2['name']}(a={a2})")

        # Ajouter les liens manquants automatiquement
        missing = add_missing_links(pid, created, node_name_map)
        links_ok += missing

        # Force config R1 si présent
        if "R1" in node_name_map and node_name_map["R1"].get("console"):
           
            time.sleep(0)
            force_configure_r1(pid, node_name_map["R1"]["id"], node_name_map["R1"]["console"])

        print(f"Deploye: {len(created)} noeuds, {links_ok} liens")
        return {"output": {
            "nodes_created": len(created),
            "links": [{"ok": True}] * links_ok,
            "project_name": "LLM-NetConf",
            "project_id": pid
        }}
    except Exception as e:
        print(f"Erreur v7: {e}")
        return {"output": None, "error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
