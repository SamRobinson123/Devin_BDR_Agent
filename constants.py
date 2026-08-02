import sys
import os
from pydantic import BaseModel, Field
from typing import TypedDict, List, Union, Annotated, Sequence, Literal
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import ToolMessage
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.graph.message import add_messages
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt
from typing_extensions import TypedDict
from langgraph.types import interrupt
from dotenv import load_dotenv
from langgraph.graph import MessagesState
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.shared.context import RequestContext

## Load env
load_dotenv()

## define the model 
llm = ChatAnthropic(model="claude-sonnet-4-5",temperature=0,max_tokens=2048)