"""FastAPI web service exposing the agent at POST /chat."""

import logging
import os
import re
from contextlib import asynccontextmanager

import openai
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from agent import build_agent, create_llm
from mcp_client import load_mcp_tools

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("agent")

# Maximum graph steps per request; stops a model that keeps calling tools forever.
RECURSION_LIMIT = 25
# Some reasoning models wrap their private reasoning in <think> tags; users should not see it.
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(min_length=1, max_length=200)


class ChatResponse(BaseModel):
    response: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    tools, status = await load_mcp_tools(os.getenv("MCP_SERVERS_CONFIG", "mcp_config.json"))
    app.state.agent = build_agent(create_llm(), tools)
    app.state.mcp_status = status
    logger.info("Agent ready with %d tools: %s", len(tools), status)
    yield


app = FastAPI(title="CSCI 599 A1 MCP Agent", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"response": f"Invalid request: {error.errors()}"})


@app.get("/")
async def root() -> dict:
    """Landing page for people who open the service URL in a browser."""
    return {
        "service": "CSCI 599 A1 MCP agent",
        "status": "ok",
        "endpoints": {
            "POST /chat": 'body {"query": "...", "session_id": "..."} -> {"response": "..."}',
            "GET /health": "MCP servers and how many tools each one exposes",
            "GET /docs": "interactive API page where you can try POST /chat",
        },
    }


@app.get("/health")
async def health(request: Request) -> dict:
    return {"status": "ok", "mcp_servers": request.app.state.mcp_status}


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    # session_id becomes the LangGraph thread_id, so each session has its own memory.
    config = {"configurable": {"thread_id": body.session_id}, "recursion_limit": RECURSION_LIMIT}
    try:
        result = await request.app.state.agent.ainvoke(
            {"messages": [HumanMessage(body.query)]}, config=config
        )
    except GraphRecursionError:
        return ChatResponse(response="I needed too many steps for this request. Please try a simpler question.")
    except openai.RateLimitError:
        raise HTTPException(status_code=429, detail="The language model is rate limited. Please retry shortly.")
    except openai.APIError as error:
        logger.error("LLM API error: %s", error)
        raise HTTPException(status_code=502, detail="The language model service returned an error.")
    except Exception:
        logger.exception("Unexpected error while handling /chat")
        raise HTTPException(status_code=500, detail="Something went wrong while answering. Please try again.")

    answer = THINK_BLOCK.sub("", result["messages"][-1].text).strip()
    return ChatResponse(response=answer or "I could not produce an answer for that request.")


if __name__ == "__main__":
    # Cloud Run injects PORT at runtime; 8080 is only the local default.
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
