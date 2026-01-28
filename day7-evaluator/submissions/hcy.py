#기본 설정
import os
from dotenv import load_dotenv
load_dotenv()

#-------------------------------------
#모델 설정
#-------------------------------------
from langchain_anthropic import ChatAnthropic
llm_writer = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    temperature=0.9
)

llm_judge = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    temperature=0.0
)

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field
from typing import Literal #주어진 보기 안에서 선택하도록 강제

#-------------------------------------
#Evaluator-optimizer(평가-개선 루프) *예제와 다르게 개선 루프 3회 제한
#-------------------------------------
# Graph state

class State(TypedDict):
    email: str
    topic: str
    feedback: str
    polite_or_not: str
    attempts: int  # 개선 시도 횟수 카운터


# 평가 결과를 구조화할 스키마(Feedback)
class Feedback(BaseModel):
    # evaluator의 출력 형식을 강제로 고정
    grade: Literal["perfect", "needs_revision"] = Field(
        description="Decide if the email is polite and not too personal.",
    )
    feedback: str = Field(
        description="If the email needs revision, provide specific advice on how to make it more professional (e.g., remove TMI, be more polite).",
    )


# evaluator(평가 LLM) 만들기
evaluator = llm_judge.with_structured_output(Feedback)


# 노드 1: llm_call_generator (생성기)
def llm_call_generator(state: State):
    """LLM으로 교수님께 이메일 쓰기:D"""

    # 시도 횟수 카운트 (없으면 0으로 시작)
    current_attempts = state.get("attempts") or 0
    new_attempts = current_attempts + 1

    if state.get("feedback"):
        prompt = f"""
        Write an email to a professor about: '{state['topic']}'.
        However, you MUST fix the previous version based on this feedback: {state['feedback']}
        Write the email in Korean.
        """
        msg = llm_writer.invoke(prompt)
    else:
        prompt = f"Write an email to a professor about: '{state['topic']}'. Write it in Korean."
        msg = llm_writer.invoke(prompt)

    # 어떤 내용을 생성했는지 출력
    print(f"[GENERATE] Email 시도 {new_attempts}: {msg.content[:300]}\n")

    return {"email": msg.content, "attempts": new_attempts}


# 노드 2: llm_call_evaluator (평가자)
def llm_call_evaluator(state: State):
    """LLM evaluates the email"""

    prompt = f"""
        You are a strict etiquette coach. Evaluate the following email draft.
        
        [Criteria]
        1. Is it formal and polite?
        2. Does it avoid TMI (Too Much Information) like personal health issues (diarrhea, vomiting, etc.)?
        3. Is it concise?
        
        If it violates any of these, give a grade of 'needs_revision' and tell them exactly what to remove.
        
        Email Draft:
        {state['email']}
        """

    grade = evaluator.invoke(prompt)

    # 어떤 내용을 평가했는지 출력
    print(f"[EVALUATE] 평가 결과 {state['attempts']}: {grade.grade}\n")
    print(f"[FEEDBACK] 조언: {grade.feedback}\n")

    return {"polite_or_not": grade.grade, "feedback": grade.feedback}


# 라우팅 함수
def route_email(state: State):
    """Route back to email generator or end based upon feedback from the evaluator"""

    if state["polite_or_not"] == "perfect":
        print("[END] 이 정도면 교수님께 바로 보내도 될 듯")

        return "Accepted"
    elif state["polite_or_not"] == "needs_revision":
        # 3회 이상 시도했다면 여기서 멈춤 (Accepted 리턴 -> END)
        if state.get("attempts", 0) >= 3:
            print("[END] 3번 고쳐서 안 되면 노답이다 걍 보내자")
            return "Accepted"

        print("[LOOP] 개선 피드백 반영하여 재시도")
        return "Rejected + Feedback"


# Build workflow
optimizer_builder = StateGraph(State)

# Add the nodes
optimizer_builder.add_node("llm_call_generator", llm_call_generator)
optimizer_builder.add_node("llm_call_evaluator", llm_call_evaluator)

# Add edges to connect nodes
optimizer_builder.add_edge(START, "llm_call_generator")
optimizer_builder.add_edge("llm_call_generator", "llm_call_evaluator")
optimizer_builder.add_conditional_edges(
    "llm_call_evaluator",
    route_email,
    {  # Name returned by route_joke : Name of next node to visit
        "Accepted": END,
        "Rejected + Feedback": "llm_call_generator",
    },
)

# Compile the workflow
optimizer_workflow = optimizer_builder.compile()

# Show the workflow
print("Here is the mermaid graph syntax. You can paste it into https://mermaid.live/ :") #사이트 들어가서 코드 붙여넣기
print(optimizer_workflow.get_graph(xray=True).draw_mermaid())

# Invoke
state = optimizer_workflow.invoke({"topic": "어제 엽떡 먹고 설사하느라 다음 수업 안 가고 싶어요ㅠ"})
print(state["email"])