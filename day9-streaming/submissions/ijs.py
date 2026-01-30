"""
.stream() : 동기
.astream() : 비동기

| 모드        | 의미                                         | 출력 예시
| ---------- | ------------------------------------------- | ------------------------------- |
| `updates`  | 각 스텝(step)에서의 상태 변경만 스트리밍함      | {'nodeA': {'field': 'value'}}
| `values`   | 전체 상태를 계속 추적해야 할 때                 | 전체 상태 객체 {...}
| `messages` | 실시간 채팅처럼 토큰 단위 출력이 필요할 때         | (토큰조각, metadata)
| `custom`   | 노드 내부에서 writer()로 직접 만든 임의 스트림 출력   | {"progress":"50%"}
| `debug`    | 디버깅용 상세 정보 (노드 id, 시간, 입력/출력 등)     | 상세 실행 로그

"""
from dotenv import load_dotenv
load_dotenv()

# =========================================================
# 🎭 실시간 AI 스토리텔러 (메인 데모)
# - 3명의 AI 작가가 병렬로 스토리, 교훈, 제목 생성
# - metadata 필터링으로 각 작가 구분
# - 장르 선택 + 최종 결과 정리 + 파일 저장 기능
# - gemini-2.5-flash 모델 사용
# =========================================================

import asyncio
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI

# 장르별 프롬프트 스타일
GENRES = {
    "1": ("판타지", "마법과 신비로운 세계관을 담아"),
    "2": ("로맨스", "사랑과 감동을 담아"),
    "3": ("공포", "섬뜩하고 긴장감 있게"),
    "4": ("코미디", "유머러스하고 웃기게"),
    "5": ("감동", "눈물 나게 감동적으로"),
}

# 3명의 AI 작가 (tags로 구분) - 모두 gemini-2.5-flash 사용
story_writer = ChatGoogleGenerativeAI(model="gemini-2.5-flash", tags=["story"])
moral_writer = ChatGoogleGenerativeAI(model="gemini-2.5-flash", tags=["moral"])
title_writer = ChatGoogleGenerativeAI(model="gemini-2.5-flash", tags=["title"])

class StoryState(TypedDict):
    topic: str
    genre: str
    genre_style: str
    story: str
    moral: str
    title: str

# 스토리 작가
async def write_story(state: StoryState, config):
    res = await story_writer.ainvoke(
        [{"role": "user", "content": f"{state['topic']}에 대한 짧은 이야기를 {state['genre_style']} 3문장으로 써줘. 한국어로 답변해."}],
        config,
    )
    return {"story": res.content}

# 교훈 작가
async def write_moral(state: StoryState, config):
    res = await moral_writer.ainvoke(
        [{"role": "user", "content": f"{state['topic']}에 대한 교훈을 {state['genre_style']} 1문장으로 써줘. 한국어로 답변해."}],
        config,
    )
    return {"moral": res.content}

# 제목 작가
async def write_title(state: StoryState, config):
    res = await title_writer.ainvoke(
        [{"role": "user", "content": f"{state['topic']}에 대한 {state['genre']} 장르의 매력적인 제목을 1개만 써줘. 한국어로 답변해."}],
        config,
    )
    return {"title": res.content}

# 그래프 (3명이 병렬로 작업)
storyteller_graph = (
    StateGraph(StoryState)
    .add_node("write_story", write_story)
    .add_node("write_moral", write_moral)
    .add_node("write_title", write_title)
    .add_edge(START, "write_story")   # 동시 실행
    .add_edge(START, "write_moral")   # 동시 실행
    .add_edge(START, "write_title")   # 동시 실행
    .compile()
)

# 메인 실행
async def run_storyteller():
    print("\n" + "="*60)
    print("🎭 실시간 AI 스토리텔러")
    print("="*60)

    # 장르 선택
    print("\n📚 장르를 선택하세요:")
    for key, (name, _) in GENRES.items():
        print(f"  {key}. {name}")

    while True:
        genre_choice = input("\n선택 (1-5): ").strip()
        if genre_choice in GENRES:
            break
        print("❌ 1~5 중에서 선택해주세요.")

    genre_name, genre_style = GENRES[genre_choice]
    print(f"✅ '{genre_name}' 장르가 선택되었습니다!")

    topic = input("\n이야기 주제를 입력하세요: ").strip()

    print(f"\n📖 [{genre_name}] '{topic}'에 대한 이야기를 3명의 작가가 작성 중...\n")
    print("-"*60)

    # 결과 저장용 버퍼
    story_buffer = ""
    moral_buffer = ""
    title_buffer = ""

    async for msg, metadata in storyteller_graph.astream(
        {
            "topic": topic,
            "genre": genre_name,
            "genre_style": genre_style,
        },
        stream_mode="messages",
    ):
        if not msg.content:
            continue

        # 작가별로 다른 이모지로 출력 + 버퍼에 저장
        tags = metadata.get("tags", [])

        if "story" in tags:
            print(f"📝 {msg.content}", end="", flush=True)
            story_buffer += msg.content
        elif "moral" in tags:
            print(f"\n💡 {msg.content}", end="", flush=True)
            moral_buffer += msg.content
        elif "title" in tags:
            print(f"\n🎬 {msg.content}", end="", flush=True)
            title_buffer += msg.content

    print("\n" + "-"*60)

    # 최종 결과 정리
    print("\n" + "="*60)
    print("📜 최종 결과")
    print("="*60)
    print(f"\n🏷️  장르: {genre_name}")
    print(f"🎬 제목: {title_buffer.strip()}")
    print(f"\n📝 스토리:\n{story_buffer.strip()}")
    print(f"\n💡 교훈: {moral_buffer.strip()}")
    print("="*60)

    # 저장 옵션
    save_choice = input("\n💾 파일로 저장할까요? (y/n): ").strip().lower()
    if save_choice == 'y':
        filename = f"story_{topic}_{genre_name}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"🎭 AI 스토리텔러 - {genre_name}\n")
            f.write("="*40 + "\n\n")
            f.write(f"주제: {topic}\n")
            f.write(f"제목: {title_buffer.strip()}\n\n")
            f.write(f"스토리:\n{story_buffer.strip()}\n\n")
            f.write(f"교훈: {moral_buffer.strip()}\n")
        print(f"✅ '{filename}' 저장 완료!")

    print("\n🎭 스토리텔링 종료!")
    print("="*60)

# 스토리텔러 실행
asyncio.run(run_storyteller())


# =========================================================
# 아래는 원본 예제 코드들 (참고용)
# =========================================================

# =========================================================
# 1. 기본 스트리밍 (updates / values / custom / messages / debug)
# =========================================================
print("\n\n" + "="*60)
print("📚 원본 예제 코드 실행")
print("="*60)

from langgraph.config import get_stream_writer

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash") # streaming=False도 가능

class State(TypedDict):
    topic: str
    joke: str

def refine_topic(state: State):
    return {"topic": state["topic"] + " 그리고 고양이"}

def generate_joke(state: State):
    msg = llm.invoke(f"{state['topic']}에 대한 농담 하나 만들어줘")
    # for custom stream
    writer = get_stream_writer()  
    writer(f"[1/2] {state['topic']} 조회 시작")
    writer(f"[2/2] {state['topic']} 조회 완료")
    return {"joke": f"이것은 {state['topic']}에 대한 농담입니다: \n{msg.content}"}

graph = (
    StateGraph(State)
    .add_node(refine_topic)
    .add_node(generate_joke)
    .add_edge(START, "refine_topic")
    .add_edge("refine_topic", "generate_joke")
    .add_edge("generate_joke", END)
    .compile()
)

# Basic usage (기본은 updates 모드)
print("\n#######Basic usage#######")
for chunk in graph.stream(  
    {"topic": "ice cream"}
):
    print(chunk)

# Multiple modes
print("\n#######Multiple modes#######")
for mode, chunk in graph.stream({"topic": "ice cream"}, stream_mode=["updates", "custom", "values", "messages", "debug"]):
    print(f"\n{mode}: {chunk}")


# =========================================================
# 아래 예제들은 GPT/OpenAI API를 사용하므로 주석 처리됨
# 필요시 OpenAI API 키 설정 후 주석 해제하여 사용
# =========================================================

"""
# =========================================================
# 2. messages 스트림 + metadata 필터링 (누가 / 어디서 말했는지)
# =========================================================
print(f"\\n\\n# -------------------------\\n# metadata를 이용한 필터링\\n# -------------------------")

import asyncio
from typing import TypedDict
from langgraph.graph import START, StateGraph
from langchain.chat_models import init_chat_model

# 1. LLM 호출마다 tags를 달아 "누가 말했는지" 구분
joke_model = init_chat_model(model="gpt-4o-mini", tags=["joke"])
poem_model = init_chat_model(model="gpt-4o-mini", tags=["poem"])

class State(TypedDict):
    topic: str
    joke: str
    poem: str

# 2. 노드 2개 (node 기준 필터용)
async def write_joke(state: State, config):
    res = await joke_model.ainvoke(
        [{"role": "user", "content": f"{state['topic']}에 대한 농담 하나 만들어줘"}],
        config,
    )
    return {"joke": res.content}

async def write_poem(state: State, config):
    res = await poem_model.ainvoke(
        [{"role": "user", "content": f"{state['topic']}에 대한 짧은 시 하나 만들어줘"}],
        config,
    )
    return {"poem": res.content}

# 3. 그래프 (병렬 실행)
graph = (
    StateGraph(State)
    .add_node("write_joke", write_joke)
    .add_node("write_poem", write_poem)
    .add_edge(START, "write_joke")
    .add_edge(START, "write_poem")
    .compile()
)


print("\\n######## messages 스트림 + metadata 필터링 ########")
# 4. 스트리밍 출력
async def main():
    async for msg, metadata in graph.astream(
        {"topic": "고양이"},
        stream_mode="messages",
    ):
        if not msg.content:
            continue

        # Filter by LLM invocation (tags) : 어떤 LLM 호출에서
        if metadata.get("tags") == ["joke"]:
            print(msg.content, end="", flush=True)

        # # Filter by node : 그래프의 어느 노드에서
        # if metadata.get("langgraph_node") == "write_poem":
        #     print(msg.content, end="|", flush=True)

asyncio.run(main())


# =========================================================
# 3. LangChain을 안 쓰는 LLM이라도, 토큰 스트리밍을 custom 스트림으로 LangGraph에 끼워 넣을 수 있음
# =========================================================
import operator
import json

from typing import TypedDict
from typing_extensions import Annotated
from langgraph.graph import StateGraph, START

from openai import AsyncOpenAI

openai_client = AsyncOpenAI()
model_name = "gpt-4o-mini"


async def stream_tokens(model_name: str, messages: list[dict]):
    response = await openai_client.chat.completions.create(
        messages=messages, model=model_name, stream=True
    )
    role = None
    async for chunk in response: # 비동기 반복문으로 토큰 조각을 하나씩 받음
        delta = chunk.choices[0].delta

        if delta.role is not None:
            role = delta.role

        if delta.content: # 토큰 내용이 있다면 yield로 밖으로 보냄
            yield {"role": role, "content": delta.content}


# this is our tool
async def get_items(place: str) -> str:
    writer = get_stream_writer()
    response = ""
    async for msg_chunk in stream_tokens(
        model_name,
        [{"role": "user", "content": f"{place}에서 볼 수 있는 물건 3가지를 설명과 함께 알려줘"}],
    ):
        response += msg_chunk["content"]
        writer(msg_chunk)

    return response


class State(TypedDict):
    messages: Annotated[list[dict], operator.add]


# this is the tool-calling graph node
async def call_tool(state: State):
    ai_message = state["messages"][-1]
    tool_call = ai_message["tool_calls"][-1]

    function_name = tool_call["function"]["name"]
    if function_name != "get_items":
        raise ValueError(f"Tool {function_name} not supported")

    function_arguments = tool_call["function"]["arguments"]
    arguments = json.loads(function_arguments)

    function_response = await get_items(**arguments)
    tool_message = {
        "tool_call_id": tool_call["id"],
        "role": "tool",
        "name": function_name,
        "content": function_response,
    }
    return {"messages": [tool_message]}


graph = (
    StateGraph(State)
    .add_node(call_tool)
    .add_edge(START, "call_tool")
    .compile()
)

print("\\n\\n######## custom 스트림 (LangChain 없이 토큰 스트리밍) ########")
inputs = {
    "messages": [
        {
            "content": None,
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "1",
                    "function": {
                        "arguments": '{"place":"bedroom"}',
                        "name": "get_items",
                    },
                    "type": "function",
                }
            ],
        }
    ]
}

import asyncio
async def main():
    async for chunk in graph.astream(
        inputs,
        stream_mode="custom",
    ):
        print(chunk["content"], end="|", flush=True)

asyncio.run(main())
"""

# =========================================================
# 4. Subgraph 스트리밍 (Gemini 사용하지 않음, 순수 로직만)
# =========================================================
print("\n\n######## Subgraph 스트리밍 ########")
from langgraph.graph import START, StateGraph
from typing import TypedDict

# Define subgraph
class SubgraphState(TypedDict):
    foo: str  # note that this key is shared with the parent graph state
    bar: str

def subgraph_node_1(state: SubgraphState):
    return {"bar": "bar"}

def subgraph_node_2(state: SubgraphState):
    return {"foo": state["foo"] + state["bar"]}

subgraph_builder = StateGraph(SubgraphState)
subgraph_builder.add_node(subgraph_node_1)
subgraph_builder.add_node(subgraph_node_2)
subgraph_builder.add_edge(START, "subgraph_node_1")
subgraph_builder.add_edge("subgraph_node_1", "subgraph_node_2")
subgraph = subgraph_builder.compile()

# Define parent graph
class ParentState(TypedDict):
    foo: str

def node_1(state: ParentState):
    return {"foo": "hi! " + state["foo"]}

builder = StateGraph(ParentState)
builder.add_node("node_1", node_1)
builder.add_node("node_2", subgraph)
builder.add_edge(START, "node_1")
builder.add_edge("node_1", "node_2")
graph = builder.compile()

for chunk in graph.stream(
    {"foo": "foo"},
    stream_mode="updates",
    # Set subgraphs=True to stream outputs from subgraphs
    subgraphs=True,  
):
    print(chunk)