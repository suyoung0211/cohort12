#기본 설정
from dotenv import load_dotenv
load_dotenv()

#-------------------------------------
#모델 설정
#-------------------------------------
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o-mini")
from langchain_google_genai import ChatGoogleGenerativeAI
llm1 = ChatGoogleGenerativeAI(model="gemini-2.5-flash")

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
# Schema for structured output to use in planning
class Section1(BaseModel):
    # 섹션 이름
    name: str = Field(
        description="이 논문의 제목입니다.",
    )
    # 섹션 설명
    description: str = Field(
        description="이 논문에서 다룰 주요 주제와 개념에 대한 간략한 개요입니다.",
    )

# 섹션 리스트
class Sections1(BaseModel):
    sections: List[Section] = Field(
        description="논문을 구성하는 섹션 목록입니다.",
    )


# Augment the LLM with schema for structured output
planner = llm.with_structured_output(Sections)
planner1 = llm1.with_structured_output(Sections1)

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
# 그래프 상태
class State1(TypedDict):
    topic: str  # 주제
    sections: list[Section]  # orchestrator가 만든 섹션 계획
    completed_sections: Annotated[
        list, operator.add
    ]  # 워커들이 만든 섹션 결과가 쌓이는 곳\
    final_report1: str  # 최종 리포트


# 워커 상태
class WorkerState1(TypedDict):
    section: Section #워커가 처리하는 섹션
    completed_sections: Annotated[list, operator.add] #워커가 처리한 섹션 결과가 쌓이는 곳


# Nodes1: orchestrator 노드(일을 쪼개는 계획자)
def orchestrator(state: State):
    """Orchestrator that generates a plan for the report in Korean"""

    # Generate queries
    report_sections = planner.invoke(
        [
            SystemMessage(content="보고서를 작성하기 위한 계획을 생성합니다."),
            HumanMessage(content=f"주제: {state['topic']}"),
        ]
    )

    # 계획 출력
    titles = [s.name for s in report_sections.sections]
    print(f"\n[PLAN] 섹션 {len(titles)}개 생성: {', '.join(titles)}\n")

    return {"sections": report_sections.sections} #섹션 계획
def orchestrator1(state: State1):
    """Orchestrator that generates a plan for the report in Korean"""

    # Generate queries
    report_sections = planner1.invoke(
        [
            SystemMessage(content="논문을 작성하기 위한 계획을 생성합니다."),
            HumanMessage(content=f"주제: {state['topic']}"),
        ]
    )

    # 계획 출력
    titles = [s.name for s in report_sections.sections]
    print(f"\n[PLAN] 논문 {len(titles)}개 생성: {', '.join(titles)}\n")

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
                content=f"섹션 이름: {state['section'].name} / 설명: {state['section'].description}"
            ),
        ]
    )

    # 어떤 섹션을 완료했는지 + 글자 수 정도만
    text = section.content or ""
    print(f"[WORKER] 완료: {state['section'].name} ({len(text)} chars)")

    # Write the updated section to completed sections
    return {"completed_sections": [section.content]} #리스트로 감싸는 것 중요

def llm_call1(state: WorkerState1):
    """Worker writes a section of the report in Korean"""

    # Generate section
    section = llm1.invoke(
        [
            SystemMessage(
                content="제공된 이름과 설명에 따라 논문 섹션을 작성하십시오. 각 섹션에 서문은 포함하지 마십시오. 마크다운 서식을 사용하십시오."
            ),
            HumanMessage(
                content=f"섹션 이름: {state['section'].name} / 설명: {state['section'].description}"
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
def synthesizer1(state: State1):
    """Synthesize full report from sections in Korean"""

    # List of completed sections
    completed_sections = state["completed_sections"]
    # 섹션 사이에 구분선 넣고 합치기
    completed_report_sections = "\n\n---\n\n".join(completed_sections)
    
    return {"final_report1": completed_report_sections}


# assign_workers (동적으로 워커 작업 생성)
def assign_workers(state: State):
    """Assign a worker to each section in the plan"""

    # 워커 몇 명 만드는지
    print(f"[DISPATCH] 워커 {len(state['sections'])}개 생성\n")
    
    # Kick off section writing in parallel via Send() API
    return [Send("llm_call", {"section": s}) for s in state["sections"]] 
def assign_workers1(state: State1):
    """Assign a worker to each section in the plan"""

    # 워커 몇 명 만드는지
    print(f"[DISPATCH] 워커 {len(state['sections'])}개 생성\n")
    
    # Kick off section writing in parallel via Send() API
    return [Send("llm1_call", {"section": s}) for s in state["sections"]] 

# Build workflow
orchestrator_worker_builder = StateGraph(State)
orchestrator_worker_builder1 = StateGraph(State1)

# Add the nodes
orchestrator_worker_builder.add_node("orchestrator", orchestrator)
orchestrator_worker_builder.add_node("llm_call", llm_call)
orchestrator_worker_builder.add_node("synthesizer", synthesizer)
orchestrator_worker_builder1.add_node("orchestrator", orchestrator1)
orchestrator_worker_builder1.add_node("llm_call1", llm_call1)
orchestrator_worker_builder1.add_node("synthesizer1", synthesizer1)

# Add edges to connect nodes
orchestrator_worker_builder.add_edge(START, "orchestrator")
orchestrator_worker_builder.add_conditional_edges(
    "orchestrator", assign_workers, ["llm_call"]
)
orchestrator_worker_builder.add_edge("llm_call", "synthesizer")
orchestrator_worker_builder.add_edge("synthesizer", END)
orchestrator_worker_builder1.add_edge(START, "orchestrator")
orchestrator_worker_builder1.add_conditional_edges(
    "orchestrator", assign_workers1, ["llm_call1"]
)
orchestrator_worker_builder1.add_edge("llm_call1", "synthesizer1")
orchestrator_worker_builder1.add_edge("synthesizer1", END)

# Compile the workflow
orchestrator_worker = orchestrator_worker_builder.compile()
orchestrator_worker1 = orchestrator_worker_builder1.compile()

# Show the workflow
print("Here is the mermaid graph syntax. You can paste it into https://mermaid.live/ :") #사이트 들어가서 코드 붙여넣기
print(orchestrator_worker.get_graph(xray=True).draw_mermaid())

# Invoke
state = orchestrator_worker.invoke({"topic": "LLM 사용 전망에 관한 보고서 짧게 작성"})
state1 = orchestrator_worker.invoke({"topic": "AI 모델에 대한 전망 논문 짧게 작성"})

text = state["final_report"] or ""
text1 = state1["final_report"] or ""
print(f"\n[synthesizer] 완료: {len(text)} chars\n")
print(f"\n[synthesizer1] 완료: {len(text)} chars\n")