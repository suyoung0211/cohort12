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

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

# DB 설정
from pymongo import MongoClient
MongoDB_URI = os.getenv("MONGODB_URI")
client = MongoClient(MongoDB_URI)
DB = client["brickers"]
collection = DB["ldraw_parts"]

#-------------------------------------
#Orchestrator-worker(오케스트레이터가 계획을 만들고 → 워커를 ‘동적으로’ 만들어서 일 하게 하고 → 결과를 합치는)
#-------------------------------------
from typing import Annotated, List
import operator


# Schema for structured output to use in planning
class Section(BaseModel):
    # 섹션 이름
    name: str = Field(
        description="이 섹션의 제목입니다.",
    )
    # 섹션 설명
    description: str = Field(
        description="이 섹션에서 다룰 주요 주제와 개념에 대한 간략한 개요입니다.",
    )

# 섹션 리스트
class Sections(BaseModel):
    sections: List[Section] = Field(
        description="보고서를 구성하는 섹션 목록입니다.",
    )


# Augment the LLM with schema for structured output
planner = llm.with_structured_output(Sections)

# Creating workers in LangGraph
from langgraph.types import Send #“워커 노드를 동적으로 여러 개 생성해서 특정 입력을 각각에 보내라”를 표현하는 객체. Send("노드이름", {입력})


# 그래프 상태
class State(TypedDict):
    topic: str  # 주제
    sections: list[Section]  # orchestrator가 만든 섹션 계획
    completed_sections: Annotated[
        list, operator.add
    ]  # 워커들이 만든 섹션 결과가 쌓이는 곳\
    final_report: str  # 최종 리포트


# 워커 상태
class WorkerState(TypedDict):
    section: Section #워커가 처리하는 섹션
    completed_sections: Annotated[list, operator.add] #워커가 처리한 섹션 결과가 쌓이는 곳


# Nodes1: orchestrator 노드(일을 쪼개는 계획자)
def orchestrator(state: State):
    """Orchestrator that generates a plan for the report in Korean"""

    # Generate queries
    report_sections = planner.invoke(
        [
            SystemMessage(content="보고서를 작성하기 위한 계획을 생성합니다. 섹션은 3~5개까지만 생성하세요"),
            HumanMessage(content=f"주제: {state['topic']}"),
        ]
    )

    # 계획 출력
    titles = [s.name for s in report_sections.sections]
    print(f"\n[PLAN] 섹션 {len(titles)}개 생성: {', '.join(titles)}\n")

    return {"sections": report_sections.sections} #섹션 계획


# Nodes2: llm_call 노드(일을 하는 워커)
def llm_call(state: WorkerState):
    """Worker가 DB 조회하고 섹션을 작성"""
    
    section_name = state['section'].name
    # 1. DB 조회
    search_keyword = section_name.split()[0]

    db_results = list(collection.find(
        {
            "$or": 
            [
                {"name": {"$regex": search_keyword, "$options": "i"}},
                {"category": {"$regex": search_keyword, "$options": "i"}}
            ]
        },
        {"_id": 0, "name": 1, "partId": 1, "category": 1}
    ).limit(5))

    # 2. 검색 결과 유무에 따른 컨텍스트 작성
    if db_results:
        db_context = f"다음은 '{search_keyword}'와 관련된 DB 검색 결과입니다:\n{str(db_results)}"
    else:
        db_context = "관련된 DB 데이터가 없습니다. 일반적인 지식을 바탕으로 작성하세요."

    # Generate section
    section = llm.invoke(
        [
            SystemMessage(
                content="너는 레고 데이터 분석가다. 제공된 [DB 검색 결과]를 반드시 인용하여 상세한 보고서 섹션을 작성해."
            ),
            HumanMessage(
                content=f"""
                섹션 이름: {state['section'].name}
                설명: {state['section'].description}
                
                [DB 검색 결과]
                {db_context}
                """
            ),
        ]
    )

    # 어떤 섹션을 완료했는지 + 글자 수 정도만
    text = section.content or ""
    print(f"[WORKER] 완료: {state['section'].name} ({len(text)} chars)")

    # Write the updated section to completed sections
    return {"completed_sections": [section.content]} #리스트로 감싸는 것 중요


# Nodes3: synthesizer 노드(편집자/편집장 역할)
def synthesizer(state: State):
    """Synthesize full report from sections in Korean"""

    # List of completed sections
    completed_sections = state["completed_sections"]
    # 섹션 사이에 구분선 넣고 합치기
    completed_report_sections = "\n\n---\n\n".join(completed_sections)
    
    return {"final_report": completed_report_sections}


# assign_workers (동적으로 워커 작업 생성)
def assign_workers(state: State):
    """Assign a worker to each section in the plan"""

    # 워커 몇 명 만드는지
    print(f"[DISPATCH] 워커 {len(state['sections'])}개 생성\n")
    
    # Kick off section writing in parallel via Send() API
    return [Send("llm_call", {"section": s}) for s in state["sections"]] 

# Build workflow
orchestrator_worker_builder = StateGraph(State)

# Add the nodes
orchestrator_worker_builder.add_node("orchestrator", orchestrator)
orchestrator_worker_builder.add_node("llm_call", llm_call)
orchestrator_worker_builder.add_node("synthesizer", synthesizer)

# Add edges to connect nodes
orchestrator_worker_builder.add_edge(START, "orchestrator")
orchestrator_worker_builder.add_conditional_edges(
    "orchestrator", assign_workers, ["llm_call"]
)
orchestrator_worker_builder.add_edge("llm_call", "synthesizer")
orchestrator_worker_builder.add_edge("synthesizer", END)

# Compile the workflow
orchestrator_worker = orchestrator_worker_builder.compile()

# Show the workflow
print("Here is the mermaid graph syntax. You can paste it into https://mermaid.live/ :") #사이트 들어가서 코드 붙여넣기
print(orchestrator_worker.get_graph(xray=True).draw_mermaid())

# Invoke
topic = "레고의 3대 기본 부품인 Brick, Plate, Tile에 대해 상세 데이터 분석 보고서"
state = orchestrator_worker.invoke({"topic": topic})

text = state["final_report"] or ""
print(f"\n[synthesizer] 완료: {len(text)} chars\n")