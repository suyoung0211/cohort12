"""
Durable execution 개념
    ↓
언제 재개/중단/재실행이 가능한가?
    ↓
persistence layer가 실제 구현
(@1.persistence.py)
    ↓
task/decorators이 그래프 구조에서
deterministic 결과를 저장하기 위한 **권장 규칙**

"""

#-----------------------------------
# task로 API 호출 감싸기 (중복 실행 방지)
"""
task 로 감싼 작업을 checkpoint에 저장
API 호출 결과가 checkpoint에 저장
재실행 시 API 호출 재실행 안 함
"""
#-----------------------------------

##1. Durable execution in LangGraph##
print("\n## 1. Durable execution in LangGraph ##")

import uuid
import operator
from typing_extensions import TypedDict, Annotated

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.store.base import BaseStore
from langchain.messages import SystemMessage, HumanMessage
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
load_dotenv()

llm = init_chat_model(
    "gpt-4o-mini",
    temperature=0.2,
)

# thread_id 기준 대화 상태 저장
checkpointer = InMemorySaver()

# user_id 기준 장기 기억 저장
store = InMemoryStore()

from langgraph.func import task

# Task: UUID 생성 (비결정적 연산 분리)
@task
def task_generate_uuid():
    return str(uuid.uuid4())

# Task: 메모리 저장 (Side-effect 분리)
@task
def task_save_memory(user_id: str, content: str, memory_id: str):
    # 전역 store 사용 (실무에선 config로 전달 권장)
    namespace = (user_id, "memories")
    store.put(namespace, memory_id, {"memory": content})

# Task: LLM 호출 (비용/비결정적 연산 분리)
@task
def task_invoke_llm(system_content: str, user_content: str):
    # 전역 llm 사용
    system = SystemMessage(content=system_content)
    human = HumanMessage(content=user_content)
    return llm.invoke([system, human])

class State(TypedDict):
    # messages는 노드 실행 결과가 누적됨
    messages: Annotated[list[dict], operator.add]

# Memory 저장 노드
def update_memory(state: State, config: RunnableConfig, *, store: BaseStore):
    user_id = config["configurable"]["user_id"]
    
    # 가장 최근 사용자 발화
    last_user_message = state["messages"][-1]["content"]

    # Action 1: ID 생성 (Task)
    memory_id = task_generate_uuid().result()
    
    # Action 2: 저장 (Task)
    task_save_memory(user_id, last_user_message, memory_id).result()

    return {}

# Model 호출 노드 (memory 검색)
def call_model(state: State, config: RunnableConfig, *, store: BaseStore):
    user_id = config["configurable"]["user_id"]
    namespace = (user_id, "memories")

    user_text = state["messages"][-1]["content"]

    # 관련 메모리 검색
    memories = store.search(
        namespace,
        query=user_text,
        limit=3,
    )

    memory_text = "\n".join(m.value["memory"] for m in memories) if memories else "(저장된 기억 없음)"

    # 프롬프트 구성
    system_content = (
        "너는 사용자와 대화하는 비서야.\n"
        "아래 [기억]은 이 사용자에 대해 저장된 정보야. 답변에 참고해.\n"
        "만약 기억이 현재 질문과 관련 없으면, 억지로 끼워 맞추지 말고 무시해.\n\n"
        f"[기억]\n{memory_text}"
    )

    # Action: LLM 호출 (Task)
    ai_msg = task_invoke_llm(system_content, user_text).result()

    return {
        "messages": [
            {
                "role": "assistant",
                "content": ai_msg.content,
            }
        ]
    }

# 그래프 구성
graph = StateGraph(State)

graph.add_node("update_memory", update_memory)
graph.add_node("call_model", call_model)

graph.add_edge(START, "update_memory")
graph.add_edge("update_memory", "call_model")
graph.add_edge("call_model", END)

graph = graph.compile(
    checkpointer=checkpointer,
    store=store,
)


# 결과 보기
config = {
    "configurable": {
        "thread_id": "1",
        "user_id": "user_1",
    }
}

print(f"{config['configurable']} 유저는 피자를 좋아한다고 말함\n")

for update in graph.stream(
    {"messages": [{"role": "user", "content": "나는 피자를 좋아해"}]},
    config,
    stream_mode="updates",
):
    print(update)

config2 = {"configurable": {"thread_id": "2", "user_id": "user_1"}}

for update in graph.stream(
    {"messages": [{"role": "user", "content": "내 기억 뭐야?"}]},
    config2,
    stream_mode="updates",
):
    print(update)

config3 = {"configurable": {"thread_id": "2", "user_id": "user_2"}} #다른 유저에는 기억이 없는 것 확인

for update in graph.stream(
    {"messages": [{"role": "user", "content": "내 기억 뭐야?"}]},
    config3,
    stream_mode="updates",
):
    print(update)


#-----------------------------------
#durability 모드 비교
"""
| 옵션       | 설명                     
| --------- | ---------------------- 
| **exit**  | 그래프 종료 시만 저장 (빠름), default 
| **async** | 다음 단계 실행과 동시에 백그라운드 저장
| **sync**  | 단계마다 저장 (가장 안전함)
"""
#-----------------------------------