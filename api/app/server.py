from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import json
import asyncio

load_dotenv()

from api.app.utils import ChatRequest, ChatRequestWrapper
from api.app.chains.chain_v4 import chain as chain_v4
from api.app.chains.chain_v4 import first_chain as first_chain_v4, second_chain as second_chain_v4
from api.app.chains.chain_v5 import invoke as chain_v5_invoke

app = FastAPI(
    title="S-Witch API Server",
    version="0.1.0",
    description="S-Witch LLM Network Configuration Assistant",
)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "S-Witch API is running!", "version": "0.1.0"}

@app.post("/v4/invoke")
async def invoke_v4(request: ChatRequestWrapper):
    req = request.input
    topology = json.loads(req.topology)
    node_info = topology["node_info"]
    
    first_output = first_chain_v4.invoke(req.dict())
    req_dict = req.dict()
    req_dict["topology"] = first_output
    
    async_list = []
    for node in node_info:
        node_request = req_dict.copy()
        node_request["question"] += f" Configure device {node['name']}."
        async_list.append(second_chain_v4.ainvoke(node_request))
    
    results = await asyncio.gather(*async_list)
    return {"output": results}

@app.post("/v5/invoke")
async def invoke_v5(request: ChatRequestWrapper):
    req = request.input
    output = await chain_v5_invoke(req)
    return {"output": output}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)