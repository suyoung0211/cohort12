import sqlite3
from typing import TypedDict, Literal, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.sqlite import SqliteSaver

# 1. 여행 상태 정의
class TravelState(TypedDict):
    destination: str
    travelers: int
    hotel: str
    total_price: int
    status: str 

# 2. 예약 툴 정의 (여기를 대폭 수정했습니다!)
def booking_tool(destination: str, travelers: int):
    """
    실제 예약을 진행하는 툴.
    중요: 사용자가 최종 '승인'을 할 때까지 함수가 끝나지 않고 내부에서 계속 돕니다.
    """
    # 초기 제안 값
    current_hotel = f"{destination} 그랜드 하얏트"
    current_price = travelers * 250000
    
    print(f"\n[Tool] {destination} 여행 패키지 생성 중...")

    # --- Tool 내부 루프 시작 (승인/거절 시에만 break) ---
    while True:
        # 툴 실행을 멈추고 사용자에게 확인 요청 (Interrupts in tools)
        user_decision = interrupt({
            "action": "confirm_booking",
            "details": {
                "destination": destination,
                "hotel": current_hotel,
                "travelers": travelers,
                "total_price": current_price
            },
            "message": f"호텔: {current_hotel} / 가격: {current_price}원\n이대로 진행할까요? (approve/edit/reject)"
        })
        
        # resume으로 받은 데이터 분석
        action = user_decision.get("action")
        
        if action == "approve":
            # 루프 종료 및 결과 반환
            return {
                "result": "success", 
                "hotel": current_hotel, 
                "total_price": current_price,
                "msg": "✅ 예약이 확정되었습니다!"
            }
        
        elif action == "edit":
            # 사용자가 수정한 데이터로 변수 업데이트
            print("\n[Tool] 🔄 내용을 수정하고 다시 검토를 요청합니다...")
            if "hotel" in user_decision:
                current_hotel = user_decision["hotel"]
                # 호텔이 바뀌면 가격도 바뀐다고 가정 (+5만원)
                current_price += 50000
            
            # return 하지 않고 while 문 처음으로 돌아가서 다시 interrupt!
            continue
            
        else: # reject
            return {"result": "cancelled", "msg": "❌ 사용자가 취소했습니다."}

# 3. 노드 정의
def validate_travelers_node(state: TravelState):
    num = state["travelers"]
    while True:
        if isinstance(num, int) and num > 0: break
        num = interrupt(f"⚠️ '{num}'명은 불가합니다. 인원(숫자)을 입력하세요.")
    return {"travelers": num}

def process_booking_node(state: TravelState):
    # 툴 실행 (툴 안에서 승인될 때까지 못 빠져나옴)
    res = booking_tool(state["destination"], state["travelers"])
    
    if res["result"] == "success":
        return {"status": "booked", "hotel": res["hotel"], "total_price": res["total_price"]}
    else:
        return {"status": "cancelled"}

# --- 4. 그래프 빌드 및 DB 연결 ---
builder = StateGraph(TravelState)
builder.add_node("validate", validate_travelers_node)
builder.add_node("booking", process_booking_node)

builder.add_edge(START, "validate")
builder.add_edge("validate", "booking")
builder.add_edge("booking", END)

# DB 파일 연결 (영구 저장)
conn = sqlite3.connect("travel_fixed.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)
graph = builder.compile(checkpointer=checkpointer)

# 5. 실행 로직 (재귀를 없애고 while 루프로 변경)
config = {"configurable": {"thread_id": "user_final_fix_1"}}

def run_graph(initial_input=None):
    current_input = initial_input
    
    while True:
        # stream 실행
        events = graph.stream(current_input, config, stream_mode="values")
        
        last_event = None
        interrupted = False
        
        for event in events:
            last_event = event
            if "__interrupt__" in event:
                interrupted = True
                content = event["__interrupt__"][0].value
                
                # (1) 인원수 검증 단계
                if isinstance(content, str):
                    print(f"\n[AI] {content}")
                    val = input("답변: ")
                    try:
                        current_input = Command(resume=int(val))
                    except ValueError:
                        print("숫자를 입력해주세요.")
                        current_input = Command(resume=0)
                    break # inner loop 탈출 -> while문 상단에서 resume 실행
                
                # (2) 툴 승인/수정 단계
                elif isinstance(content, dict):
                    print(f"\n──────────────────────────────")
                    print(f"[검토 요청] {content['message']}")
                    print(f"상세 내용: {content['details']}")
                    print(f"──────────────────────────────")
                    
                    action = input("선택 (approve/edit/reject): ").strip().lower()
                    
                    if action == "edit":
                        new_hotel = input("새로운 호텔 이름 입력: ")
                        current_input = Command(resume={"action": "edit", "hotel": new_hotel})
                    else:
                        current_input = Command(resume={"action": action})
                    break # inner loop 탈출
        
        # 더 이상 인터럽트가 없으면 최종 결과 반환
        if not interrupted:
            return last_event

# --- 실행부 ---
print("--- ✈️ AI 여행 예약 ---")

# 현재 DB 상태 확인
existing_state = graph.get_state(config)

if existing_state.next:
    print("💡 이전에 멈춘 지점부터 다시 시작합니다.")
    # 저장된 상태가 있으면 아무 인풋 없이 실행 (체크포인트가 알아서 resume 지점을 찾음)
    final = run_graph(None)
else:
    print("🆕 새로운 세션을 시작합니다.")
    start_input = {"destination": "제주도", "travelers": 0, "status": "searching"}
    final = run_graph(start_input)

if final:
    print(f"\n--- 최종 결과: {final.get('status')} ---")