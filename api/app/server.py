import os
import json
import time
import socket
import math
import requests
import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn


load_dotenv()

app = FastAPI(title="S-Witch Network Engine", version="4.2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GNS3_URL = os.getenv("GNS3_URL", "http://localhost:3080/v2")
OLLAMA_URL = "http://localhost:11434/api/chat"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a Senior Network Engineer.
Rules:
1. For Cisco routers: use 'conf t', 'interface', 'ip address X.X.X.X 255.255.255.0', 'no shutdown'.
2. For VPCS: use 'ip <address>/<mask> <gateway>'.
3. NEVER truncate. NEVER abbreviate 'no shutdown'.
4. Always write complete subnet masks: 255.255.255.0
5. Output ONLY valid JSON array."""

FIXED_PORTS = {
    "R1": 5000,
    "Switch1": 5001,
    "PC1": 5002,
    "PC2": 5004,
    "Switch2": 5006,
    "PC3": 5007,
    "PC4": 5009,
}


def get_gns3_project():
    try:
        projs = requests.get(f"{GNS3_URL}/projects").json()
        if not projs:
            return None, None
        return projs[0]["project_id"], projs[0]
    except Exception:
        return None, None


def get_gns3_nodes():
    try:
        pid, _ = get_gns3_project()
        if not pid:
            return {}

        nodes = requests.get(f"{GNS3_URL}/projects/{pid}/nodes").json()

        return {
            n["name"]: {
                "console": n.get("console"),
                "id": n["node_id"],
                "type": n.get("node_type"),
            }
            for n in nodes
        }

    except Exception as e:
        print(f"Erreur GNS3: {e}")
        return {}


def normalize_cisco_command(cmd: str) -> str:
    cmd = cmd.strip()

    if not cmd:
        return ""

    if re.match(r"^(n|no\s*s|no\s*shu|no\s*shut)$", cmd, re.I):
        return "no shutdown"

    if "ip address" in cmd.lower():
        parts = cmd.split()

        if len(parts) >= 4 and parts[3] == "255" and len(parts) < 5:
            return f"{parts[0]} {parts[1]} {parts[2]} 255.255.255.0"

        if len(parts) == 3 and re.match(r"\d+\.\d+\.\d+\.\d+", parts[2]):
            return f"{cmd} 255.255.255.0"

    return cmd


def send_to_console(port, command_block: str):
    """
    Envoie proprement des commandes dans la console GNS3.
    Version stable pour IOS Cisco/Dynamips :
    - utilise \\r\\n au lieu de \\n ;
    - ajoute un délai entre les commandes ;
    - évite que les commandes soient collées.
    """

    if not port:
        return False

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
            s.settimeout(2)

            time.sleep(1)

            for _ in range(3):
                s.sendall(b"\r\nno\r\n")
                time.sleep(0.5)

            try:
                while s.recv(4096):
                    pass
            except socket.timeout:
                pass

            s.sendall(b"\r\nenable\r\nterminal length 0\r\n")
            time.sleep(1)

            for line in command_block.replace("\\n", "\n").split("\n"):
                clean = normalize_cisco_command(line)

                if clean and clean.lower() != "enable":
                    print(f"  -> {clean}")
                    s.sendall((clean + "\r\n").encode("ascii"))

                    delay = (
                        1.5
                        if any(
                            x in clean.lower()
                            for x in ["ip address", "interface", "write", "copy"]
                        )
                        else 0.8
                    )

                    time.sleep(delay)

            s.sendall(b"\r\nend\r\nwrite memory\r\n")
            time.sleep(2)

            return True

    except Exception as e:
        print(f"Erreur Console {port}: {e}")
        return False


def wait_for_router_prompt(s, timeout=120):
    """
    Attend que le routeur Cisco soit prêt.
    Gère le wizard initial et les redémarrages éventuels.
    """

    buffer = ""
    last_prompt_time = None
    deadline = time.time() + timeout
    wizard_count = 0

    while time.time() < deadline:
        try:
            data = s.recv(4096).decode(errors="ignore")
            buffer += data

            if "yes/no" in buffer.lower():
                wizard_count += 1
                print(f"Wizard détecté ({wizard_count}x) -> envoi 'no'")
                s.sendall(b"no\r\n")
                buffer = ""
                time.sleep(2)
                continue

            if "Router>" in buffer or "Router#" in buffer:
                if last_prompt_time is None:
                    last_prompt_time = time.time()
                    print("Premier prompt détecté, attente stabilisation...")
                elif time.time() - last_prompt_time > 5:
                    print("Prompt stable confirmé.")
                    return True
            else:
                last_prompt_time = None

            if "System restarted" in buffer or "RESTART" in buffer:
                print("Reboot R1 détecté, reset attente...")
                buffer = ""
                last_prompt_time = None

        except socket.timeout:
            s.sendall(b"\r\n")
            time.sleep(1)

    return False


def force_configure_r1(port, max_retries=3):
    """
    Configuration robuste de R1.
    Utilisé après création de la topologie pour forcer la config des interfaces.
    """

    commands = [
        "conf t",
        "no ip domain-lookup",
        "interface FastEthernet0/0",
        "ip address 192.168.1.254 255.255.255.0",
        "no shutdown",
        "exit",
        "interface FastEthernet1/0",
        "ip address 192.168.2.254 255.255.255.0",
        "no shutdown",
        "exit",
        "end",
        "write memory",
    ]

    for attempt in range(1, max_retries + 1):
        print(f"\nTentative config R1 {attempt}/{max_retries} sur port {port}...")

        try:
            with socket.create_connection(("127.0.0.1", port), timeout=150) as s:
                s.settimeout(3)

                if not wait_for_router_prompt(s, timeout=120):
                    print(f"Timeout attente prompt tentative {attempt}")
                    continue

                s.sendall(b"enable\r\n")
                time.sleep(1)

                print("Envoi des commandes de configuration...")

                for cmd in commands:
                    print(f"  -> {cmd}")
                    s.sendall((cmd + "\r\n").encode("ascii"))

                    delay = (
                        1.5
                        if any(x in cmd.lower() for x in ["interface", "ip address", "write"])
                        else 0.8
                    )

                    time.sleep(delay)

                time.sleep(3)

                s.sendall(b"show ip interface brief\r\n")
                time.sleep(3)

                output = ""

                try:
                    output = s.recv(8192).decode(errors="ignore")
                except Exception:
                    pass

                print(f"Vérification:\n{output[:500]}")

                if "192.168.1.254" in output and "up" in output.lower():
                    print("R1 configuré et stable.")
                    return True

                print("Vérification échouée, nouvelle tentative...")

        except Exception as e:
            print(f"Erreur tentative {attempt}: {e}")
            time.sleep(5)

    print("Échec configuration R1 après toutes les tentatives.")
    return False


def add_missing_links(pid, created_nodes, node_name_map):
    print("Vérification des liens manquants...")

    existing_links = requests.get(f"{GNS3_URL}/projects/{pid}/links").json()
    switch_port_counters = {}

    for link in existing_links:
        for node in link["nodes"]:
            node_id = node["node_id"]

            node_name = next(
                (
                    name
                    for name, data in node_name_map.items()
                    if data["id"] == node_id
                ),
                None,
            )

            if node_name and "Switch" in node_name:
                current = switch_port_counters.get(node_name, 0)
                switch_port_counters[node_name] = max(
                    current,
                    node["port_number"] + 1,
                )

    pc_switch_map = {
        "PC1": "Switch1",
        "PC2": "Switch1",
        "PC3": "Switch2",
        "PC4": "Switch2",
    }

    links_added = 0

    for pc_name, sw_name in pc_switch_map.items():
        if pc_name not in node_name_map or sw_name not in node_name_map:
            continue

        pc_id = node_name_map[pc_name]["id"]

        already_connected = any(
            node["node_id"] == pc_id
            for link in existing_links
            for node in link["nodes"]
        )

        if not already_connected:
            sw_port = switch_port_counters.get(sw_name, 1)

            res = requests.post(
                f"{GNS3_URL}/projects/{pid}/links",
                json={
                    "nodes": [
                        {
                            "node_id": pc_id,
                            "adapter_number": 0,
                            "port_number": 0,
                        },
                        {
                            "node_id": node_name_map[sw_name]["id"],
                            "adapter_number": 0,
                            "port_number": sw_port,
                        },
                    ]
                },
            )

            if res.status_code in [200, 201]:
                links_added += 1
                switch_port_counters[sw_name] = sw_port + 1
                print(f"Lien ajouté: {pc_name} <-> {sw_name}")

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

            res = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0,
                },
                timeout=30,
            )

            content = res.json()["choices"][0]["message"]["content"]

        else:
            res = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "stream": False,
                    "options": {
                        "num_predict": 2048,
                        "temperature": 0,
                    },
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                },
                timeout=60,
            )

            content = res.json()["message"]["content"]

        print(f"LLM: {round(time.time() - start, 2)}s | {model}")
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
  {{"device": "PC3", "command": "ip 192.168.2.1/24 192.168.2.254", "comment": "IP PC3"}},
  {{"device": "PC4", "command": "ip 192.168.2.2/24 192.168.2.254", "comment": "IP PC4"}},
  {{"device": "R1", "command": "conf t\\ninterface FastEthernet0/0\\nip address 192.168.1.254 255.255.255.0\\nno shutdown\\ninterface FastEthernet1/0\\nip address 192.168.2.254 255.255.255.0\\nno shutdown\\nend", "comment": "Gateway R1"}}
]"""

    content = call_llm(prompt, system=SYSTEM_PROMPT)

    if not content:
        return []

    try:
        match = re.search(r"\[.*\]", content, re.DOTALL)
        result = json.loads(match.group()) if match else []

        print(f"Commandes: {len(result)} équipements")

        for item in result:
            print(
                f"  -> {item.get('device')}: "
                f"{item.get('command', '')[:80]}"
            )

        return result

    except Exception as e:
        print(f"Erreur parsing: {e}")
        return []


@app.get("/")
def root():
    return {
        "message": "S-Witch Network Engine v4.2.1",
        "version": "4.2.1",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "nodes": len(get_gns3_nodes()),
    }


@app.post("/v4/invoke")
async def apply_config(request: Request):
    data = await request.json()
    req = data.get("input", {})

    topology = req.get("topology", {})

    if isinstance(topology, str):
        topology = json.loads(topology)

    question = req.get("question", "")

    print(f"\n[v4] {question}")

    configs = generate_config(topology, question)

    if not configs:
        return {
            "output": [],
            "error": "LLM failed",
        }

    time.sleep(1)

    node_map = get_gns3_nodes()
    applied = []

    for item in configs:
        name = item.get("device")
        cmds = item.get("command")

        if name in node_map:
            port = node_map[name]["console"]
            print(f"Config {name} sur port {port}...")

            if port:
                success = send_to_console(port, cmds)
                item["status"] = "success" if success else "failed"

                if success:
                    applied.append(name)

        else:
            item["status"] = "node_not_found"

    print(f"Appliqué: {', '.join(applied) if applied else 'RIEN'}")

    return {
        "output": configs,
        "applied_to": applied,
    }


@app.post("/v5/invoke")
async def process_config(request: Request):
    data = await request.json()
    req_input = data.get("input", {})

    topology = req_input.get("topology", {})

    if isinstance(topology, str):
        topology = json.loads(topology)

    question = req_input.get("question", "")

    print(f"\n[v5] {question}")

    configs = generate_config(topology, question)

    if not configs:
        return {
            "output": [],
            "error": "LLM failed",
        }

    time.sleep(1)

    node_map = get_gns3_nodes()
    applied = []

    for item in configs:
        name = item.get("device")
        cmds = item.get("command")

        if name in node_map:
            port = node_map[name]["console"]
            print(f"Config {name} sur port {port}...")

            if port:
                success = send_to_console(port, cmds)
                item["status"] = "success" if success else "failed"

                if success:
                    applied.append(name)

        else:
            item["status"] = "node_not_found"

    print(f"Appliqué: {', '.join(applied) if applied else 'RIEN'}")

    return {
        "output": configs,
        "applied_to": applied,
    }


@app.post("/v6/invoke")
async def gen_topology(request: Request):
    data = await request.json()
    question = data.get("input", {}).get("question", "")

    print(f"\n[v6] {question}")

    prompt = f"""Task: {question}
Generate a complete GNS3 topology. Node types: vpcs, ethernet_switch, dynamips.
Include ALL links between ALL devices.

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

    if not content:
        return {
            "output": None,
            "error": "LLM failed",
        }

    try:
        topo = json.loads(content[content.find("{"):content.rfind("}") + 1])

        print(f"Topologie: {len(topo.get('node_info', []))} noeuds")

        return {
            "output": topo,
        }

    except Exception as e:
        return {
            "output": None,
            "error": str(e),
        }


@app.post("/v7/invoke")
async def deploy_gns3(request: Request):
    data = await request.json()

    topo = data.get("input", {}).get("topology", {})

    if isinstance(topo, str):
        topo = json.loads(topo)

    print("\n[v7] Déploiement GNS3...")

    try:
        pid, _ = get_gns3_project()

        if not pid:
            return {
                "output": None,
                "error": "No GNS3 project",
            }

        created = {}
        node_name_map = {}

        for i, node in enumerate(topo.get("node_info", [])):
            angle = (2 * math.pi * i) / max(len(topo["node_info"]), 1)

            payload = {
                "name": node["name"],
                "node_type": node["type"],
                "compute_id": "local",
                "x": int(400 * math.cos(angle)),
                "y": int(400 * math.sin(angle)),
            }

            if node["type"] == "dynamips":
                payload["properties"] = {
                    "platform": "c7200",
                    "ram": 512,
                    "slot0": "C7200-IO-FE",
                    "slot1": "PA-FE-TX",
                    "image": "c7200-advipservicesk9-mz.152-4.S5.image",
                }

            res = requests.post(
                f"{GNS3_URL}/projects/{pid}/nodes",
                json=payload,
            ).json()

            created[node["node_id"]] = res

            node_name_map[node["name"]] = {
                "id": res["node_id"],
                "type": node["type"],
                "console": res.get("console"),
            }

            requests.post(
                f"{GNS3_URL}/projects/{pid}/nodes/{res['node_id']}/start",
                json={},
            )

            print(f"{node['name']} créé et démarré")

        time.sleep(5)

        adapter_map = {}
        links_ok = 0

        for link in topo.get("link_info", []):
            n1 = created.get(link.get("node1_id"))
            n2 = created.get(link.get("node2_id"))

            if n1 and n2:
                a1 = adapter_map.get(n1["name"], 0)
                a2 = adapter_map.get(n2["name"], 0)

                res = requests.post(
                    f"{GNS3_URL}/projects/{pid}/links",
                    json={
                        "nodes": [
                            {
                                "node_id": n1["node_id"],
                                "adapter_number": a1,
                                "port_number": 0,
                            },
                            {
                                "node_id": n2["node_id"],
                                "adapter_number": a2,
                                "port_number": 0,
                            },
                        ]
                    },
                )

                if res.status_code in [200, 201]:
                    links_ok += 1

                    if n1.get("node_type") == "dynamips" or "R" in n1.get("name", ""):
                        adapter_map[n1["name"]] = a1 + 1

                    if n2.get("node_type") == "dynamips" or "R" in n2.get("name", ""):
                        adapter_map[n2["name"]] = a2 + 1

                    print(
                        f"Lien: {n1['name']}(a={a1}) "
                        f"<-> {n2['name']}(a={a2})"
                    )

        missing = add_missing_links(pid, created, node_name_map)
        links_ok += missing

        if "R1" in node_name_map and node_name_map["R1"].get("console"):
            r1_port = node_name_map["R1"]["console"]

            print(f"\nConfiguration automatique R1 sur port {r1_port}...")
            force_configure_r1(r1_port)

        print(f"\nDéployé: {len(created)} noeuds, {links_ok} liens")

        return {
            "output": {
                "nodes_created": len(created),
                "links": [{"ok": True}] * links_ok,
                "project_name": "LLM-NetConf",
                "project_id": pid,
            }
        }

    except Exception as e:
        print(f"Erreur v7: {e}")

        return {
            "output": None,
            "error": str(e),
        }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)