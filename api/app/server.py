import os
import json
import time
import socket
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

load_dotenv()

app = FastAPI(title="S-Witch Pro API", version="1.0.0")

GNS3_URL = os.getenv("GNS3_URL", "http://localhost:3080/v2")
OLLAMA_URL = "http://localhost:11434/api/chat"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_gns3_nodes():
    try:
        projs = requests.get(f"{GNS3_URL}/projects").json()
        if not projs: return {}
        pid = projs[0]["project_id"]
        nodes = requests.get(f"{GNS3_URL}/projects/{pid}/nodes").json()
        return {n["name"]: {"console": n.get("console"), "id": n["node_id"]} for n in nodes}
    except Exception as e:
        print(f"Erreur GNS3: {e}")
        return {}

def send_to_console(port, commands: str):
    if not port: return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
            s.settimeout(2)
            time.sleep(1)
            s.sendall(b"\n\nterminal length 0\n")
            time.sleep(0.5)
            try:
                while s.recv(4096): pass
            except socket.timeout:
                pass
            lines = commands.replace("\\n", "\n").split('\n')
            for line in lines:
                clean_line = line.strip()
                if clean_line:
                    s.sendall((clean_line + '\n').encode('ascii'))
                    wait_time = 0.6 if len(clean_line) > 40 else 0.3
                    time.sleep(wait_time)
            s.sendall(b"\nend\nwrite\n")
            time.sleep(1)
            return True
    except Exception as e:
        print(f"Erreur Console Port {port}: {e}")
        return False

def generate_config(topology, question):
    api_key = os.getenv("GROQ_API_KEY")
    model = "llama-3.3-70b-versatile" if api_key else "qwen2.5:7b"
    start_time = time.time()

    prompt = f"""You are a Network Automation Expert.
TOPOLOGY: {json.dumps(topology)}
USER REQUEST: {question}

STRICT OUTPUT RULES:
1. Return ONLY a JSON array of objects.
2. Format: {{"device": "string", "command": "string", "comment": "string"}}
3. For VPCS (PC1, PC2...): use 'ip 192.168.x.x/24 192.168.x.254'.
4. For Cisco (R1...): use 'enable', 'conf t', etc.
5. NO prose, NO markdown blocks, NO explanations.
6. Ensure EVERY device required for the connectivity is included.
7. Write COMPLETE commands, never truncate.

Example:
[
  {{"device": "PC1", "command": "ip 192.168.1.1/24 192.168.1.254", "comment": "IP PC1"}},
  {{"device": "PC2", "command": "ip 192.168.1.2/24 192.168.1.254", "comment": "IP PC2"}},
  {{"device": "R1", "command": "enable\\nconf t\\ninterface FastEthernet0/0\\nip address 192.168.1.254 255.255.255.0\\nno shutdown\\nend", "comment": "Gateway R1"}}
]"""

    try:
        if api_key:
            res = requests.post(GROQ_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
                timeout=30)
            content = res.json()['choices'][0]['message']['content']
        else:
            res = requests.post(OLLAMA_URL,
                json={
                    "model": model,
                    "stream": False,
                    "options": {
                        "num_predict": 1024,
                        "temperature": 0
                    },
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=60)
            content = res.json()['message']['content']

        elapsed = round(time.time() - start_time, 2)
        print(f"Temps de reponse LLM: {elapsed}s | Modele: {model}")

        start, end = content.find('['), content.rfind(']') + 1
        result = json.loads(content[start:end])
        print(f"Commandes generees: {len(result)} equipements")
        for r in result:
            print(f"  -> {r.get('device')}: {r.get('command', '')[:80]}")
        return result

    except Exception as e:
        print(f"Erreur LLM: {e}")
        return []

@app.post("/v4/invoke")
async def process_request(request: Request):
    data = await request.json()
    req_input = data.get("input", {})
    topology = req_input.get("topology", {})
    if isinstance(topology, str): topology = json.loads(topology)
    question = req_input.get("question", "")

    print(f"\n{'='*50}")
    print(f"Question: {question}")
    print(f"Topology: {len(topology.get('node_info', []))} equipements")

    configs = generate_config(topology, question)
    if not configs:
        return {"output": [], "error": "LLM failed to generate config"}

    node_map = get_gns3_nodes()
    applied_devices = []

    for item in configs:
        name = item.get("device")
        cmds = item.get("command")
        if name in node_map:
            print(f"Configuration de {name}...")
            success = send_to_console(node_map[name]["console"], cmds)
            item["status"] = "success" if success else "failed"
            if success: applied_devices.append(name)
        else:
            item["status"] = "node_not_found"

    print(f"Termine. Appareils configures: {', '.join(applied_devices)}")
    print(f"{'='*50}\n")
    return {"output": configs, "applied_to": applied_devices}

@app.post("/v5/invoke")
async def invoke_v5(request: Request):
    return await process_request(request)

@app.get("/")
def root():
    return {"message": "S-Witch API is running!", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "nodes": len(get_gns3_nodes())}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
