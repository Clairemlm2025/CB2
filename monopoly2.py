import streamlit as st
import random
import json
import time
import os
from copy import deepcopy
from filelock import FileLock

st.set_page_config(page_title="消費者行為大富翁｜多人版", layout="wide")

# =========================================================
# 基本檔案設定
# =========================================================
STATE_FILE = "game_state.json"
LOCK_FILE = "game_state.lock"

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
# 使用者本地 session（只存登入組別，不存遊戲本體）
# =========================================================
if "my_group" not in st.session_state:
    st.session_state.my_group = None

if "my_name" not in st.session_state:
    st.session_state.my_name = ""

# =========================================================
# 建立初始共享遊戲狀態
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
        "players": {},  # {"0": "王小明", "1": "李小華"}
        "host_group": 0
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
    return [
        q for q in QUESTIONS
        if q["id"] not in state["used_question_ids"]
    ]

def draw_question(state):
    pool = available_questions(state)
    if not pool:
        return None
    return random.choice(pool)

def draw_card(card_type):
    if card_type == "chance":
        return random.choice(CHANCE_CARDS)
    return random.choice(FATE_CARDS)

def reset_game_state():
    state = get_initial_state()
    # 保留已加入玩家名稱
    old = load_state()
    state["players"] = old.get("players", {})
    state["host_group"] = old.get("host_group", 0)
    save_state(state)

# =========================================================
# 共用遊戲流程
# =========================================================
def process_roll_shared(group_idx):
    def mutator(state):
        if state["game_over"]:
            return state

        if state["phase"] != "roll":
            return state

        if state["current_group"] != group_idx:
            return state

        dice = random.randint(1, 6)
        old_pos = state["positions"][group_idx]
        new_pos = (old_pos + dice) % len(BOARD)

        # 通過起點
        if old_pos + dice >= len(BOARD):
            state["money"][group_idx] += PASS_START_BONUS
            add_log(state, f"第 {group_idx+1} 組通過起點，獲得 ${PASS_START_BONUS}")

        state["positions"][group_idx] = new_pos
        state["current_space"] = new_pos
        state["last_roll"] = dice

        space = BOARD[new_pos]

        # 起點
        if space["type"] == "start":
            state["phase"] = "roll"
            state["current_group"] = next_group(group_idx)
            state["current_question"] = None
            msg = f"第 {group_idx+1} 組擲出 {dice} 點，停在起點。下一組：第 {state['current_group']+1} 組。"
            state["last_message"] = msg
            add_log(state, msg)
            return state

        # 機會
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

        # 命運
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

        # 品牌格
        owner = state["owner"][new_pos]

        # 尚未被佔領：出題
        if owner is None:
            question = draw_question(state)

            # 題庫用完，直接結束
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

        # 自己的地
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

        # 別人的地
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

def process_answer_shared(group_idx, selected_idx):
    def mutator(state):
        if state["game_over"]:
            return state

        if state["phase"] != "answer":
            return state

        if state["current_group"] != group_idx:
            return state

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
            state["last_message"] = msg + f" 下一組：第 {state['current_group']+1} 組。"
            add_log(state, state["last_message"])

        return state

    return update_state(mutator)

# =========================================================
# 玩家加入 / 登記組別
# =========================================================
def join_group(group_idx, name):
    def mutator(state):
        state["players"][str(group_idx)] = name if name.strip() else f"第{group_idx+1}組代表"
        return state
    update_state(mutator)
    st.session_state.my_group = group_idx
    st.session_state.my_name = name if name.strip() else f"第{group_idx+1}組代表"

def leave_group():
    st.session_state.my_group = None
    st.session_state.my_name = ""

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
        <div style="font-size:30px;font-weight:900;">🎲 消費者行為大富翁｜多人版</div>
        <div style="font-size:15px;color:#455a64;margin-top:8px;">同一網址・同一局遊戲・輪到才可操作</div>
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
# 頁面
# =========================================================
state = load_state()
my_group = st.session_state.my_group

st.title("🎲 消費者行為大富翁｜多人共玩版")

top1, top2, top3, top4 = st.columns([1, 1, 1, 3])
with top1:
    st.metric("目前回合", f"第 {state['current_group']+1} 組")
with top2:
    st.metric("目前階段", "擲骰" if state["phase"] == "roll" else "答題")
with top3:
    st.metric("已答對題數", len(state["used_question_ids"]))
with top4:
    st.info(state["last_message"])

# =========================================================
# 側邊欄：加入組別 / 控制區
# =========================================================
with st.sidebar:
    st.subheader("玩家登入")

    if my_group is None:
        name_input = st.text_input("你的名字（可不填）", value="")
        group_options = [f"第 {i+1} 組" for i in range(NUM_GROUPS)]
        selected_group_label = st.selectbox("選擇你的組別", group_options)
        selected_group = group_options.index(selected_group_label)

        occupied_by = state["players"].get(str(selected_group))
        if occupied_by:
            st.warning(f"此組目前登記代表：{occupied_by}")

        if st.button("✅ 加入這一組", type="primary", use_container_width=True):
            join_group(selected_group, name_input)
            st.rerun()
    else:
        st.success(f"你目前是：第 {my_group+1} 組 {GROUP_ICONS[my_group]}")
        if st.session_state.my_name:
            st.caption(f"名稱：{st.session_state.my_name}")

        if st.button("🚪 離開目前組別", use_container_width=True):
            leave_group()
            st.rerun()

    st.markdown("---")
    st.subheader("房間控制")

    host_group = state.get("host_group", 0)
    is_host = (my_group == host_group)

    st.caption(f"主持組：第 {host_group+1} 組")

    if is_host:
        if st.button("♻️ 重設整局遊戲", type="primary", use_container_width=True):
            reset_game_state()
            st.rerun()
    else:
        st.info("只有主持組可重設整局。")

    if st.button("🔄 重新整理畫面", use_container_width=True):
        st.rerun()

    st.markdown("---")
    st.subheader("目前操作權")

    if my_group is None:
        st.warning("請先加入組別。")
    else:
        if state["game_over"]:
            st.error("遊戲已結束")
        elif state["current_group"] == my_group:
            st.success("現在輪到你們組操作")
        else:
            st.info(f"現在輪到第 {state['current_group']+1} 組")

    # 擲骰按鈕
    can_roll = (
        my_group is not None
        and not state["game_over"]
        and state["phase"] == "roll"
        and state["current_group"] == my_group
    )

    if can_roll:
        if st.button("🎲 擲骰", type="primary", use_container_width=True):
            process_roll_shared(my_group)
            st.rerun()

    # 答題區
    can_answer = (
        my_group is not None
        and not state["game_over"]
        and state["phase"] == "answer"
        and state["current_group"] == my_group
        and state["current_question"] is not None
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
            key=f"answer_group_{my_group}_turn_{state['turn']}"
        )

        if st.button("✅ 提交答案", type="primary", use_container_width=True):
            selected_idx = q["options"].index(answer_choice)
            process_answer_shared(my_group, selected_idx)
            st.rerun()

# =========================================================
# 遊戲結束提示
# =========================================================
if state["game_over"] and state["winner_group"] is not None:
    st.success(f"🏁 遊戲結束！冠軍是第 {state['winner_group']+1} 組 {GROUP_ICONS[state['winner_group']]}")

# =========================================================
# 主畫面
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
        rep = state["players"].get(str(g), "未登記")
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
- 13 組可用同一網址加入同一局遊戲
- 每位玩家先選擇自己的組別
- **只有輪到的組別能操作**
- 共用同一個棋盤、同一個回合、同一份遊戲狀態
- 起始現金皆為 **$2000**
- 通過起點可獲得 **$200**
- 走到未被佔領的品牌格：  
  - 題目從「尚未被答對過」的題庫中隨機抽出  
  - 答對：成功佔領，且該題不再出現  
  - 答錯：支付該格固定過路費  
- 走到已被別組佔領的格子：  
  - 不可再搶佔  
  - 不回答題目  
  - 直接支付固定過路費給原佔領組  
- 走到自己已佔領的格子：安全通過
- 若所有品牌地都已被佔領，遊戲結束
- 若所有可用題目都已答對過，遊戲也會直接結束
- 排名先比 **佔領格數**，再比 **現金**
    """)

st.caption("多人同步提醒：所有人請使用同一台伺服器上的同一個網址；本版本使用共享 JSON 檔保存同一局狀態。")