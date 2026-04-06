from typing import List, Tuple
from pydantic import BaseModel, Field
from langchain_core.output_parsers import JsonOutputParser

class ChatRequest(BaseModel):
    chat_history: List[Tuple[str, str]] = Field(default=[])
    topology: str
    question: str

class ChatRequestWrapper(BaseModel):
    input: ChatRequest
    config: dict = Field(default={})
    kwargs: dict = Field(default={})

class ChatResponse(BaseModel):
    device: str = Field(description="The device name.")
    command: str = Field(description="CLI Command for the device.")
    comment: str = Field(description="Description of the command.")

output_parser = JsonOutputParser(pydantic_object=ChatResponse)

class PortIdentification(BaseModel):
    device: str = Field(description="The device name.")
    port: str = Field(description="The port name.")
    ip: str = Field(description="The ip address.")
    subnet: str = Field(description="The subnet mask.")

class PortIdentificationWrapper(BaseModel):
    port_info: List[PortIdentification] = Field(description="Port identification result.")

port_identification_parser = JsonOutputParser(pydantic_object=PortIdentificationWrapper)

class NetworkTopology(BaseModel):
    node_info: List[dict] = Field(description="Device information.")
    link_info: List[dict] = Field(description="Link information.")

network_topology_parser = JsonOutputParser(pydantic_object=NetworkTopology)