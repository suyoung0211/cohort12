import os
from typing import Literal
from typing_extensions import TypedDict
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

load_dotenv()

# 1. 모델 설정
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")

# 2. 구조화된 출력 (Router용)
class Route(BaseModel):
    step: Literal["poem", "story", "joke"] = Field(
        description="유저의 입력에 대해 poem, story, joke 중 하나를 선택하여라"
    )

router = llm.with_structured_output(Route)

# 3. State 정의 (feedback 추가)
class State(TypedDict):
    input: str     # 초기 입력 및 누적된 입력
    decision: str  # 결정된 경로
    output: str    # LLM의 답변
    feedback: str  # 사용자의 검토 내용

# 4. Nodes 정의
def llm_call_router(state: State):
    """사용자의 의도를 파악하여 분기 결정"""
    decision = router.invoke([
        SystemMessage(content="유저의 입력에 대해 poem, story, joke 중 하나를 선택하세요."),
        HumanMessage(content=state["input"]),
    ])
    print(f"\n[Decision]: {decision.step}")
    return {"decision": decision.step}

def llm_call_story(state: State):
    system_prompt = "당신은 매혹적인 소설가입니다. 풍부한 묘사가 담긴 짧은 이야기를 쓰세요."
    result = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=state["input"])])
    return {"output": result.content}

def llm_call_joke(state: State):
    system_prompt = "당신은 재치 있는 코미디언입니다. 반전이 있는 짧은 농담을 하세요."
    result = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=state["input"])])
    return {"output": result.content}

def llm_call_poem(state: State):
    system_prompt = "당신은 감성적인 시인입니다. 아름다운 운율의 시를 쓰세요."
    result = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=state["input"])])
    return {"output": result.content}

def human_review_node(state: State):
    """사용자에게 결과를 보여주고 피드백을 받음"""
    print(f"\n=== AI 결과 ===\n{state['output']}\n===============")
    feedback = input("\n결과가 마음에 드시나요? (만족하면 'ok', 수정이 필요하면 요청사항 입력): ")

    # 수정이 필요한 경우, 기존 input에 피드백을 더해 문맥 유지
    if feedback.lower() != "ok":
        new_input = f"이전 요청: {state['input']}\n사용자 피드백: {feedback}"
        return {"feedback": feedback, "input": new_input}

    return {"feedback": feedback}

# 5. Conditional Edge 로직
def route_decision(state: State):
    if state["decision"] == "story": return "llm_call_1"
    if state["decision"] == "joke": return "llm_call_2"
    return "llm_call_3"

def should_continue(state: State):
    if state["feedback"].lower() == "ok":
        return END
    return "llm_call_router"

# 6. Workflow 구축
builder = StateGraph(State)

builder.add_node("llm_call_router", llm_call_router)
builder.add_node("llm_call_1", llm_call_story)
builder.add_node("llm_call_2", llm_call_joke)
builder.add_node("llm_call_3", llm_call_poem)
builder.add_node("human_review", human_review_node)

builder.add_edge(START, "llm_call_router")
builder.add_conditional_edges(
    "llm_call_router",
    route_decision,
    {"llm_call_1": "llm_call_1", "llm_call_2": "llm_call_2", "llm_call_3": "llm_call_3"}
)

builder.add_edge("llm_call_1", "human_review")
builder.add_edge("llm_call_2", "human_review")
builder.add_edge("llm_call_3", "human_review")

builder.add_conditional_edges(
    "human_review",
    should_continue,
    {END: END, "llm_call_router": "llm_call_router"}
)

# 7. 실행
graph = builder.compile()
graph.invoke({"input": "고양이에 대한 짧은 농담을 해줘."})