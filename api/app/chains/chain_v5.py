# 0. Setup
import os
import asyncio
import json
from dotenv import load_dotenv

# Charge les variables du fichier .env (GOOGLE_API_KEY)
load_dotenv()

# 1. Create Templates

INSTRUCTION = """You are a network operator, and I will request network configuration from you through chat. 
In the request process, I will convey the network topology, the content of the conversation so far, and my requirements. 
To process the request, you will follow the process in four steps.

- In the first stage, the previous conversation is received as input and goes through a process of summarizing it. If there is no conversation content, the step is skipped.
- In the second stage, For a given network topology, provide an overall design(blueprint) that can meet the requirements without adding links or new devices. For example, determine routing protocol, Access List, VLAN allocation, etc.
- In step 3, the task of assigning an IP address and subnet mask to every connected port of the topology is performed according to the overall design.
- In step 4, the task of creating a CLI command for each device is performed.
"""

FIRST_STEP_TEMPLATE = INSTRUCTION + '\n' + """You are currently in stage 1.
If the content of a previous conversation is as follows, summarize the content in one paragraph.
- Previous conversation: {prev_conversation}"""

SECOND_STEP_TEMPLATE = INSTRUCTION + '\n' + """You are currently in stage 2.
A summary of the previous conversation follows:
- Summary of previous conversation: {prev_conversation_summary}
The current network topology is as follows.
- network topology : {network_topology}
Currently my requirements are:
- Current conversation content: {question}
At this time, please suggest how to design the overall network."""

THIRD_STEP_TEMPLATE = INSTRUCTION + '\n' + """You are currently in stage 3.
Details on the overall network design are as follows.
- Network design: {design_of_network}
The current network topology is as follows.
- network topology : {network_topology}
Assign an appropriate IP address and subnet mask to the every connected port of each device.
{format_instructions}"""

FOURTH_STEP_TEMPLATE = INSTRUCTION + '\n' + """You are currently in stage 4.
Details on the overall network design are as follows.
- Network design: {design_of_network}
The current network topology is as follows.
- network topology: {network_topology}
- ip address / subnet mask : {port_identification}
The node_name that you need to configure is {device_name}.
Create a CLI command according to the above design. In this step, you should assign the ip address and subnet mask to the every port of the device.
{format_instructions}
{example_command}"""

OUTPUT_EXAMPLE_COMMAND = """Below are examples of creation.
- {"device": "R1", "command": "enable\\nconfigure terminal\\ninterface GigabitEthernet1/0\\nip address 192.168.1.1 255.255.255.0\\nno shutdown\\nexit", "comment": "set ip"}
- {"device": "PC1", "command": "ip 192.168.1.2 /24 192.168.1.1", "comment": "configure PC1"}
"""

# 2. Create Prompt
from langchain_core.prompts import PromptTemplate
from api.app.utils import output_parser, port_identification_parser, ChatRequest

first_step_prompt = PromptTemplate.from_template(FIRST_STEP_TEMPLATE)
second_step_prompt = PromptTemplate.from_template(SECOND_STEP_TEMPLATE)
third_step_prompt = PromptTemplate.from_template(THIRD_STEP_TEMPLATE, partial_variables={"format_instructions": port_identification_parser.get_format_instructions()})
forth_step_prompt = PromptTemplate.from_template(FOURTH_STEP_TEMPLATE, partial_variables={"format_instructions": output_parser.get_format_instructions(), "example_command": OUTPUT_EXAMPLE_COMMAND})

# 3. Create Chain ( Implementation)
from langchain_core.output_parsers import StrOutputParser

from langchain_groq import ChatGroq

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0
)

first_step_chain = first_step_prompt | llm | StrOutputParser()
second_step_chain = second_step_prompt | llm | StrOutputParser()
third_step_chain = third_step_prompt | llm | port_identification_parser
fourth_step_chain = forth_step_prompt | llm | output_parser

# 4. Create Invoke Function

async def invoke(input: ChatRequest):
    # Etape 1 : Résumé
    if len(input.chat_history) != 0:
        prev_conversation_summary = await first_step_chain.ainvoke({ "prev_conversation": input.chat_history })
    else:
        prev_conversation_summary = "It does not exist."
    
    # Etape 2 : Design
    topology_data = json.loads(input.topology)
    design_of_network = await second_step_chain.ainvoke({ 
        "prev_conversation_summary": prev_conversation_summary, 
        "network_topology": topology_data, 
        "question": input.question 
    })
    
    # Etape 3 : IPs
    port_identification = await third_step_chain.ainvoke({ 
        "design_of_network": design_of_network, 
        "network_topology": topology_data 
    })
    
    # Etape 4 : CLI Commands (Parallélisé)
    node_info = topology_data["node_info"]
    tasks = []
    for node in node_info:
        tasks.append(fourth_step_chain.ainvoke({ 
            "design_of_network": design_of_network, 
            "network_topology": topology_data, 
            "port_identification": port_identification, 
            "device_name": node["name"] 
        }))
    
    results = await asyncio.gather(*tasks)
    print(json.dumps(results, indent=2))
    return results

# 5. Test
DUMMY_INPUT_1 = ChatRequest(
    chat_history = [],
    topology = json.dumps({"node_info":[{"name":"PC1"},{"name":"PC2"},{"name":"R1"}],"link_info":[]}), # Simplifié pour le test
    question = "Configure a basic network between PC1 and PC2 via R1."
)

if __name__ == "__main__":
    if not os.getenv("GROQ_API_KEY"):
        print("ERREUR : GROQ_API_KEY non trouvée.")
    else:
        asyncio.run(invoke(DUMMY_INPUT_1))