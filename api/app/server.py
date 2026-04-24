from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import json, requests, socket, time, os

load_dotenv()

app = FastAPI(title="S-Witch API Server", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GNS3_URL = "http://localhost:3080/v2"

def ask_llm(topology, question):
    groq_key = os.getenv("GROQ_API_KEY")
    prompt = f"""You are a Cisco IOS expert.
Network topology: {json.dumps(topology)}
Task: {question}

Rules:
- For VPCS nodes: use format "ip X.X.X.X/mask gateway"
- For block traffic: use access-list deny commands on R1
- For OSPF: use router ospf commands
- For show commands: use show IOS commands
- Each device appears ONCE only

Output ONLY a valid JSON array:
[
  {{"device": "PC1", "command": "ip 192.168.1.1/24 192.168.1.254", "comment": "Configure PC1"}},
  {{"device": "R1", "command": "enable\\nconfigure terminal\\naccess-list 1 deny 192.168.1.1\\ninterface f0/0\\nip access-group 1 in\\nend", "comment": "Block PC1"}}
]
No explanation. Only JSON array."""

    try:
        if groq_key:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}"},
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0},
                timeout=30
            )
            content = response.json()['choices'][0]['message']['content']
        else:
            response = requests.post(
                "http://localhost:11434/api/chat",
                json={"model": "qwen2.5:7b", "stream": False, "messages": [{"role": "user", "content": prompt}]},
                timeout=60
            )
            content = response.json()['message']['content']

        start = content.find('[')
        end = content.rfind(']') + 1
        if start != -1 and end > start:
            return json.loads(content[start:end])
    except Exception as e:
        print(f"LLM error: {e}")
    return []

def get_gns3_nodes():
    try:
        projects = requests.get(f"{GNS3_URL}/projects").json()
        if not projects:
            return {}
        project_id = projects[0]["project_id"]
        nodes = requests.get(f"{GNS3_URL}/projects/{project_id}/nodes").json()
        return {n["name"]: {"console": n.get("console"), "host": "127.0.0.1"} for n in nodes}
    except:
        return {}

def apply_command(host, port, command):
    try:
        s = socket.socket()
        s.connect((host, port))
        s.settimeout(5)
        time.sleep(1)
        try:
            s.recv(1024)
        except:
            pass
        for cmd in command.replace("\\n", "\n").split("\n"):
            if cmd.strip():
                s.send((cmd + "\n").encode())
                time.sleep(0.3)
        time.sleep(1)
        try:
            output = s.recv(4096).decode(errors="ignore")
        except:
            output = ""
        s.close()
        return True, output
    except Exception as e:
        return False, str(e)

@app.get("/")
async def root():
    return {"message": "S-Witch API is running!", "version": "0.1.0"}

@app.post("/v4/invoke")
async def invoke_v4(request: dict):
    try:
        req = request.get("input", {})
        topology = json.loads(req.get("topology", "{}"))
        question = req.get("question", "")
        print(f"Question reçue: {question}")
        print(f"Topology nodes: {len(topology.get('node_info', []))}")
        results = ask_llm(topology, question)
        print(f"Résultats LLM: {results}")
        node_map = get_gns3_nodes()
        applied = []
        for result in results:
            device = result.get("device", "")
            command = result.get("command", "")
            if device and command and device in node_map:
                node = node_map[device]
                if node.get("console"):
                    success, _ = apply_command("127.0.0.1", node["console"], command)
                    result["applied"] = success
                    if success:
                        applied.append(device)
        return {"output": results, "applied_to": applied}
    except Exception as e:
        return {"output": [], "error": str(e)}

@app.post("/v5/invoke")
async def invoke_v5(request: dict):
    return await invoke_v4(request)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
