import streamlit as st
import random
import json
import os
from copy import deepcopy
from filelock import FileLock

st.set_page_config(page_title="消費者行為大富翁｜多人共玩版", layout="wide")

# =========================================================
# 基本檔案設定
# =========================================================
STATE_FILE = "game_state.json"
LOCK_FILE = "game_state.lock"
HOST_PIN = "mlm0801"   # ← 這裡改成你自己的主持人密碼

with open("board.json", "r", encoding="utf-8") as f:
    BOARD = json.load(f)

with open("questions.json", "r", encoding="utf-8") as f:
    QUESTIONS = json.load(f)

with open("chance_cards.json", "r", encoding="utf-8") as f:
    CARD_DATA = json.load(f)
    CHANCE_CARDS = CARD_DATA["chance"]
    FATE_CARDS = CARD_DATA["fate"]

# =========================================================
# 常數
# =========================================================
NUM_GROUPS = 13
START_MONEY = 2000
PASS_START_BONUS = 200

GROUP_COLORS = [
    "#e53935", "#1e88e5", "#43a047", "#fdd835", "#8e24aa",
    "#fb8c00", "#00acc1", "#d81b60", "#6d4c41", "#546e7a",
    "#3949ab", "#7cb342", "#c0ca33"
]

GROUP_ICONS = [
    "🔴", "🔵", "🟢", "🟡", "🟣", "🟠", "🔷",
    "🌸", "🟤", "⚫", "💎", "🍏", "⭐"
]

# =========================================================
# 使用者本地 session
# =========================================================
if "role" not in st.session_state:
    st.session_state.role = None   # None / host / player

if "my_group" not in st.session_state:
    st.session_state.my_group = None

if "my_name" not in st.session_state:
    st.session_state.my_name = ""

# =========================================================
# 初始共享狀態
# =========================================================
def get_initial_state():
    return {
        "positions": [0] * NUM_GROUPS,
        "money": [START_MONEY] * NUM_GROUPS,
        "owner": [None] * len(BOARD),
        "turn": 0,
        "current_group": 0,
        "phase": "roll",  # roll / answer
        "current_question": None,
        "current_space": None,
        "last_roll": None,
        "last_message": "遊戲開始，請第 1 組擲骰。",
        "log": [],
        "game_over": False,
        "winner_group": None,
        "used_question_ids": [],
        "players": {},     # {"0": "王小明", ...}
        "host_name": ""
    }

def ensure_state_file():
    if not os.path.exists(STATE_FILE):
        with FileLock(LOCK_FILE):
            if not os.path.exists(STATE_FILE):
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(get_initial_state(), f, ensure_ascii=False, indent=2)

def load_state():
    ensure_state_file()
    with FileLock(LOCK_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

def save_state(state):
    with FileLock(LOCK_FILE):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

def update_state(mutator):
    with FileLock(LOCK_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        new_state = mutator(deepcopy(state))
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)
    return new_state

ensure_state_file()

# =========================================================
# 工具函式
# =========================================================
def next_group(g):
    return (g + 1) % NUM_GROUPS

def owned_count(state, g):
    return sum(1 for x in state["owner"] if x == g)

def add_log(state, text):
    state["log"].insert(0, text)
    state["log"] = state["log"][:80]
    return state

def all_brand_spaces_owned(state):
    for i, space in enumerate(BOARD):
        if space["type"] == "brand" and state["owner"][i] is None:
            return False
    return True

def available_questions(state):
    return [q for q in QUESTIONS if q["id"] not in state["used_question_ids"]]

def draw_question(state):
    pool = available_questions(state)
    if not pool:
        return None
    return random.choice(pool)

def draw_card(card_type):
    if card_type == "chance":
        return random.choice(CHANCE_CARDS)
    return random.choice(FATE_CARDS)


def reset_board_only():
    old = load_state()
    state = get_initial_state()
    state["players"] = old.get("players", {})
    state["host_name"] = old.get("host_name", "")
    save_state(state)

def reset_full_game():
    state = get_initial_state()
    save_state(state)

# =========================================================
# 身分 / 加入 / 離開
# =========================================================
def join_as_host(name, pin):
    if pin != HOST_PIN:
        return False

    def mutator(state):
        state["host_name"] = name.strip() if name.strip() else "主持人"
        return state

    update_state(mutator)
    st.session_state.role = "host"
    st.session_state.my_group = None
    st.session_state.my_name = name.strip() if name.strip() else "主持人"
    return True

def reclaim_host(pin):
    if pin != HOST_PIN:
        return False

    state = load_state()
    host_name = state.get("host_name", "").strip() or "主持人"
    st.session_state.role = "host"
    st.session_state.my_group = None
    st.session_state.my_name = host_name
    return True

def join_group(group_idx, name):
    def mutator(state):
        if str(group_idx) in state["players"]:
            return state
        state["players"][str(group_idx)] = name.strip() if name.strip() else f"第{group_idx+1}組代表"
        return state

    new_state = update_state(mutator)

    if str(group_idx) in new_state["players"]:
        joined_name = new_state["players"][str(group_idx)]
        st.session_state.role = "player"
        st.session_state.my_group = group_idx
        st.session_state.my_name = joined_name

def leave_current_role():
    if st.session_state.role == "player" and st.session_state.my_group is not None:
        group_idx = st.session_state.my_group

        def mutator(state):
            state["players"].pop(str(group_idx), None)
            return state

        update_state(mutator)

    st.session_state.role = None
    st.session_state.my_group = None
    st.session_state.my_name = ""

def is_group_taken(state, group_idx):
    return str(group_idx) in state["players"]

# =========================================================
# 共用遊戲流程
# =========================================================
def process_roll_shared(actor_group, allow_host=False):
    def mutator(state):
        if state["game_over"]:
            return state

        if state["phase"] != "roll":
            return state

        if not allow_host and state["current_group"] != actor_group:
            return state

        group_idx = state["current_group"]
        dice = random.randint(1, 6)
        old_pos = state["positions"][group_idx]
        new_pos = (old_pos + dice) % len(BOARD)

        if old_pos + dice >= len(BOARD):
            state["money"][group_idx] += PASS_START_BONUS
            add_log(state, f"第 {group_idx+1} 組通過起點，獲得 ${PASS_START_BONUS}")

        state["positions"][group_idx] = new_pos
        state["current_space"] = new_pos
        state["last_roll"] = dice

        space = BOARD[new_pos]

        if space["type"] == "start":
            state["phase"] = "roll"
            state["current_group"] = next_group(group_idx)
            state["current_question"] = None
            msg = f"第 {group_idx+1} 組擲出 {dice} 點，停在起點。下一組：第 {state['current_group']+1} 組。"
            state["last_message"] = msg
            add_log(state, msg)
            return state

        if space["type"] == "chance":
            card = draw_card("chance")
            state["money"][group_idx] += card["money"]
            state["phase"] = "roll"
            state["current_group"] = next_group(group_idx)
            state["current_question"] = None
            sign = "+" if card["money"] >= 0 else ""
            msg = (
                f"第 {group_idx+1} 組擲出 {dice} 點，來到【機會】。"
                f"{card['title']}：{card['text']}（{sign}${card['money']}）"
                f" 下一組：第 {state['current_group']+1} 組。"
            )
            state["last_message"] = msg
            add_log(state, msg)
            return state

        if space["type"] == "fate":
            card = draw_card("fate")
            state["money"][group_idx] += card["money"]
            state["phase"] = "roll"
            state["current_group"] = next_group(group_idx)
            state["current_question"] = None
            sign = "+" if card["money"] >= 0 else ""
            msg = (
                f"第 {group_idx+1} 組擲出 {dice} 點，來到【命運】。"
                f"{card['title']}：{card['text']}（{sign}${card['money']}）"
                f" 下一組：第 {state['current_group']+1} 組。"
            )
            state["last_message"] = msg
            add_log(state, msg)
            return state

        owner = state["owner"][new_pos]

        if owner is None:
            question = draw_question(state)

            if question is None:
                ranking = []
                for g in range(NUM_GROUPS):
                    ranking.append({
                        "group": g,
                        "owned": owned_count(state, g),
                        "money": state["money"][g]
                    })
                ranking.sort(key=lambda x: (x["owned"], x["money"]), reverse=True)
                state["winner_group"] = ranking[0]["group"]
                state["game_over"] = True
                state["phase"] = "roll"
                state["current_question"] = None
                msg = (
                    "所有可用題目都已答對過，遊戲結束！"
                    f" 冠軍是第 {state['winner_group']+1} 組。"
                )
                state["last_message"] = msg
                add_log(state, msg)
                return state

            state["phase"] = "answer"
            state["current_question"] = question
            msg = (
                f"第 {group_idx+1} 組擲出 {dice} 點，來到【{space['name']}】。"
                f" 此格尚未被佔領，請回答題目。答對可佔領；答錯支付固定過路費 ${space['toll']}。"
            )
            state["last_message"] = msg
            add_log(state, msg)
            return state

        if owner == group_idx:
            state["phase"] = "roll"
            state["current_group"] = next_group(group_idx)
            state["current_question"] = None
            msg = (
                f"第 {group_idx+1} 組擲出 {dice} 點，來到自己的【{space['name']}】。"
                f" 安全通過，下一組：第 {state['current_group']+1} 組。"
            )
            state["last_message"] = msg
            add_log(state, msg)
            return state

        toll = space["toll"]
        state["money"][group_idx] -= toll
        state["money"][owner] += toll
        state["phase"] = "roll"
        state["current_group"] = next_group(group_idx)
        state["current_question"] = None
        msg = (
            f"第 {group_idx+1} 組擲出 {dice} 點，來到第 {owner+1} 組已佔領的【{space['name']}】。"
            f" 不可再搶佔，直接支付固定過路費 ${toll}。下一組：第 {state['current_group']+1} 組。"
        )
        state["last_message"] = msg
        add_log(state, msg)
        return state

    return update_state(mutator)

def process_answer_shared(actor_group, selected_idx, allow_host=False):
    def mutator(state):
        if state["game_over"]:
            return state

        if state["phase"] != "answer":
            return state

        if not allow_host and state["current_group"] != actor_group:
            return state

        group_idx = state["current_group"]
        q = state["current_question"]
        if q is None:
            return state

        pos = state["current_space"]
        space = BOARD[pos]

        if selected_idx == q["answer"]:
            state["owner"][pos] = group_idx
            if q["id"] not in state["used_question_ids"]:
                state["used_question_ids"].append(q["id"])
            msg = (
                f"第 {group_idx+1} 組回答正確，成功佔領【{space['name']}】。"
                f" 理論概念：{q['concept']}。"
            )
        else:
            toll = space["toll"]
            state["money"][group_idx] -= toll
            correct = q["options"][q["answer"]]
            msg = (
                f"第 {group_idx+1} 組回答錯誤，支付固定過路費 ${toll}。"
                f" 正確答案：{correct}。理論概念：{q['concept']}。"
            )

        state["current_question"] = None
        state["current_space"] = None

        if all_brand_spaces_owned(state):
            state["game_over"] = True
            ranking = []
            for g in range(NUM_GROUPS):
                ranking.append({
                    "group": g,
                    "owned": owned_count(state, g),
                    "money": state["money"][g]
                })
            ranking.sort(key=lambda x: (x["owned"], x["money"]), reverse=True)
            state["winner_group"] = ranking[0]["group"]
            state["last_message"] = (
                f"所有品牌地都已被佔領，遊戲結束！"
                f" 冠軍是第 {state['winner_group']+1} 組。"
            )
            add_log(state, state["last_message"])
        else:
            state["phase"] = "roll"
            state["current_group"] = next_group(group_idx)
            state["turn"] += 1
            state["last_message"] = msg + f" 下一組：第 {state['current_group']+1} 組。"
            add_log(state, state["last_message"])

        return state

    return update_state(mutator)

# =========================================================
# 棋盤顯示
# =========================================================
def render_cell_html(state, idx):
    space = BOARD[idx]
    owner = state["owner"][idx]
    tokens_here = [g for g, p in enumerate(state["positions"]) if p == idx]

    bg = "#ffffff"
    border = "#cfd8dc"

    if space["type"] == "start":
        bg = "#fff8e1"
        border = "#ffb300"
    elif space["type"] == "chance":
        bg = "#e3f2fd"
        border = "#42a5f5"
    elif space["type"] == "fate":
        bg = "#fce4ec"
        border = "#ec407a"
    else:
        bg = "#f8f9fa"

    lines = []
    lines.append(f'<div style="font-size:11px;color:#607d8b;font-weight:700;">#{idx}</div>')
    lines.append(f'<div style="font-size:15px;font-weight:800;line-height:1.15;margin:2px 0 4px 0;">{space["name"]}</div>')
    lines.append(f'<div style="font-size:11px;color:#78909c;">{space["category"]}</div>')

    if space["type"] == "brand":
        lines.append(f'<div style="font-size:11px;color:#455a64;">過路費 ${space["toll"]}</div>')

    if owner is not None:
        lines.append(f'<div style="font-size:11px;font-weight:700;color:{GROUP_COLORS[owner]};">🚩 第{owner+1}組</div>')

    if tokens_here:
        token_html = "".join(
            f'<span style="margin-right:3px;font-size:16px;">{GROUP_ICONS[g]}</span>'
            for g in tokens_here
        )
        lines.append(f'<div style="margin-top:auto;min-height:22px;white-space:nowrap;overflow:hidden;">{token_html}</div>')
    else:
        lines.append('<div style="margin-top:auto;min-height:22px;"></div>')

    inner_html = "".join(lines)

    return f"""
    <div style="
        height:130px;
        border:2px solid {border};
        background:{bg};
        border-radius:12px;
        padding:8px;
        box-sizing:border-box;
        overflow:hidden;
        display:flex;
        flex-direction:column;
        justify-content:flex-start;
    ">
        {inner_html}
    </div>
    """

def render_board(state):
    size = 11
    coords = []

    for c in range(size):
        coords.append((0, c))
    for r in range(1, size - 1):
        coords.append((r, size - 1))
    for c in range(size - 1, -1, -1):
        coords.append((size - 1, c))
    for r in range(size - 2, 0, -1):
        coords.append((r, 0))

    grid = [["" for _ in range(size)] for _ in range(size)]

    for i in range(len(BOARD)):
        r, c = coords[i]
        grid[r][c] = render_cell_html(state, i)

    current_group = state["current_group"]
    phase_text = "擲骰" if state["phase"] == "roll" else "答題"

    center_html = f"""
    <div style="
        height:100%;
        border:2px dashed #90a4ae;
        border-radius:18px;
        background:linear-gradient(135deg,#fff3e0,#e3f2fd);
        display:flex;
        align-items:center;
        justify-content:center;
        text-align:center;
        flex-direction:column;
        padding:20px;
        box-sizing:border-box;
    ">
        <div style="font-size:30px;font-weight:900;">🎲 消費者行為大富翁｜課堂版</div>
        <div style="font-size:15px;color:#455a64;margin-top:8px;">主持人可重新接管＋學生鎖組版</div>
        <div style="margin-top:18px;font-size:20px;font-weight:800;">目前回合：第 {current_group+1} 組</div>
        <div style="margin-top:6px;font-size:18px;color:#5c6bc0;font-weight:700;">目前階段：{phase_text}</div>
        <div style="margin-top:10px;font-size:15px;color:#546e7a;max-width:80%;">
            {state["last_message"]}
        </div>
    </div>
    """

    html = """
    <style>
    .board-wrap {
        display:grid;
        grid-template-columns: repeat(11, minmax(70px, 1fr));
        gap:8px;
        width:100%;
    }
    .board-center {
        grid-column:2 / span 9;
        grid-row:2 / span 9;
    }
    </style>
    <div class="board-wrap">
    """

    for r in range(size):
        for c in range(size):
            if 1 <= r <= 9 and 1 <= c <= 9:
                if r == 1 and c == 1:
                    html += f'<div class="board-center">{center_html}</div>'
                else:
                    continue
            else:
                html += grid[r][c] if grid[r][c] else "<div></div>"

    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)

# =========================================================
# 主畫面
# =========================================================
state = load_state()
role = st.session_state.role
my_group = st.session_state.my_group

st.title("🎲 消費者行為大富翁｜多人共玩版")

t1, t2, t3, t4 = st.columns([1, 1, 1, 3])
with t1:
    st.metric("目前回合", f"第 {state['current_group']+1} 組")
with t2:
    st.metric("目前階段", "擲骰" if state["phase"] == "roll" else "答題")
with t3:
    st.metric("已答對題數", len(state["used_question_ids"]))
with t4:
    st.info(state["last_message"])

# =========================================================
# 側邊欄
# =========================================================
with st.sidebar:
    st.subheader("登入身分")

    if role is None:
        login_mode = st.radio("請選擇身分", ["主持人", "學生代表"])
        name_input = st.text_input("名稱（可不填）", value="")

        if login_mode == "主持人":
            host_pin_input = st.text_input("請輸入主持人 PIN", type="password")
            if st.button("🎤 以主持人身分進入", type="primary", use_container_width=True):
                ok = join_as_host(name_input, host_pin_input)
                if ok:
                    st.rerun()
                else:
                    st.error("主持人 PIN 錯誤，無法登入主持人模式。")
        else:
            available_labels = []
            available_map = {}

            for i in range(NUM_GROUPS):
                if is_group_taken(state, i):
                    continue
                label = f"第 {i+1} 組"
                available_labels.append(label)
                available_map[label] = i

            if available_labels:
                selected_label = st.selectbox("選擇你的組別", available_labels)
                selected_group = available_map[selected_label]

                if st.button("✅ 加入這一組", type="primary", use_container_width=True):
                    join_group(selected_group, name_input)
                    st.rerun()
            else:
                st.warning("所有組別都已被選走。")
    else:
        if role == "host":
            st.success("你目前身分：主持人")

            st.info("主持人控制台")

            if st.button("♻️ 重設盤面（保留組別）", use_container_width=True):
            reset_board_only()
            st.rerun()

            if st.button("🧹 完全重開新局（清空組別）", type="primary", use_container_width=True):
            reset_full_game()
            st.rerun()

        elif role == "player" and my_group is not None:
            st.success(f"你目前身分：第 {my_group+1} 組 {GROUP_ICONS[my_group]}")

        if st.session_state.my_name:
            st.caption(f"名稱：{st.session_state.my_name}")

        if st.button("🚪 離開目前身分", use_container_width=True):
            leave_current_role()
            st.rerun()

    st.markdown("---")
    st.subheader("主持人重新接管")

    reclaim_pin_input = st.text_input("重新接管請輸入主持人 PIN", type="password", key="reclaim_host_pin")
    if st.button("🔑 重新接管主持人權限", use_container_width=True):
        ok = reclaim_host(reclaim_pin_input)
        if ok:
            st.success("已重新取得主持人權限。")
            st.rerun()
        else:
            st.error("PIN 錯誤，無法重新接管。")

st.markdown("---")
st.subheader("控制台")

host_can_control = role == "host"
player_can_control = (
    role == "player"
    and my_group is not None
    and state["current_group"] == my_group
)

if role == "host":
    st.info("主持人控制台")

    if st.button("♻️ 重設盤面（保留組別）", use_container_width=True):
        reset_board_only()
        st.rerun()

    if st.button("🧹 完全重開新局（清空組別）", type="primary", use_container_width=True):
        reset_full_game()
        st.rerun()

st.markdown("---")
st.subheader("目前操作權")

if state["game_over"]:
    st.error("遊戲已結束")
else:
    st.info(f"現在輪到第 {state['current_group']+1} 組")

    can_roll = (
        not state["game_over"]
        and state["phase"] == "roll"
        and (player_can_control or host_can_control)
    )

    if can_roll:
        roll_label = "🎲 擲骰"
        if role == "host":
            roll_label = f"🎲 代第 {state['current_group']+1} 組擲骰"

        if st.button(roll_label, type="primary", use_container_width=True):
            process_roll_shared(my_group, allow_host=(role == "host"))
            st.rerun()

    can_answer = (
        not state["game_over"]
        and state["phase"] == "answer"
        and state["current_question"] is not None
        and (player_can_control or host_can_control)
    )

    if can_answer:
        q = state["current_question"]
        pos = state["current_space"]
        space = BOARD[pos]

        st.warning(f"目前所在格：{space['name']}")
        st.caption(f"題目 ID：{q['id']}")
        st.caption(f"答對可佔領；答錯支付固定過路費 ${space['toll']}")
        st.markdown("### 題目")
        st.write(q["question"])

        answer_choice = st.radio(
            "請選擇答案",
            q["options"],
            key=f"answer_{role}_{state['turn']}_{state['current_group']}"
        )

        submit_label = "✅ 提交答案"
        if role == "host":
            submit_label = f"✅ 代第 {state['current_group']+1} 組提交答案"

        if st.button(submit_label, type="primary", use_container_width=True):
            selected_idx = q["options"].index(answer_choice)
            process_answer_shared(my_group, selected_idx, allow_host=(role == "host"))
            st.rerun()

    st.markdown("---")
    st.subheader("已加入組別")
    for i in range(NUM_GROUPS):
        if str(i) in state["players"]:
            st.caption(f"第 {i+1} 組：{state['players'][str(i)]}")
        else:
            st.caption(f"第 {i+1} 組：未加入")

    if state.get("host_name"):
        st.caption(f"主持人：{state['host_name']}")

# =========================================================
# 遊戲結束提示
# =========================================================
if state["game_over"] and state["winner_group"] is not None:
    st.success(f"🏁 遊戲結束！冠軍是第 {state['winner_group']+1} 組 {GROUP_ICONS[state['winner_group']]}")

# =========================================================
# 主畫面內容
# =========================================================
left, right = st.columns([2.2, 1], gap="large")

with left:
    st.subheader("棋盤")
    render_board(state)

with right:
    st.subheader("即時排行榜")

    ranking = []
    for g in range(NUM_GROUPS):
        ranking.append({
            "group": g,
            "owned": owned_count(state, g),
            "money": state["money"][g],
            "position": state["positions"][g]
        })
    ranking.sort(key=lambda x: (x["owned"], x["money"]), reverse=True)

    for idx, item in enumerate(ranking, start=1):
        g = item["group"]
        rep = state["players"].get(str(g), "未加入")
        st.markdown(
            f"""
            <div style="
                border:1px solid #e0e0e0;
                border-radius:12px;
                padding:10px 12px;
                margin-bottom:8px;
                background:linear-gradient(90deg,{GROUP_COLORS[g]}18,white);
            ">
                <div style="font-weight:900;">#{idx} 第 {g+1} 組 {GROUP_ICONS[g]}</div>
                <div>👤 代表：{rep}</div>
                <div>💰 現金：${item['money']}</div>
                <div>🚩 佔領：{item['owned']}</div>
                <div>📍 位置：{item['position']}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.subheader("最新紀錄")
    for line in state["log"][:15]:
        st.caption(line)

with st.expander("規則說明"):
    st.markdown("""
- 主持人可單獨登入，不屬於任何一組
- 主持人可用 PIN 隨時重新接管權限
- 學生代表需先選擇組別
- 某組一旦被一位學生選走，其他人就不能再選同一組
- 只有輪到的組別能操作；主持人可在必要時代操作
- 題目從尚未被答對過的題庫中抽出
- 題目答對後，不會再重複出現
- 所有品牌地都被佔領，或所有可用題目都已答對過時，遊戲結束
- 排名先比佔領格數，再比現金
    """)