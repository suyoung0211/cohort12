# ============================================================
# [Day 6 최종 과제] LangGraph 마스터리: AI 서술형 채점 시스템 (Final)
#
# 포함된 패턴:
# 1. Structured Output (Pydantic): 입출력 규격화
# 2. Orchestrator: 복잡한 입력을 분류하고 계획 수립
# 3. Dynamic Parallelism (Send): 동적 워커 생성 (Map)
# 4. Cycle/Loop (Reflexion): 점수 기반의 자기 교정 루프
# 5. Aggregation (Reducer): 결과 취합 및 리포트 생성
# ============================================================

import operator
from typing import Annotated, List, TypedDict, Optional
from typing_extensions import Literal
from dotenv import load_dotenv

# LangChain / Google Gemini 설정
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

# LangGraph 핵심 모듈
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

# 환경 변수 로드 (.env 파일 필요)
load_dotenv()

# 모델 설정 (Gemini Flash 사용 권장)
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")

# -------------------------------------
# MOCK DATA (테스트용 가짜 데이터)
# -------------------------------------
STUDENT_DRAFT = """
[김철수 학생 답안]
1. 임진왜란은 1592년에 일어났고 이순신 장군이 활약했습니다.
2. 삼각형의 내각의 합은 180도입니다.
3. 물은 산소 2개, 수소 1개로 이루어져 있어 화학식은 HO2입니다.
4. '사과'는 영어로 Banana라고 합니다. 
5. 40세의 나이를 불혹이라고 합니다.
"""

# -------------------------------------
# 1. 데이터 모델 정의 (Schema)
# -------------------------------------

# [분류용] 개별 답안 구조
class AnswerSheet(BaseModel):
    subject: str = Field(..., description="과목명")
    student_answer: str = Field(..., description="학생 답안 내용")

# [분류용] 전체 답안지 구조
class ParsedExam(BaseModel):
    sheets: List[AnswerSheet] = Field(..., description="분류된 답안 리스트")

# [채점용] 학생 성적표
class GradeResult(BaseModel):
    subject: str
    score: int = Field(..., description="학생 점수 (0-100)")
    feedback: str = Field(..., description="학생에게 줄 피드백")
    is_correct: bool

# [검토용] 채점 품질 평가표 (Pass/Fail 대신 점수 사용)
class ReviewResult(BaseModel):
    quality_score: int = Field(..., description="채점의 논리적 타당성 점수 (0-100)")
    critique: str = Field(..., description="채점에 대한 평가 및 개선 요구사항")


# -------------------------------------
# 2. SubGraph (Worker) 정의
# -------------------------------------

# [Worker State]
class WorkerState(TypedDict):
    # 입력
    subject: str
    student_answer: str

    # 내부 상태
    grade_result: Optional[GradeResult] # 채점 결과
    review_critique: Optional[str]      # 검토 피드백
    retry_count: int                    # 재시도 횟수

    # [BRIDGE] 출력 (메인 그래프로 전달될 데이터)
    # operator.add를 통해 메인 그래프의 리스트에 자동으로 합류합니다.
    final_grades: Annotated[List[GradeResult], operator.add]

# [Node: Grader] 채점 선생님
def node_grade(state: WorkerState):
    print(f"    ✍️ [{state['subject']}] 채점 중... (시도: {state['retry_count'] + 1}회)")

    grader = llm.with_structured_output(GradeResult)

    prompt = f"과목: {state['subject']}\n답안: {state['student_answer']}\n위 내용을 채점하세요."

    # 재시도일 경우 피드백 반영 (Reflexion)
    if state.get("review_critique"):
        prompt += f"\n\n[지적사항]: '{state['review_critique']}'\n위 지적을 반영하여 채점을 수정하세요."

    result = grader.invoke(prompt)
    result.subject = state['subject'] # 과목명 유지

    return {"grade_result": result, "retry_count": state["retry_count"] + 1}

# [Node: Reviewer] 품질 관리자 (점수 기반 평가)
def node_review(state: WorkerState):
    print(f"      🔎 [{state['subject']}] 채점 품질 심사 중...")

    reviewer = llm.with_structured_output(ReviewResult)
    res = state["grade_result"]

    # 채점 결과 자체가 타당한지 점수(0~100)로 평가
    prompt = f"""
    당신은 수석 교사입니다. 아래 채점 결과가 논리적으로 타당한지 0~100점으로 평가하세요.
    
    [원본 문제/답안]
    과목: {state['subject']}
    답안: {state['student_answer']}
    
    [AI 교사의 채점]
    점수: {res.score}
    피드백: {res.feedback}
    
    채점이 정확하고 피드백이 적절하면 높은 점수(90 이상),
    오류가 있거나 피드백이 부실하면 낮은 점수를 부여하세요.
    """
    review = reviewer.invoke(prompt)

    print(f"      👉 품질 점수: {review.quality_score}점 / 코멘트: {review.critique}")
    return {"review_critique": review.critique, "last_quality_score": review.quality_score}

# [Node: Reporter] (New!) 결과 전송 브리지
def node_report(state: WorkerState):
    # 최종 확정된 grade_result를 리스트에 담아 반환 -> 메인 그래프로 병합됨
    return {"final_grades": [state["grade_result"]]}

# [Edge Logic] 점수 기반 루프 결정
def loop_decision(state: WorkerState):
    # 품질 점수를 가져옵니다 (node_review에서 state에 넣었다고 가정하거나, 직전 invoke 결과 활용)
    # 여기서는 편의상 node_review가 반환한 값을 state에 'last_quality_score'로 저장했다고 가정하고 꺼냅니다.
    # (실제 런타임에서는 ReviewResult를 state에 저장하는 것이 정석이나, 간단히 로직만 구현)

    # Review 단계에서 invoke한 결과가 state 업데이트에 반영되려면 State에 필드가 있어야 합니다.
    # 여기서는 간단히 review_critique 내용이나 별도 변수를 확인합니다.
    # *위 node_review에서 last_quality_score를 반환했으므로 state에 들어옵니다 (TypedDict에 추가 필요).*

    quality = state.get("last_quality_score", 0)

    # 기준: 품질 80점 이상이면 통과 OR 3번 시도했으면 강제 통과
    if quality >= 80 or state["retry_count"] >= 3:
        return "pass"
    else:
        return "retry"

# State에 품질 점수 필드 추가 (동적 업데이트를 위해)
WorkerState.__annotations__["last_quality_score"] = int

# [SubGraph Build]
worker_graph = StateGraph(WorkerState)
worker_graph.add_node("grade", node_grade)
worker_graph.add_node("review", node_review)
worker_graph.add_node("report", node_report) # 연결 고리 노드

worker_graph.add_edge(START, "grade")
worker_graph.add_edge("grade", "review")

worker_graph.add_conditional_edges(
    "review",
    loop_decision,
    {
        "retry": "grade", # 점수 미달 시 재채점
        "pass": "report"  # 통과 시 결과 포장 후 종료
    }
)
worker_graph.add_edge("report", END)

grading_worker = worker_graph.compile()


# -------------------------------------
# 3. Main Graph (Orchestrator) 정의
# -------------------------------------

# [Main State]
class MainState(TypedDict):
    raw_text: str
    parsed_sheets: List[AnswerSheet]
    # Reducer: 여러 Worker의 결과를 하나로 합침
    final_grades: Annotated[List[GradeResult], operator.add]
    final_report: str

# [Node: Parse]
def node_parse(state: MainState):
    print("\n🧐 [Head Teacher] 답안지 스캔 및 과목 분류 중...")
    parser = llm.with_structured_output(ParsedExam)
    result = parser.invoke(f"다음 내용을 과목별로 분리해줘:\n{state['raw_text']}")
    return {"parsed_sheets": result.sheets}

# [Node: Compile]
def node_compile(state: MainState):
    print("\n🖨️ [System] 최종 성적표 출력 중...")
    grades = state['final_grades']

    report = "=== 🏫 2026학년도 AI 서술형 평가 결과 ===\n"
    total_score = 0

    # 보기 좋게 정렬 (과목명 기준)
    sorted_grades = sorted(grades, key=lambda x: x.subject)

    for g in sorted_grades:
        icon = "✅" if g.score >= 60 else "⚠️" # 60점 기준 과락 표시
        report += f"\n{icon} [{g.subject}] {g.score}점\n   └ 피드백: {g.feedback}\n"
        total_score += g.score

    report += f"\n{'='*40}\n총점: {total_score} / {len(grades)*100} 점"
    return {"final_report": report}

# [Edge Logic: Map]
def map_workers(state: MainState):
    return [
        Send("grading_worker", {
            "subject": s.subject,
            "student_answer": s.student_answer,
            "retry_count": 0,
            "grade_result": None,
            "review_critique": None,
            "final_grades": [] # 초기화
        })
        for s in state['parsed_sheets']
    ]

# [Main Graph Build]
workflow = StateGraph(MainState)

workflow.add_node("parse", node_parse)
workflow.add_node("grading_worker", grading_worker) # 컴파일된 서브그래프 사용
workflow.add_node("compile", node_compile)

workflow.add_edge(START, "parse")
workflow.add_conditional_edges("parse", map_workers, ["grading_worker"])
workflow.add_edge("grading_worker", "compile")
workflow.add_edge("compile", END)

app = workflow.compile()


# -------------------------------------
# 4. 실행
# -------------------------------------

if __name__ == "__main__":
    print(f"📄 [제출된 답안지]\n{STUDENT_DRAFT}")
    print("-" * 50)

    # 초기 상태 주입
    inputs = {"raw_text": STUDENT_DRAFT, "final_grades": []}

    try:
        # 실행
        result = app.invoke(inputs)

        # 최종 결과 출력
        print("\n" + result["final_report"])

    except Exception as e:
        print(f"❌ Error: {e}")


# -------------------------------------
# [Visualization] Mermaid 그래프 출력
# -------------------------------------
print("="*50)
print("📊 [Mermaid Graph] 아래 코드를 https://mermaid.live/ 에 붙여넣으세요.")
print("="*50)
try:
    # xray=True를 해야 SubGraph(채점-검토 루프) 내부가 보입니다.
    print(app.get_graph(xray=True).draw_mermaid())
except Exception:
    print(app.get_graph().draw_mermaid())
print("="*50 + "\n")