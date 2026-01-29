"""
체크포인터를 붙여 컴파일하면, 그래프 상태가 매 super-step마다 자동 저장(체크포인트) 된다.
저장된 체크포인트는 thread(스레드) 에 쌓이며, 실행이 끝난 뒤에도 상태 조회/재개/분기가 가능해진다.
그 결과로 HITL(중간에 사람 개입), 대화/세션 메모리, 과거 시점 재생(타임 트래블), 실패 지점부터 복구(장애 내성) 같은 기능이 열린다.
Agent Server를 쓰면 이런 저장/관리(체크포인팅)를 서버가 자동으로 해줘서 직접 설정할 필요가 없다


thread
thread는 그래프 실행 상태를 묶는 고유 식별자(ID)
thread_id는 이 그래프 실행의 기억이 저장되는 대화방/세션 키
"""

#----------------------------------------
#Checkpoints (스레드(thread)의 특정 시점 상태를 체크포인트(checkpoint))
"""
config: 해당 체크포인트와 연관된 설정(config)
metadata: 체크포인트에 대한 메타데이터
values: 해당 시점의 state 값
next: 다음에 실행될 노드
tasks: 다음에 실행될 작업 정보
"""
#----------------------------------------

from typing import Annotated
from typing_extensions import TypedDict
from operator import add
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.runnables import RunnableConfig

class State(TypedDict):
    foo: str
    bar: Annotated[list[str], add]

def node_a(state: State):
    return {"foo": "a", "bar": ["a"]}

def node_b(state: State):
    return {"foo": "b", "bar": ["b"]}

workflow = StateGraph(State)
workflow.add_node(node_a)
workflow.add_node(node_b)
workflow.add_edge(START, "node_a")
workflow.add_edge("node_a", "node_b")
workflow.add_edge("node_b", END)

# Checkpointer 설정
checkpointer = InMemorySaver()
graph = workflow.compile(checkpointer=checkpointer)

# 초기 실행
config: RunnableConfig = {"configurable": {"thread_id": "1"}}
print("--- [초기 실행 시작] ---")
result=graph.invoke({"foo": "", "bar": []}, config)
print("초기 실행 완료\n")
print(result) # {'foo': 'b', 'bar': ['a', 'b']}


##1. Get state (상태 조회)##
config = {"configurable": {"thread_id": "1"}} #{"thread_id": "1", "checkpoint_id": } 특정 체크포인트 조회 가능
latest_state = graph.get_state(config)
print("\n## 최신 상태 조회 ##")
print(latest_state)

##2. Get state history (상태 히스토리 조회)##
print("\n## 상태 히스토리 조회 ##")
config = {"configurable": {"thread_id": "1"}}
history = list(graph.get_state_history(config))
print(history) # 내림차순, checkpoint_id는 매번 변경 됨

##3. Replay (리플레이)##
config = {"configurable": {"thread_id": "1", "checkpoint_id": history[1].config['configurable']['checkpoint_id']}}
graph.invoke(None, config=config)
print("\n## 리플레이 결과 ##")
print(graph.get_state(config))


##4. Update state (상태 수정)##
"""
config
thread_id: 업데이트할 스레드
checkpoint_id(선택): 해당 체크포인트에서 상태를 포크(fork)
"""

"""
values
업데이트할 state 값
노드가 state를 업데이트하는 것과 동일하게 처리
reducer 규칙에 따라 처리됨
"""

config = {"configurable": {"thread_id": "1"}}
graph.update_state(config, {"foo": "2", "bar": ["b"]})
print("\n## Update State 결과 ##")
print(graph.get_state(config))

"""
as_node
update_state를 호출할 때 선택적으로 as_node를 지정, 선택 없으면 최신으로
"""
# 특정 노드가 업데이트한 것처럼 속여서 다음 실행 흐름을 제어할 수 있음
print("\n## 4-1. Update State with as_node ##")
graph.update_state(config, {"foo": "forked_foo", "bar": ["hello world"]}, as_node="node_a")
forked_state = graph.get_state(config)
print(f"as_node='node_a' 업데이트 후 다음에 실행될 노드(next): {forked_state.next}")

print("\n## 재개 실행 후 상태 ##")
graph.invoke(None, config={"configurable": {"thread_id": "1"}})
print(graph.get_state({"configurable": {"thread_id": "1"}}))

#----------------------------------------
#Memory store
"""
Store는 “스레드를 넘어 공유되는 사용자/전역 기억”을 담당
"""
#----------------------------------------

##1. Basic Usage##
import uuid
from langgraph.store.memory import InMemoryStore
in_memory_store = InMemoryStore()

user_id = "1"
namespace_for_memory = (user_id, "memories") #1번 사용자 memories 폴더
print("\n## 1. Basic Usage ##")
print(f"네임스페이스: {namespace_for_memory}")

memory_id = str(uuid.uuid4())
memory = {"음식선호도" : "피자 좋아"}
in_memory_store.put(namespace_for_memory, memory_id, memory) #저장 put

memories = in_memory_store.search(namespace_for_memory) #조회 search
print(f"메모리에 담긴 데이터: {memories[-1].dict()}")


##2. Semantic Search##
from dotenv import load_dotenv
load_dotenv()

from langchain.embeddings import init_embeddings

store = InMemoryStore(
    index={
        "embed": init_embeddings("openai:text-embedding-3-small"),  # Embedding provider
        "dims": 1536,                              # Embedding dimensions
        "fields": ["음식선호도", "$"] #유저에 대한 모든 문맥을 기억하려면 "$" / 특정 필드만 임베딩할 수 도 있음
    }
)

print("\n## 2. Semantic Search ##")

#(1) 아직 메모리 없을 때 검색
memories = store.search(
    namespace_for_memory,
    query="유저가 좋아한다고 말한 음식은?",
    limit=3  # Return top 3 matches
)
print("초기 시맨틱 검색 결과:", [m.value for m in memories])

# 특정 필드만 임베딩
store.put(
    namespace_for_memory,
    str(uuid.uuid4()),
    {
        "음식선호도": "나는 이탈리아 음식을 좋아해",
        "context": "저녁에 관한 계획 논의하기"
    },
    index=["음식선호도"] # Only embed "음식선호도" field
)

# 임베딩 없이 저장 (조회는 가능, 시맨틱 검색은 불가)
store.put(
    namespace_for_memory,
    str(uuid.uuid4()),
    {
        "취미": "스킨스쿠버 다이빙이 취미야",
        "context": "저녁에 관한 계획 논의하기"
    },
    index=False
)

store.put(
    namespace_for_memory,
    str(uuid.uuid4()),
    {
        "음식선호도": "나는 고수가 싫어",
        "context": "점심에 관한 계획 논의하기"
    }
)

#(2) 메모리 추가 후 검색
memories = store.search(
    namespace_for_memory,
    query="유저가 좋아한다고 말한 음식은?",
    limit=3  # Return top 3 matches
)
print("최종 시맨틱 검색 결과:", [(m.value, m.score) for m in memories])


##3. Using in LangGraph##
print("\n## 3. LangGraph에서 Memory Store 사용하기 ##")

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

llm = init_chat_model(
    "gpt-4o-mini",
    temperature=0.2,
)

# thread_id 기준 대화 상태 저장
checkpointer = InMemorySaver()

# user_id 기준 장기 기억 저장
store = InMemoryStore()

class State(TypedDict):
    # messages는 노드 실행 결과가 누적됨
    messages: Annotated[list[dict], operator.add]

# Memory 저장 노드
def update_memory(state: State, config: RunnableConfig, *, store: BaseStore):
    user_id = config["configurable"]["user_id"]
    namespace = (user_id, "memories")

    # 가장 최근 사용자 발화
    last_user_message = state["messages"][-1]["content"]

    memory_id = str(uuid.uuid4())
    store.put(
        namespace,
        memory_id,
        {"memory": last_user_message},
    )

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

    # 메모리를 “컨텍스트”로 넣고, OpenAI가 답하도록 함
    system = SystemMessage(
        content=(
            "너는 사용자와 대화하는 비서야.\n"
            "아래 [기억]은 이 사용자에 대해 저장된 정보야. 답변에 참고해.\n"
            "만약 기억이 현재 질문과 관련 없으면, 억지로 끼워 맞추지 말고 무시해.\n\n"
            f"[기억]\n{memory_text}"
        )
    )
    human = HumanMessage(content=user_text)

    ai_msg = llm.invoke([system, human])

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

# [시나리오 시작]
config = {
    "configurable": {
        "thread_id": "root_1", # 1번 우주
        "user_id": "pengveloper",
    }
}

print("\n🎬 [Scene 1] 흑역사 생성 중...")
# 1. 실수로 약한 모습을 보임
inputs = {"messages": [{"role": "user", "content": "아 나 오늘 깃 머지하다가 충돌 나서 다 날려먹었어 ㅠㅠ"}]}

# stream 대신 invoke로 한 번만 실행 (중간 개입을 위해)
initial_state = graph.invoke(inputs, config)
print(f"AI의 반응(원본): {initial_state['messages'][-1]['content']}")


print("\n🧙‍♂️ [Scene 2] 닥터 스트레인지 등판! (Time Travel)")

# 2-1. [기존] 대화 내역(State) 조작 -> "채팅 로그 조작"
new_message = {
    "role": "user",
    "content": "나 오늘 깃 머지 충돌 났는데 CLI로 완벽하게 해결했어! 완전 고수 같았음 v"
}

current_messages = initial_state['messages']
current_messages[-2] = new_message
current_messages.pop()

print(">> 채팅 로그(State)를 수정하고 있습니다...")
graph.update_state(config, {"messages": current_messages})


# 🔥 [추가] 2-2. 장기 기억(Store) 조작 -> "뇌세척(?)"
print(">> 뇌 속의 기억(Store)도 조작합니다...")

# (1) 방금 저장된 '망했다'는 기억을 찾습니다.
bad_memories = store.search(("pengveloper", "memories"), query="망했어", limit=1)

if bad_memories:
    bad_memory_id = bad_memories[0].key # 기억의 고유 번호(ID)를 알아냄

    # (2) 그 ID의 내용을 '성공했다'로 덮어씌웁니다(put).
    store.put(
        ("pengveloper", "memories"),
        bad_memory_id, # 같은 ID로 저장하면 덮어쓰기(Update) 됨!
        {"memory": "나 오늘 깃 머지 충돌 났는데 완벽하게 해결했어! 완전 고수임."}
    )
    print(f"   -> 기억 ID({bad_memory_id})의 내용을 '성공'으로 바꿔치기 완료!")


print("\n🎬 [Scene 3] 바뀐 미래 확인")

# 3. 수정된 기억을 바탕으로 다시 AI에게 말을 걸어봅니다.
# AI가 기억을 제대로 했는지 확인하기 위해 질문
inputs_2 = {"messages": [{"role": "user", "content": "나 오늘 어땠다고?"}]}

for update in graph.stream(inputs_2, config, stream_mode="updates"):
    pass

final_state = graph.get_state(config)
print(f"\nAI의 최종 반응: {final_state.values['messages'][-1]['content']}")


# 4. Store(장기 기억)까지 조작되었는지 확인
print("\n📦 [Store 확인] 뇌 속에 저장된 기억 까보기")
memories = store.search(("pengveloper", "memories"))
for m in memories:
    print(f"- 기억: {m.value['memory']}")



"""Apendix

- langgraph.json 설정은 “배포/서버 환경에서 store 인덱스 켜기”
"store": {
  "index": {
    "embed": "openai:text-embeddings-3-small",
    "dims": 1536,
    "fields": ["$"]
  }

# 시스템적으로 어떻게 보관·보호·운영할까
 - langgraph-checkpoint vs langgraph-checkpoint-sqlite vs langgraph-checkpoint-postgres: '어디에 저장하냐' 차이
 - Serializer: 'state를 저장 가능하게 변환'하는 규칙
 - pickle_fallback: 변환 실패 시 pickle로 구제
 - EncryptedSerializer: 저장되는 내용 자체를 암호화
 """