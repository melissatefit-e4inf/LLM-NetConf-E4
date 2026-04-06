import sys
sys.path.append('.')
from dotenv import load_dotenv
load_dotenv()
from api.app.chains.chain_v4 import chain

topology = {
    "link_info": [
        {"link_id": "link-1", "link_type": "ethernet", "nodes": [
            {"node_id": "pc1", "port_number": 0},
            {"node_id": "switch1", "port_number": 0}
        ]},
        {"link_id": "link-2", "link_type": "ethernet", "nodes": [
            {"node_id": "pc2", "port_number": 0},
            {"node_id": "switch1", "port_number": 1}
        ]},
        {"link_id": "link-3", "link_type": "ethernet", "nodes": [
            {"node_id": "r1", "port_number": 0},
            {"node_id": "switch1", "port_number": 2}
        ]}
    ],
    "node_info": [
        {"node_id": "pc1", "name": "PC1", "node_type": "vpcs",
         "ports": [{"name": "Ethernet0", "port_number": 0, "link_type": "ethernet"}]},
        {"node_id": "pc2", "name": "PC2", "node_type": "vpcs",
         "ports": [{"name": "Ethernet0", "port_number": 0, "link_type": "ethernet"}]},
        {"node_id": "r1", "name": "R1", "node_type": "dynamips",
         "ports": [{"name": "FastEthernet0/0", "port_number": 0, "link_type": "ethernet"}]},
        {"node_id": "switch1", "name": "Switch1", "node_type": "ethernet_switch",
         "ports": [
             {"name": "Ethernet0", "port_number": 0, "link_type": "ethernet"},
             {"name": "Ethernet1", "port_number": 1, "link_type": "ethernet"},
             {"name": "Ethernet2", "port_number": 2, "link_type": "ethernet"}
         ]}
    ]
}

questions = [
    "Configure all PCs to ping each other",
    "Block traffic from PC1 to PC2",
    "Configure OSPF on R1",
]

print("Test chain_v4 avec Groq")
print("="*50)

for q in questions:
    print(f"\nQuestion: {q}")
    print("-"*40)
    result = chain.invoke({
        "topology": topology,
        "chat_history": [],
        "question": q
    })
    print(result)

print("\n" + "="*50)
print("Termine!")