# 이 코드는 LangGraph의 심화 패턴들을 종합적으로 학습하기 위한 예제입니다.
#
# [핵심 기능 요약]
# 1. **Router (라우터)**: 질문과 답안을 분석하여 '역사' 또는 '수학' 과목으로 자동 분류합니다.
# 2. **Parallel Execution (병렬 처리)**: '역사' 과목일 경우, 채점/오답노트/암기팁 3가지 작업을 동시에 수행합니다.
# 3. **Evaluator-Optimizer (평가-최적화)**: '수학' 과목일 경우, 채점 결과가 논리적인지 평가하고 부족하면 스스로 개선(Loop)합니다.
# 4. **Quota Management (토큰/쿼터 관리)**: 무료 API의 호출 제한을 피하기 위해 실행 간 대기 시간을 둡니다.

import os
import time
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from typing_extensions import TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from langchain.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

load_dotenv()
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")

# --- 상태(State) 정의 ---
class GradingState(TypedDict):
    question: str
    student_answer: str
    subject: str
    grade: str
    review_note: str
    extra_content: str
    retry_count: int
    quality_status: str
    critique: str

# ============================================================
# [핵심 기능 1] Router (라우터) 정의
# ============================================================
class SubjectRouter(BaseModel):
    subject: Literal["history", "math"] = Field(..., description="history 또는 math 중 선택")

router_llm = llm.with_structured_output(SubjectRouter)

# ============================================================
# [핵심 기능 3] Evaluator (평가자) 정의
# ============================================================
class FeedbackQuality(BaseModel):
    status: Literal["PASS", "FAIL"] = Field(..., description="채점 결과가 정확하고 오류 분석이 포함되었으면 PASS, 아니면 FAIL")
    critique: str = Field(..., description="FAIL인 경우, 누락된 분석이나 부정확한 부분을 구체적으로 지적")

evaluator_llm = llm.with_structured_output(FeedbackQuality)


# --- 노드(Node) 정의 ---

def route_subject(state: GradingState):
    return {
        "subject": router_llm.invoke(f"질문: {state['question']}\n답안: {state['student_answer']}").subject,
        "retry_count": 0
    }

# ============================================================
# [핵심 기능 2] Parallel Execution (병렬 처리) 노드들
# ============================================================
def history_grade(state: GradingState):
    return {"grade": llm.invoke(f"역사 채점: {state['student_answer']}").content}

def history_review(state: GradingState):
    return {"review_note": llm.invoke(f"역사 오답노트: {state['student_answer']}").content}

def history_tip(state: GradingState):
    return {"extra_content": llm.invoke(f"역사 암기팁: {state['question']}").content}

# ============================================================
# [핵심 기능 3] Optimizer (최적화) - 생성자(Generator)
# ============================================================
def generate_math_feedback(state: GradingState):
    print(f"   -> [수학] 채점 결과 생성 중... (시도: {state['retry_count'] + 1})")
    
    prompt = f"""
    당신은 엄격한 수학 선생님입니다. 학생의 답안을 채점하세요.
    [문제]: {state['question']}
    [학생 답안]: {state['student_answer']}
    다음 내용을 반드시 포함하세요:
    1. 정답 여부 (정답/오답)
    2. 학생 풀이 과정의 구체적인 오류 지적 (만약 오답이라면)
    3. 올바른 풀이 과정 제시
    """
    
    if state.get("critique"):
        prompt += f"\n\n[이전 채점에 대한 지적사항]: {state['critique']}\n위 지적을 반영하여 채점 결과를 보완/수정하세요."
        
    result = llm.invoke(prompt)
    return {"grade": result.content, "retry_count": state["retry_count"] + 1}

# ============================================================
# [핵심 기능 3] Evaluator (평가자) - 검증 노드
# ============================================================
def evaluate_math_feedback(state: GradingState):
    print("   -> [수학] 채점 품질 평가 중...")
    
    prompt = f"""
    다음 AI 조교의 채점 결과가 적절한지 평가하세요.
    [문제]: {state['question']}
    [학생 답안]: {state['student_answer']}
    [AI 채점 결과]: {state['grade']}
    
    [평가 기준]:
    1. 정답/오답 판정이 정확한가?
    2. 오류 원인을 정확히 짚어냈는가?
    3. 정답 풀이가 포함되어 있는가?
    """
    eval_result = evaluator_llm.invoke(prompt)
    
    return {
        "quality_status": eval_result.status,
        "critique": eval_result.critique
    }

# --- 엣지(Edge) 로직 ---

def route_decision(state: GradingState):
    if state["subject"] == "history":
        return ["history_grade", "history_review", "history_tip"]
    else:
        return "generate_math_feedback"

def check_quality_loop(state: GradingState):
    if state["quality_status"] == "PASS" or state["retry_count"] >= 3:
        if state["quality_status"] == "FAIL":
            print("   -> [Loop] 최대 재시도 초과. 현재 결과로 종료.")
        else:
            print("   -> [Loop] 품질 통과! (PASS)")
        return END
    
    print(f"   -> [Loop] 품질 미달: '{state['critique']}' -> 다시 작성합니다.")
    return "generate_math_feedback"

# --- 그래프 구성 ---
workflow = StateGraph(GradingState)

workflow.add_node("route_subject", route_subject)
workflow.add_node("history_grade", history_grade)
workflow.add_node("history_review", history_review)
workflow.add_node("history_tip", history_tip)
workflow.add_node("generate_math_feedback", generate_math_feedback)
workflow.add_node("evaluate_math_feedback", evaluate_math_feedback)

workflow.set_entry_point("route_subject")

workflow.add_conditional_edges(
    "route_subject",
    route_decision,
    {
        "history_grade": "history_grade",
        "history_review": "history_review",
        "history_tip": "history_tip",
        "generate_math_feedback": "generate_math_feedback"
    }
)

workflow.add_edge("history_grade", END)
workflow.add_edge("history_review", END)
workflow.add_edge("history_tip", END)

workflow.add_edge("generate_math_feedback", "evaluate_math_feedback")
workflow.add_conditional_edges(
    "evaluate_math_feedback",
    check_quality_loop,
    {
        "generate_math_feedback": "generate_math_feedback",
        END: END
    }
)

app = workflow.compile()

# --- 실행 및 테스트 ---

test_cases = [
    {
        "name": "CASE 1: 역사 (병렬 처리 확인)",
        "question": "임진왜란이 일어난 연도와 그 결과는?",
        "answer": "1592년에 일어났고, 조선 국토가 황폐화되었다."
    },
    {
        "name": "CASE 2: 수학 (모범 답안)",
        "question": "이차방정식 x^2 - 5x + 6 = 0 의 해를 구하시오.",
        "answer": "인수분해하면 (x-2)(x-3)=0 이므로 x=2 또는 x=3 입니다."
    },
    {
        "name": "CASE 3: 수학 (오답 -> 피드백 루프 확인)",
        "question": "이차방정식 x^2 - 5x + 6 = 0 의 해를 구하시오.",
        "answer": "잘 모르겠어요. 그냥 1 아닐까요?"
    }
]

print("--- [LangGraph 심화 패턴 검증 시작] ---\n")

for i, case in enumerate(test_cases):
    print(f"=== [{case['name']}] 실행 중... ===")
    
    if i > 0:
        print("   (API 쿼터 회복을 위해 60초 대기 중...)")
        time.sleep(60)

    try:
        result = app.invoke({
            "question": case['question'],
            "student_answer": case['answer']
        })

        print(f"\n[결과 확인]")
        print(f"▶ 분류된 과목: {result['subject']}")
        
        if result['subject'] == 'history':
            print("▶ 실행 패턴: 병렬 처리 (Parallel)")
            print(f"- 채점: {result.get('grade')[:50]}...")
            print(f"- 오답노트: {result.get('review_note')[:50]}...")
            print(f"- 암기팁: {result.get('extra_content')[:50]}...")
        elif result['subject'] == 'math':
            print("▶ 실행 패턴: 평가-최적화 (Evaluator-Optimizer)")
            print(f"- 시도 횟수: {result['retry_count']}")
            print(f"- 품질 상태: {result.get('quality_status')}")
            print(f"- 최종 피드백:\n{result['grade'][:200]}...")
            
    except Exception as e:
        error_msg = str(e)
        # [핵심 기능 4] Quota Management: 에러 메시지 내용을 확인하여 처리
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            print("\n[ERROR] Google API 쿼터(사용량 제한)가 초과되었습니다.")
            print("무료 플랜(Free Tier)은 분당/일일 요청 횟수에 제한이 있습니다.")
            print("잠시 후 다시 실행하거나, 내일 다시 시도해주세요.")
            break
        else:
            print(f"\n[ERROR] 알 수 없는 오류 발생: {e}")
    
    print("-" * 60 + "\n")
