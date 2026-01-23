import os
from typing import TypedDict, Literal
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

load_dotenv()

# 1. 모델 설정 (토큰 절약을 위해 Haiku 사용)
llm = ChatAnthropic(model="claude-3-haiku-20240307")

# 2. 라우터 스키마 정의
class Route(BaseModel):
    step: Literal["upper", "count", "summary"] = Field(
        description="작업 선택: 대문자(upper), 글자수(count), 요약(summary)"
    )

router_llm = llm.with_structured_output(Route)

# 3. State 정의
class State(TypedDict):
    input: str
    decision: str
    output: str
    is_valid: bool
    retry_count: int

# 4. 노드 함수 정의

def router_node(state: State):
    """사용자의 의도를 분석하여 경로 결정"""
    result = router_llm.invoke(state["input"])
    return {"decision": result.step, "retry_count": 0, "is_valid": False}

def upper_node(state: State):
    """모두 대문자로 변환"""
    return {"output": state["input"].upper()}

def count_node(state: State):
    """텍스트의 글자 수 계산 (공백 포함)"""
    return {"output": f"입력된 텍스트의 총 글자 수는 {len(state['input'])}자입니다."}

def summary_node(state: State):
    """3단어 요약 (루프 대상)"""
    current_retry = state.get("retry_count", 0)
    
    # 실패 횟수에 따라 AI에게 더 강력한 가이드 제공
    if current_retry == 0:
        prompt = f"다음 문장을 딱 3단어로만 요약해. 다른 말은 절대 하지마: {state['input']}"
    else:
        prompt = f"반드시 '딱 3단어'로만 다시 요약해! (현재 {current_retry}번 실패함): {state['input']}"
    
    result = llm.invoke(prompt)
    return {"output": result.content.strip(), "retry_count": current_retry + 1}

def checker_node(state: State):
    """파이썬 코드로 단어 수 검사 (토큰 0개)"""
    words = state["output"].split()
    is_ok = (len(words) == 3)
    # 루프 진행 상황을 보기 위한 중간 출력
    if not is_ok:
        print(f"   [검수 실패] 현재 결과: '{state['output']}' (단어 수: {len(words)}) -> 다시 시도 중...")
    return {"is_valid": is_ok}

# 5. 조건부 로직 (Edges)

def route_selection(state: State):
    if state["decision"] == "upper": return "upper_node"
    elif state["decision"] == "count": return "count_node"
    else: return "summary_node"

def check_loop(state: State):
    # 성공했거나 3번 시도했으면 종료
    if state["is_valid"] or state["retry_count"] >= 3:
        return END
    return "summary_node"

# 6. 그래프 빌드 및 컴파일
builder = StateGraph(State)

builder.add_node("router_node", router_node)
builder.add_node("upper_node", upper_node)
builder.add_node("count_node", count_node)
builder.add_node("summary_node", summary_node)
builder.add_node("checker_node", checker_node)

builder.add_edge(START, "router_node")

builder.add_conditional_edges(
    "router_node", 
    route_selection,
    {
        "upper_node": "upper_node", 
        "count_node": "count_node", 
        "summary_node": "summary_node"
    }
)

builder.add_edge("upper_node", END)
builder.add_edge("count_node", END)

# 요약 루프 연결
builder.add_edge("summary_node", "checker_node")
builder.add_conditional_edges(
    "checker_node", 
    check_loop,
    {END: END, "summary_node": "summary_node"}
)

app = builder.compile()

# --------------------------------------------------
# 7. 워크플로우 시각화 (Mermaid)
# --------------------------------------------------
print("\n" + "="*60)
print("Below is the Mermaid graph syntax. Paste it at https://mermaid.live/")
print("="*60)
print(app.get_graph().draw_mermaid())
print("="*60 + "\n")

# --------------------------------------------------
# 8. 전체 노드 시나리오 테스트 실행
# --------------------------------------------------
long_text = """
최근 오픈AI와 구글, 앤스로픽 등 글로벌 빅테크 기업들 사이에서 인공지능 모델의 성능 경쟁이 그 어느 때보다 치열하게 전개되고 있습니다. 
특히 대규모 언어 모델인 LLM은 단순한 텍스트 생성을 넘어 논리적 추론과 복잡한 코딩 능력까지 갖추게 되었으며, 
이제는 이미지와 음성을 동시에 이해하는 멀티모달 기능이 표준으로 자리 잡았습니다. 
이러한 기술적 진보는 의료, 금융, 교육 등 산업 전반에 걸쳐 혁신적인 변화를 불러일으키고 있지만, 
한편으로는 가짜 뉴스 확산이나 저작권 침해, 그리고 AI의 윤리적 가이드라인 마련과 같은 사회적 과제들도 동시에 던져주고 있습니다.
"""

test_inputs = [
    {"input": "make this uppercase: hello world", "label": "1. 대문자 변환 테스트"},
    {"input": "이 문장의 글자 수를 세어줘: " + long_text[:20], "label": "2. 글자 수 측정 테스트"},
    {"input": "다음 문장을 딱 3단어로 요약해줘: " + long_text, "label": "3. 3단어 요약 루프 테스트 (긴 텍스트)"}
]

print("🚀 테스트를 시작합니다.")

for test in test_inputs:
    print(f"\n▶ {test['label']}")
    # 개별 테스트를 위한 실행 (invoke)
    result = app.invoke({"input": test['input']})
    
    print(f"   - 선택된 작업: {result['decision']}")
    print(f"   - 최종 결과: {result['output']}")
    if result['decision'] == 'summary':
        status = "성공" if result['is_valid'] else "실패(횟수 초과)"
        print(f"   - 검수 결과: {status} (시도: {result['retry_count']}회)")
    print("-" * 40)