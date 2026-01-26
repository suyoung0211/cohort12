#기본 설정
from dotenv import load_dotenv
load_dotenv()

#-------------------------------------
#모델 설정
#-------------------------------------
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o")

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

from langchain.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

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
            SystemMessage(content="보고서를 작성하기 위한 계획을 생성합니다."),
            HumanMessage(content=f"주제: {state['topic']}\n출력은 반드시 한국어로 작성하라."),
        ]
    )

    # 계획 출력
    titles = [s.name for s in report_sections.sections]
    print(f"\n[PLAN] 섹션 {len(titles)}개 생성: {', '.join(titles)}\n")

    return {"sections": report_sections.sections} #섹션 계획


# Nodes2: llm_call 노드(일을 하는 워커)
def llm_call(state: WorkerState):
    """Worker writes a section of the report in Korean"""

    # Generate section
    section = llm.invoke(
        [
            SystemMessage(
                content="제공된 이름과 설명에 따라 보고서 섹션을 작성하십시오. 각 섹션에 서문은 포함하지 마십시오. 마크다운 서식을 사용하십시오."
            ),
            HumanMessage(
                content=f"섹션 이름: {state['section'].name} / 설명: {state['section'].description}\n출력은 반드시 한국어로 작성하라."
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
state = orchestrator_worker.invoke({"topic": "LLM 프롬프트 법칙에 관한 보고서 짧게 작성"})

text = state["final_report"] or ""
print(f"\n[synthesizer] 완료: {len(text)} chars\n")