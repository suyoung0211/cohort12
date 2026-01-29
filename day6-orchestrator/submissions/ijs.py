import os
import operator
from typing import Annotated, List, Literal, Union
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 1. 환경 설정 및 모델 로드
load_dotenv()
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
# gemini-2.5-flash 고정
# 모델 설정 부분에 'max_retries' 추가
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    max_retries=5,  # 할당량 초과 시 자동으로 다시 시도하는 횟수
)

# 2. 스키마 정의
class Section(BaseModel):
    name: str = Field(description="섹션 제목")
    description: str = Field(description="섹션 설명")

class Sections(BaseModel):
    sections: List[Section]

class ReviewResult(BaseModel):
    is_approved: bool = Field(description="승인 여부")
    feedback: str = Field(description="피드백 내용")

planner = llm.with_structured_output(Sections)
reviewer_llm = llm.with_structured_output(ReviewResult)

# 3. 상태 정의 수정
class State(TypedDict):
    topic: str
    sections: list[Section]
    # 메인 State에는 합쳐질 결과 리스트만 둡니다.
    completed_sections: Annotated[list, operator.add]
    final_report: str

# 워커 전용 상태: 메인 State와 분리하여 설계
class WorkerState(TypedDict):
    section: Section
    # 아래 키들은 메인 State에 존재하지 않으므로 병렬 충돌이 나지 않습니다.
    worker_content: str
    worker_feedback: str
    worker_review_count: int
    worker_is_approved: bool

# 4. 노드 함수 정의
def orchestrator(state: State):
    """오케스트레이터: 토픽을 기반으로 섹션 계획"""
    res = planner.invoke([
        SystemMessage(content="보고서 구조 기획 전문가입니다. 주어진 주제에 대해 적절한 섹션들을 계획하세요."),
        HumanMessage(content=f"주제: {state['topic']}\n\n이 주제에 대한 보고서 섹션들을 계획해주세요.")
    ])
    print(f"[ORCHESTRATOR] 계획된 섹션: {[s.name for s in res.sections]}")
    return {"sections": res.sections}

def llm_call(state: WorkerState):
    """작성 및 재작성"""
    f_back = f"\n이전 피드백: {state.get('worker_feedback', '')}" if state.get('worker_feedback') else ""

    res = llm.invoke([
        SystemMessage(content="보고서 작성 전문가입니다. 본문만 마크다운으로 작성하세요."),
        HumanMessage(content=f"제목: {state['section'].name}\n설명: {state['section'].description}{f_back}")
    ])

    print(f"[WORKER] 작성 완료: {state['section'].name} (시도 {state.get('worker_review_count', 0) + 1}회)")

    # 키 이름을 worker_content 등으로 변경
    return {
        "worker_content": res.content,
        "worker_review_count": state.get("worker_review_count", 0) + 1
    }

def reviewer(state: WorkerState):
    """품질 검수"""
    res = reviewer_llm.invoke([
        SystemMessage(content="품질 검수자입니다. 부실하면 반려하세요."),
        HumanMessage(content=f"섹션: {state['section'].name}\n내용: {state['worker_content']}")
    ])
    return {"worker_is_approved": res.is_approved, "worker_feedback": res.feedback}

def synthesizer_bridge(state: WorkerState):
    # 워커의 최종 결과물만 메인 State의 completed_sections(Annotated)로 보냄
    return {"completed_sections": [state["worker_content"]]}

def synthesizer(state: State):
    """합성기: 모든 섹션을 합쳐서 최종 보고서 생성"""
    completed = state.get("completed_sections", [])
    final_report = "\n\n---\n\n".join(completed)
    print(f"[SYNTHESIZER] {len(completed)}개 섹션을 합쳐 최종 보고서 생성")
    return {"final_report": final_report}

# 5. 제어 로직 수정
def assign_workers(state: State):
    return [Send("llm_call", {
        "section": s,
        "worker_review_count": 0,
        "worker_content": "",
        "worker_feedback": ""
    }) for s in state["sections"]]

def check_review(state: WorkerState) -> Literal["llm_call", "synthesizer_bridge"]:
    if state.get("worker_is_approved") or state.get("worker_review_count", 0) >= 2:
        return "synthesizer_bridge"

    print(f"  [X] {state['section'].name}: 반려됨 -> 재작성 시작")
    return "llm_call"

# 6. 빌드 및 컴파일
builder = StateGraph(State)

builder.add_node("orchestrator", orchestrator)
builder.add_node("llm_call", llm_call)
builder.add_node("reviewer", reviewer)
builder.add_node("synthesizer_bridge", synthesizer_bridge)
builder.add_node("synthesizer", synthesizer)

builder.add_edge(START, "orchestrator")
builder.add_conditional_edges("orchestrator", assign_workers, ["llm_call"])

# 워커 루프: 작성 -> 검수 -> (재작성 OR 브릿지)
builder.add_edge("llm_call", "reviewer")
builder.add_conditional_edges("reviewer", check_review, ["llm_call", "synthesizer_bridge"])

builder.add_edge("synthesizer_bridge", "synthesizer")
builder.add_edge("synthesizer", END)

app = builder.compile()

# 실행
if __name__ == "__main__":
    config = {"topic": "LLM 스케일링 법칙에 관한 보고서 짧게 작성"}
    result = app.invoke(config)
    print("\n" + "="*50)
    print("최종 보고서 결과")
    print("="*50 + "\n")
    print(result["final_report"])