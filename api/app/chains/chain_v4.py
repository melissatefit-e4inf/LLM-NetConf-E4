#! python
from operator import itemgetter
from typing import List, Tuple
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from dotenv import load_dotenv; load_dotenv()
from api.app.utils import output_parser, network_topology_parser

_TEMPLATE_FOR_ALLOCATE_IP = """I have the following Network Topology.
- Network Topology: {network_topology}
- Previous Chatting History: {chat_history}
- Current question: {question}
Can you allocate IP addresses and subnet masks to each device's port?
{format_instructions}
- Network Topology:"""

PROMPT_FOR_ALLOCATE_IP = PromptTemplate.from_template(
    _TEMPLATE_FOR_ALLOCATE_IP,
    partial_variables={"format_instructions": network_topology_parser.get_format_instructions()}
)

_TEMPLATE_FOR_ANSWER = """I have the following Network Topology.
- Network Topology: {network_topology}
- Previous Chatting History: {chat_history}
- Current question: {question}
{format_instructions}
{output_examples}"""

PROMPT_FOR_ANSWER = PromptTemplate.from_template(
    _TEMPLATE_FOR_ANSWER,
    partial_variables={
        "format_instructions": output_parser.get_format_instructions(),
        "output_examples": """Output Examples:
- {"device": "R1", "command": "enable\nconfigure terminal\ninterface GigabitEthernet0/0\nip address 192.168.0.1\nno shutdown\nexit", "comment": "set ip on R1"}
- {"device": "PC1", "command": "ip 192.168.0.2 /24 192.168.0.1", "comment": "Configure PC1 ip address"}"""
    }
)

def _format_chat_history(chat_history: List[Tuple]) -> str:
    buffer = ""
    for dialogue_turn in chat_history:
        human = "Human: " + dialogue_turn[0]
        ai = "Assistant: " + dialogue_turn[1]
        buffer += "\n" + "\n".join([human, ai])
    if buffer == "":
        buffer = "None"
    return buffer

from langchain_groq import ChatGroq
import os
groq_model = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0
)

chain = (
    {
        "network_topology": {
            "network_topology": itemgetter("topology"),
            "chat_history": itemgetter("chat_history") | RunnableLambda(_format_chat_history),
            "question": itemgetter("question"),
        } | PROMPT_FOR_ALLOCATE_IP | groq_model | network_topology_parser,
        "chat_history": itemgetter("chat_history") | RunnableLambda(_format_chat_history),
        "question": itemgetter("question"),
    }
    | PROMPT_FOR_ANSWER
    | groq_model
    | output_parser
)

first_chain = (
    {
        "network_topology": itemgetter("topology"),
        "chat_history": itemgetter("chat_history") | RunnableLambda(_format_chat_history),
        "question": itemgetter("question"),
    }
    | PROMPT_FOR_ALLOCATE_IP
    | groq_model
    | network_topology_parser
)

second_chain = (
    {
        "network_topology": itemgetter("topology"),
        "chat_history": itemgetter("chat_history") | RunnableLambda(_format_chat_history),
        "question": itemgetter("question"),
    }
    | PROMPT_FOR_ANSWER
    | groq_model
    | output_parser
)