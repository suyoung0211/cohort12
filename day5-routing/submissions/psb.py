#기본 설정
import os
from dotenv import load_dotenv
load_dotenv()

#-------------------------------------
#모델 설정
#-------------------------------------
from langchain_google_genai import ChatGoogleGenerativeAI
llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

#-------------------------------------
#Routing (입력값 처리 후 컨텍스트별 작업으로 전달)
#-------------------------------------
from typing_extensions import Literal 
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

# DB 설정
from pymongo import MongoClient
MongoDB_URI = os.getenv("MONGODB_URI")
client = MongoClient(MongoDB_URI)
DB = client["brickers"]
collection = DB["ldraw_parts"]

# LLM이 반드시 step에 "technical"/"market"/"creative" 중 하나를 내게 강제.
class Route(BaseModel):
    step: Literal["technical", "market", "creative"] = Field(
        None, description="사용자의 주 목적을 분류합니다. 기술 관련은 technical, 가격/가치는 market, 활용법/아이디어는 creative 입니다"
    )


# 구조화 출력 강제된 라우터
router = llm.with_structured_output(Route)


# State
class State(TypedDict):
    input: str #사용자 입력
    decision: str #분기 결정
    output: str #출력


# Nodes
def technical_node(state: State):
    # 전문가 프롬프트 추가
    prompt = f"너는 레고 전문 엔지니어다. 다음 질문에 대해 크기, 내구성, 소재 등 기술적인 관점에서만 건조하게 답변해라: {state['input']}"

    result = llm.invoke(prompt)
    return {"output": result.content}


def market_node(state: State):   
    
    # 1. 사용자의 질문(input)을 검색 키워드로 사용
    keyword = state['input']
    
    # 2. DB 검색 수행 ($or 연산자로 이름이나 ID 검색)    
    db_results = list(collection.find(
        {
            "$or": [
                {"name": {"$regex": keyword, "$options": "i"}}, 
                {"partId": {"$regex": keyword, "$options": "i"}},
                {"category": {"$regex": keyword, "$options": "i"}} # 카테고리도 검색 추가
            ]
        }, 
        {"_id": 0, "partId": 1, "name": 1, "category": 1} # 가져올 필드
    ).limit(5)) # 최대 5개

    # 3. 검색 결과 유무에 따라 프롬프트 다르게 주기
    if db_results:        
        prompt = f"""
        너는 레고 시장 분석가다. 사용자가 '{keyword}'에 대해 묻고 있다.
        
        [DB 검색 결과]
        {str(db_results)}
        
        위 DB 데이터를 근거로 가격, 희귀도, 부품 정보를 분석해서 답변해라.
        """
    else:           
        prompt = f"너는 레고 시장 분석가다. '{keyword}'에 대한 DB 데이터가 없으므로, 네가 아는 일반적인 지식을 동원해 답변해라: {state['input']}"

    result = llm.invoke(prompt)
    return {"output": result.content}


def creative_node(state: State):
    # 전문가 프롬프트 추가
    prompt = f"너는 레고 아티스트다. 다음 질문에 대해 창의적인 아이디어, MOC 제작 팁, 디자인 영감을 주는 답변을 해라: {state['input']}"

    result = llm.invoke(prompt)
    return {"output": result.content}


# 라우터 노드
def llm_call_router(state: State):
    """Route the input to the appropriate node"""

    # Run the augmented LLM with structured output to serve as routing logic
    decision = router.invoke(
        [
            SystemMessage(
                content="사용자의 질문이 기술적인 내용인가, 가격/가치인가, 활용법/아이디어인가 technical/market/creative 중 어디에 가까운지 판단해라"
            ),
            HumanMessage(content=state["input"]),
        ]
    )
    print(f"Decision: {decision.step}")
    return {"decision": decision.step}


# Conditional edge function to route to the appropriate node
def route_decision(state: State):
    # Return the node name you want to visit next
    if state["decision"] == "technical":
        return "technical_node"
    elif state["decision"] == "market":
        return "market_node"
    elif state["decision"] == "creative":
        return "creative_node"


# Build workflow
router_builder = StateGraph(State)

# Add nodes
router_builder.add_node("technical_node", technical_node)
router_builder.add_node("market_node", market_node)
router_builder.add_node("creative_node", creative_node)
router_builder.add_node("llm_call_router", llm_call_router)

# Add edges to connect nodes
router_builder.add_edge(START, "llm_call_router")
router_builder.add_conditional_edges(
    "llm_call_router",
    route_decision,
    {  # Name returned by route_decision : Name of next node to visit
        "technical_node": "technical_node",
        "market_node": "market_node",
        "creative_node": "creative_node",
    },
)
router_builder.add_edge("technical_node", END)
router_builder.add_edge("market_node", END)
router_builder.add_edge("creative_node", END)

# Compile workflow
router_workflow = router_builder.compile()

# Show the workflow
print("Here is the mermaid graph syntax. You can paste it into https://mermaid.live/ :") #사이트 들어가서 코드 붙여넣기
print(router_workflow.get_graph(xray=True).draw_mermaid())

# Invoke
answer = router_workflow.invoke({"input": "slope 의 가격은 얼마인가?"})
print(f"\nAnswer: {answer}")