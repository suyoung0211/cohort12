import operator
from typing import Annotated, List, Literal
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from pydantic import BaseModel, Field

# 환경 변수 로드
load_dotenv()

# 모델 설정
llm = ChatAnthropic(model="claude-haiku-4-5-20251001")

# 설정값
MIN_LENGTH = 100  # 검증 기준
MAX_RETRIES = 3   # 최대 재시도 횟수

# --- 1. 스키마 및 상태 정의 ---

class DayPlan(BaseModel):
    day: str = Field(description="일차 (예: Day 1)")
    theme: str = Field(description="테마")
    description: str = Field(description="설명")

class TravelPlan(BaseModel):
    itinerary: List[DayPlan] = Field(description="일정 목록")

planner = llm.with_structured_output(TravelPlan)

class State(TypedDict):
    topic: str
    itinerary: list[DayPlan]
    # 여러 워커의 결과물을 안전하게 합치기 위한 reducer
    completed_days: Annotated[list, operator.add] 
    final_guidebook: str

class WorkerState(TypedDict):
    day_plan: DayPlan

# --- 2. 노드 로직 ---

def orchestrator(state: State):
    """기획 노드"""
    print(f"\n[PLANNER] '{state['topic']}' 여행 계획 수립 중...")
    plan = planner.invoke([
        SystemMessage(content="여행 계획을 세우세요. 최소 2개 이상의 일정이 포함되어야 합니다."),
        HumanMessage(content=state['topic'])
    ])
    print(f"[PLANNER] 총 {len(plan.itinerary)}일 일정 생성 완료.")
    return {"itinerary": plan.itinerary}

def check_plan_quality(state: State) -> Literal["assign", "orchestrator"]:
    if len(state["itinerary"]) < 2:
        print(f"🚨 [PLAN RETRY] 일정이 너무 적음. 다시 기획합니다.")
        return "orchestrator"
    return "assign"

def llm_call(state: WorkerState):
    """워커 노드: 내부 루프를 통해 3회까지 재시도"""
    day_info = state['day_plan']
    final_content = ""
    
    # 🌟 횟수 제한 루프 (최대 3회)
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"🔄 [WORKER] {day_info.day} 작성 중... (시도 {attempt}/{MAX_RETRIES})")
        
        response = llm.invoke([
            SystemMessage(content=f"상세 일정을 마크다운으로 작성하세요. 내용은 반드시 {MIN_LENGTH}자 이상이어야 합니다."),
            HumanMessage(content=f"{day_info.day}: {day_info.theme}")
        ])
        
        content = response.content
        current_len = len(content)
        
        if current_len >= 800:
            print(f"✅ [WORKER DONE] {day_info.day}: {current_len}자 작성 완료 (통과)")
            final_content = content
            break
        else:
            if attempt < MAX_RETRIES:
                print(f"❌ [WORKER RETRY] {day_info.day}: {current_len}자 (기준 미달)")
            else:
                print(f"⚠️ [WORKER FAIL] {day_info.day}: 최종 {current_len}자 (최대 시도 횟수 초과)")
                final_content = content + "\n\n(참고: 분량 미달로 재작성된 내용입니다.)"

    # 성공하든 실패하든 마지막 결과물을 completed_days 리스트에 추가
    return {"completed_days": [final_content]}

def synthesizer(state: State):
    """최종 합치기"""
    # 데이터가 섞이지 않았는지 확인하기 위해 각 섹션 길이 출력
    section_lengths = [len(s) for s in state["completed_days"]]
    print(f"\n[SYNTHESIZER] 취합 시작. 각 섹션 길이: {section_lengths}")
    
    full_guide = "\n\n---\n\n".join(state["completed_days"])
    return {"final_guidebook": full_guide}

def assign_workers(state: State):
    """동적 할당"""
    print(f"[DISPATCH] {len(state['itinerary'])}명의 워커에게 작업 할당...")
    return [Send("llm_call", {"day_plan": d}) for d in state["itinerary"]]

# --- 3. 그래프 구축 ---

builder = StateGraph(State)

builder.add_node("orchestrator", orchestrator)
builder.add_node("llm_call", llm_call)
builder.add_node("synthesizer", synthesizer)

builder.add_edge(START, "orchestrator")

# 기획 검증 루프
builder.add_conditional_edges("orchestrator", check_plan_quality, {
    "orchestrator": "orchestrator",
    "assign": "assign_workers_trigger"
})

# 브릿지 노드 (Send API 호출용)
def bridge_node(state: State): return state
builder.add_node("assign_workers_trigger", bridge_node)
builder.add_conditional_edges("assign_workers_trigger", assign_workers, ["llm_call"])

# 🌟 중요: 이제 llm_call에서 직접 synthesizer로 갑니다 (데이터 충돌 방지)
builder.add_edge("llm_call", "synthesizer")
builder.add_edge("synthesizer", END)

graph = builder.compile()

# --- 4. 시각화 및 실행 ---

print("\n" + "="*50)
print("👀 워크플로우 시각화 (Mermaid Syntax)")
print(graph.get_graph(xray=True).draw_mermaid())
print("="*50 + "\n")

result = graph.invoke({"topic": "도쿄 2박 3일 미식 여행 간단하게 작성"})

print("\n" + "="*50)
print(f"🏁 [최종 결과]")
print(f"- 총 글자 수: {len(result['final_guidebook'])}자")
print(f"- 포함된 일정 수: {len(result['completed_days'])}일")
print("="*50)