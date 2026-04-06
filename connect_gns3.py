import requests
import json
import telnetlib
import time

GNS3_URL = "http://localhost:3080/v2"

# Etape 1 - Recuperer le projet
projects = requests.get(f"{GNS3_URL}/projects").json()
project = projects[0]
project_id = project["project_id"]
print(f"Projet trouve: {project['name']} (ID: {project_id})")

# Etape 2 - Recuperer les noeuds
nodes = requests.get(f"{GNS3_URL}/projects/{project_id}/nodes").json()
print(f"\nEquipements trouves:")
for node in nodes:
    print(f"  - {node['name']} (type: {node['node_type']}, console: {node.get('console', 'N/A')})")

# Etape 3 - Recuperer les liens
links = requests.get(f"{GNS3_URL}/projects/{project_id}/links").json()
print(f"\nNombre de liens: {len(links)}")

# Etape 4 - Construire la topologie JSON pour S-Witch
topology = {
    "node_info": [],
    "link_info": []
}

for node in nodes:
    ports = []
    for port in node.get("ports", []):
        ports.append({
            "name": port.get("name", ""),
            "port_number": port.get("port_number", 0),
            "link_type": "ethernet"
        })
    topology["node_info"].append({
        "node_id": node["node_id"],
        "name": node["name"],
        "node_type": node["node_type"],
        "console": node.get("console", None),
        "console_host": node.get("console_host", "127.0.0.1"),
        "ports": ports
    })

for link in links:
    topology["link_info"].append({
        "link_id": link["link_id"],
        "link_type": "ethernet",
        "nodes": [
            {"node_id": n["node_id"], "port_number": n.get("port_number", 0)}
            for n in link.get("nodes", [])
        ]
    })

print(f"\nTopologie JSON construite:")
print(json.dumps(topology, indent=2))

# Sauvegarde
with open("topology_live.json", "w") as f:
    json.dump(topology, f, indent=2)
print("\nTopologie sauvegardee dans topology_live.json")