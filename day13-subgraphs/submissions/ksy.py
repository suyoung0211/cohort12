from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

# --- Subgraph: 환불 계산기 ---
class RefundState(TypedDict):
    # 부모와 상관없는 독자적 스키마
    raw_amount: int
    fee_rate: float
    final_refund: int

def calculate_fee(state: RefundState):
    return {"final_refund": int(state["raw_amount"] * (1 - state["fee_rate"]))}

sub_builder = StateGraph(RefundState)
sub_builder.add_node("calculate_fee", calculate_fee)
sub_builder.add_edge(START, "calculate_fee")
refund_subgraph = sub_builder.compile()

# --- Parent Graph: 고객 서비스 ---
class SupportState(TypedDict):
    customer_name: str
    order_value: int
    status: str

def initiate_support(state: SupportState):
    print(f"--- {state['customer_name']}님의 요청 분석 중 ---")
    return {"status": "processing"}

def call_refund_subgraph(state: SupportState):
    # [핵심] 부모 State -> 자식 State로 수동 변환하여 invoke
    # 환불 수수료 10%(0.1) 적용 시나리오
    response = refund_subgraph.invoke({
        "raw_amount": state["order_value"],
        "fee_rate": 0.1
    })
    
    # [핵심] 자식 결과 -> 부모 State로 수동 업데이트
    return {"status": f"환불 완료: {response['final_refund']}원"}

builder = StateGraph(SupportState)
builder.add_node("initiate", initiate_support)
builder.add_node("refund_process", call_refund_subgraph)
builder.add_edge(START, "initiate")
builder.add_edge("initiate", "refund_process")
graph = builder.compile()

# 실행
for chunk in graph.stream({"customer_name": "김철수", "order_value": 100000}, subgraphs=True):
    print(chunk)

from typing import Annotated
import operator
from typing_extensions import TypedDict

# 공유되는 상태 구조
class SharedState(TypedDict):
    # Annotated와 operator.add를 사용하면 리스트가 교체되지 않고 '추가'됨
    history: Annotated[list[str], operator.add]
    internal_notes: str # 서브그래프에서만 쓸 키

# --- Subgraph: 기술 지원 팀 ---
def tech_analysis(state: SharedState):
    # 부모와 공유하는 history에 내용 추가
    return {
        "history": ["기술 팀: 하드웨어 결함 확인됨"],
        "internal_notes": "로그 분석 결과 전원부 이상"
    }

tech_builder = StateGraph(SharedState)
tech_builder.add_node("tech_analysis", tech_analysis)
tech_builder.add_edge(START, "tech_analysis")
tech_subgraph = tech_builder.compile()

# --- Parent Graph: 통합 관제 ---
class ParentState(TypedDict):
    history: Annotated[list[str], operator.add]
    priority: str

def initial_triage(state: ParentState):
    return {"history": ["상담원: 기술 지원 요청 접수"], "priority": "High"}

builder = StateGraph(ParentState)
builder.add_node("triage", initial_triage)
# [핵심] 컴파일된 그래프를 노드로 직접 추가
builder.add_node("tech_team", tech_subgraph) 

builder.add_edge(START, "triage")
builder.add_edge("triage", "tech_team")
graph = builder.compile()

# 실행 결과 확인 (internal_notes는 부모 최종 state에 남지 않거나 무시됨)
for chunk in graph.stream({"history": ["고객: 화면이 안 나와요"]}, subgraphs=True):
    print(chunk)

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command

class TaskState(TypedDict):
    task_name: str
    is_approved: bool

# --- Subgraph: 승인 프로세스 ---
def ask_approval(state: TaskState):
    print(f"--- '{state['task_name']}' 승인 대기 중 ---")
    # 여기서 멈춤
    user_input = interrupt("이 작업을 승인하시겠습니까? (yes/no)")
    return {"is_approved": user_input == "yes"}

sub_builder = StateGraph(TaskState)
sub_builder.add_node("ask_approval", ask_approval)
sub_builder.add_edge(START, "ask_approval")
approval_subgraph = sub_builder.compile()

# --- Parent Graph ---
builder = StateGraph(TaskState)
builder.add_node("process", approval_subgraph)
builder.add_edge(START, "process")

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "step_123"}}

# 1. 실행 시작 (interrupt에서 멈춤)
graph.invoke({"task_name": "서버 재부팅", "is_approved": False}, config)

# 2. 서브그래프 상태 들여다보기
full_state = graph.get_state(config, subgraphs=True)
# tasks[0]에 현재 멈춰있는 서브그래프 정보가 담김
subgraph_snapshot = full_state.tasks[0].state
print(f"\n[현재 서브그래프 내부 상태]: {subgraph_snapshot.values}")

# 3. 승인 입력 보내기
graph.invoke(Command(resume="yes"), config)

print("\n--- 최종 결과 ---")
print(graph.get_state(config).values)

# 1. Invoke a graph from a node (수동 매핑 방식)
# 부모와 자식이 별개의 객체로 존재하며, 부모 노드 함수 내에서 자식을 **'함수처럼 호출'**하는 구조
'''
[Parent State: customer_name, order_value, status]
       │
       ▼
┌──────────────┐
│   initiate   │ (부모 노드 1)
└──────┬───────┘
       │ {status: "processing"} 업데이트
       ▼
┌───────────────────────────────────────────────┐
│  refund_process (부모 노드 2)                  │
│  ┌─────────────────────────────────────────┐  │
│  │ 1. 매핑: order_value(10만) -> raw_amount │  │
│  │                                         │  │
│  │ 2. Subgraph 실행 (독립 공간)             │  │
│  │    [Sub State: raw_amount, fee_rate]    │  │
│  │    START -> calculate_fee -> END        │  │
│  │               (90,000 산출)              │  │
│  │                                         │  │
│  │ 3. 매핑: final_refund -> status          │  │
│  └────────────────────┬────────────────────┘  │
└───────────────────────┼───────────────────────┘
       │                ▼
       ▼        {status: "환불 완료: 90000원"}
[Parent END]
'''

# 2. Add a graph as a node (상태 공유 방식)
# 부모 그래프의 설계도 안에 자식 그래프를 '직접 끼워넣는' 구조 / 특정 키(history)를 실시간으로 같이 사용
'''
[Parent State: history (List), priority]
      │
      ▼
┌──────────────┐
│   triage     │ (부모 노드 1)
└──────┬───────┘
      │ {history: ["상담원: 접수..."], priority: "High"} 추가
      ▼
┌──────────────────────────────────────────────┐
│  tech_team (서브그래프 노드)                  │
│                                              │
│  [Shared Space] <─── history 리스트 공유 ───> │
│                                              │
│  ┌───────────────────────────────────────┐   │
│  │ tech_analysis (서브그래프 노드 1)      │   │
│  │ - history에 "기술 팀: 결함..." 추가    │   │
│  │ - internal_notes (자식 전용) 기록      │   │
│  └───────────────────┬───────────────────┘   │
└──────────────────────┼───────────────────────┘
      │                ▼
      ▼        {history: ['고객: 화면이 안 나와요', '상담원: 기술 지원 요청 접수', '기술 팀: 하드웨어 결함 확인됨']}
[Parent END]
'''

# 3. View subgraph state: only in interrupt (중단 시 내부 상태 확인)
# 프로세스 도중 **'체크포인트'**를 찍고 멈춘 뒤, 외부에서 내부를 들여다보는 구조
'''
[Parent State: task_name, is_approved]
      │
      ▼
┌───────────────────────────────────────────────┐
│  process (서브그래프 노드)                     │
│  ┌─────────────────────────────────────────┐  │
│  │ ask_approval (서브그래프 노드 1)         │  │
│  │                                         │  │
│  │   [!] interrupt 발생 ───────────────────┼──┼───>  [관리자 대기]
│  │   (현재 상태 DB 저장: thread_id)         │  │          │
│  │                                         │  │          │ 1. get_state로 조회
│  │                                         │  │          │ 2. resume("yes") 전송
│  │   [▶] 재개 (Resume) <───────────────────┼──┼──────────┘
│  │                                         │  │
│  │ - is_approved: True로 업데이트           │  │
│  └────────────────────┬────────────────────┘  │
└───────────────────────┼───────────────────────┘
      │                 ▼
      ▼        {task_name: "서버 재부팅", is_approved: True}
[Parent END]
'''