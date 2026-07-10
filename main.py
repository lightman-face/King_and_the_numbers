from __future__ import annotations

import random
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox


SUITS = ("♠", "♥", "♣", "♦")
SUIT_POWER = {"♦": 0, "♣": 1, "♥": 2, "♠": 3, "": 4}
RANK_LABEL = {1: "A", 11: "J", 12: "Q", 13: "K", 14: "小王", 15: "大王"}
RANK_POWER = {
    4: 0, 6: 1, 8: 2, 9: 3, 10: 4, 11: 5, 12: 6, 13: 7,
    1: 8, 3: 9, 2: 10, 5: 11, 14: 12, 15: 13, 7: 14,
}


@dataclass(frozen=True)
class Card:
    rank: int
    suit: str = ""

    @property
    def label(self) -> str:
        if self.rank >= 14:
            return RANK_LABEL[self.rank]
        return f"{self.suit}{RANK_LABEL.get(self.rank, self.rank)}"

    @property
    def color(self) -> str:
        return "#d73535" if self.suit in ("♥", "♦") or self.rank == 15 else "#20242b"

    @property
    def power(self) -> tuple[int, int]:
        return RANK_POWER[self.rank], SUIT_POWER[self.suit]

    @property
    def points(self) -> int:
        if self.rank in (10, 13):
            return 10
        return 5 if self.rank == 5 else 0


@dataclass
class Play:
    cards: list[Card]
    kind: str

    @property
    def power(self) -> tuple[int, int]:
        return max(card.power for card in self.cards)

    @property
    def text(self) -> str:
        return " ".join(card.label for card in self.cards)


def make_deck() -> list[Card]:
    deck = [Card(rank, suit) for rank in range(1, 14) for suit in SUITS]
    deck += [Card(14), Card(15)]
    random.shuffle(deck)
    return deck


def classify(cards: list[Card]) -> Play | None:
    if len(cards) == 5:
        ranks = {card.rank for card in cards}
        if 7 in ranks and 5 in ranks and 2 in ranks and 3 in ranks and (14 in ranks or 15 in ranks):
            return Play(cards, "special")
    if len(cards) == 1:
        return Play(cards, "single")
    if len(cards) == 2 and cards[0].rank == cards[1].rank:
        return Play(cards, "pair")
    if len(cards) == 3 and len({card.rank for card in cards}) == 1:
        return Play(cards, "bomb")
    return None


def beats(new: Play, old: Play | None) -> bool:
    if old is None:
        return True
    if new.kind == "special":
        return True
    if new.kind == "bomb" and old.kind != "bomb":
        return True
    if new.kind != old.kind or len(new.cards) != len(old.cards):
        return False
    return new.power > old.power


class Game:
    BG = "#123d2d"
    PANEL = "#f4ead2"
    GOLD = "#d5a934"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("七王五二三")
        self.root.geometry("1040x720")
        self.root.minsize(900, 620)
        self.root.configure(bg=self.BG)

        self.deck: list[Card] = []
        self.hands: list[list[Card]] = [[], []]
        self.captured: list[list[Card]] = [[], []]
        self.selected: set[int] = set()
        self.current = 0
        self.leader = 0
        self.round_winner = 0
        self.last_play: Play | None = None
        self.table_cards: list[Card] = []
        self.round_active = False
        self.game_over = False
        self.privacy_open = False
        self.parity_owner: int | None = None

        self.status_var = tk.StringVar()
        self.info_var = tk.StringVar()
        self.score_var = tk.StringVar()
        self.build_ui()
        self.new_game()

    def build_ui(self) -> None:
        header = tk.Frame(self.root, bg="#0b2920", pady=12)
        header.pack(fill="x")
        tk.Label(header, text="♠  七 王 五 二 三  ♥", fg=self.GOLD, bg="#0b2920",
                 font=("Microsoft YaHei UI", 24, "bold")).pack()
        tk.Label(header, textvariable=self.info_var, fg="white", bg="#0b2920",
                 font=("Microsoft YaHei UI", 11)).pack(pady=(4, 0))

        self.table = tk.Frame(self.root, bg=self.BG)
        self.table.pack(fill="both", expand=True, padx=24, pady=16)
        tk.Label(self.table, textvariable=self.status_var, bg=self.BG, fg="white",
                 font=("Microsoft YaHei UI", 16, "bold"), wraplength=900).pack(pady=8)
        self.play_area = tk.Frame(self.table, bg="#0d3225", height=170,
                                  highlightbackground="#ae8b3a", highlightthickness=2)
        self.play_area.pack(fill="x", padx=90, pady=10)
        self.play_area.pack_propagate(False)
        self.table_label = tk.Label(self.play_area, text="等待开局", bg="#0d3225", fg="#f6e8bd",
                                    font=("Microsoft YaHei UI", 20), wraplength=760)
        self.table_label.pack(expand=True)

        self.hand_frame = tk.Frame(self.table, bg=self.BG)
        self.hand_frame.pack(fill="both", expand=True, pady=8)

        controls = tk.Frame(self.root, bg="#0b2920", pady=12)
        controls.pack(fill="x")
        self.play_btn = self.button(controls, "出牌", self.play_selected)
        self.play_btn.pack(side="left", padx=(28, 8))
        self.pass_btn = self.button(controls, "放弃本回合", self.pass_round, "#9b3f35")
        self.pass_btn.pack(side="left", padx=8)
        self.score_label = tk.Label(controls, textvariable=self.score_var, bg="#0b2920", fg="white",
                                    font=("Microsoft YaHei UI", 11))
        self.score_label.pack(side="right", padx=28)

    def button(self, parent: tk.Widget, text: str, command, color: str = "#bf8b25") -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=color, fg="white",
                         activebackground="#e0b44b", activeforeground="white", relief="flat",
                         padx=20, pady=8, font=("Microsoft YaHei UI", 11, "bold"), cursor="hand2")

    def new_game(self) -> None:
        self.deck = make_deck()
        self.hands = [[], []]
        self.captured = [[], []]
        self.table_cards = []
        self.last_play = None
        self.game_over = False
        self.round_active = False
        for _ in range(5):
            self.hands[0].append(self.deck.pop())
            self.hands[1].append(self.deck.pop())
        self.update_info()
        self.choose_parity()

    def choose_parity(self) -> None:
        self.clear_hand()
        self.status_var.set("开局：由一名玩家抢先选择奇数或偶数")
        self.table_label.config(text="🎲 请选择奇偶，选择后另一名玩家自动获得另一项")
        box = tk.Frame(self.hand_frame, bg=self.PANEL, padx=35, pady=28)
        box.pack(pady=20)
        tk.Label(box, text="谁先选择？", bg=self.PANEL, font=("Microsoft YaHei UI", 15, "bold")).pack(pady=6)
        for player in (0, 1):
            row = tk.Frame(box, bg=self.PANEL)
            row.pack(pady=5)
            tk.Label(row, text=f"玩家 {player + 1}", width=10, bg=self.PANEL,
                     font=("Microsoft YaHei UI", 12)).pack(side="left")
            self.button(row, "选奇数", lambda p=player: self.set_parity(p, 1)).pack(side="left", padx=5)
            self.button(row, "选偶数", lambda p=player: self.set_parity(p, 0)).pack(side="left", padx=5)
        self.set_controls(False)

    def set_parity(self, player: int, parity: int) -> None:
        self.parity_owner = player if parity == 1 else 1 - player
        chooser_text = "奇数" if parity else "偶数"
        self.status_var.set(f"玩家 {player + 1} 选择了{chooser_text}，正在掷骰子……")
        self.clear_hand()
        self.animate_die(12)

    def animate_die(self, remaining: int) -> None:
        value = random.randint(1, 6)
        self.table_label.config(text=f"🎲  {value}", font=("Microsoft YaHei UI", 44, "bold"))
        if remaining:
            self.root.after(90, lambda: self.animate_die(remaining - 1))
            return
        winner = self.parity_owner if value % 2 else 1 - self.parity_owner
        self.current = self.leader = self.round_winner = winner
        result = "奇数" if value % 2 else "偶数"
        self.status_var.set(f"骰子为 {value}（{result}），玩家 {winner + 1} 先出牌")
        self.root.after(900, lambda: self.start_round(initial=True))

    def start_round(self, initial: bool = False) -> None:
        if not initial:
            self.draw_to_five(self.round_winner)
            self.draw_to_five(1 - self.round_winner)
        self.leader = self.current = self.round_winner
        self.last_play = None
        self.table_cards = []
        self.round_active = True
        self.table_label.config(text="本回合尚未出牌", font=("Microsoft YaHei UI", 20))
        self.update_info()
        self.show_privacy()

    def draw_to_five(self, player: int) -> None:
        while len(self.hands[player]) < 5 and self.deck:
            self.hands[player].append(self.deck.pop())

    def show_privacy(self) -> None:
        if self.game_over:
            return
        self.privacy_open = False
        self.selected.clear()
        self.clear_hand()
        cover = tk.Frame(self.hand_frame, bg="#182b3a", padx=50, pady=35)
        cover.pack(expand=True)
        tk.Label(cover, text=f"请将设备交给玩家 {self.current + 1}", bg="#182b3a", fg="white",
                 font=("Microsoft YaHei UI", 23, "bold")).pack(pady=8)
        tk.Label(cover, text="确认周围无人偷看后再显示手牌", bg="#182b3a", fg="#c5d1d8",
                 font=("Microsoft YaHei UI", 12)).pack(pady=8)
        self.button(cover, "我是玩家，显示我的手牌", self.reveal_hand).pack(pady=12)
        self.set_controls(False)
        self.status_var.set(f"轮到玩家 {self.current + 1}")

    def reveal_hand(self) -> None:
        self.privacy_open = True
        self.render_hand()
        self.set_controls(True)

    def clear_hand(self) -> None:
        for child in self.hand_frame.winfo_children():
            child.destroy()

    def render_hand(self) -> None:
        self.clear_hand()
        hand = self.hands[self.current]
        hand.sort(key=lambda c: c.power, reverse=True)
        title = f"玩家 {self.current + 1} 的手牌（点击选择）"
        tk.Label(self.hand_frame, text=title, bg=self.BG, fg="white",
                 font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(6, 12))
        cards_frame = tk.Frame(self.hand_frame, bg=self.BG)
        cards_frame.pack()
        for index, card in enumerate(hand):
            selected = index in self.selected
            btn = tk.Button(cards_frame, text=card.label, command=lambda i=index: self.toggle_card(i),
                            width=7, height=4, bg="#ffe7a3" if selected else "#fffdf5",
                            fg=card.color, relief="raised", bd=4 if selected else 2,
                            font=("Microsoft YaHei UI", 15, "bold"), cursor="hand2")
            btn.grid(row=0, column=index, padx=5, pady=(0 if selected else 12, 12 if selected else 0))

    def toggle_card(self, index: int) -> None:
        if index in self.selected:
            self.selected.remove(index)
        else:
            self.selected.add(index)
        self.render_hand()

    def play_selected(self) -> None:
        if not self.privacy_open or self.game_over:
            return
        cards = [self.hands[self.current][i] for i in sorted(self.selected)]
        play = classify(cards)
        if not play:
            messagebox.showwarning("不能这样出", "请选择单张、同点数对子、三张同点数炸弹，或七王五二三。")
            return
        if not beats(play, self.last_play):
            messagebox.showwarning("牌不够大", "必须用同类型且更大的牌压制；炸弹可以压制单牌或对子。")
            return
        for card in cards:
            self.hands[self.current].remove(card)
        self.table_cards.extend(cards)
        self.last_play = play
        self.round_winner = self.current
        self.table_label.config(text=f"玩家 {self.current + 1}：{play.text}\n类型：{self.kind_name(play.kind)}")
        if play.kind == "special":
            self.finish_game(self.current, "成功打出“七王五二三”，立即获胜！")
            return
        if not self.deck and not self.hands[self.current]:
            self.finish_by_score()
            return
        self.current = 1 - self.current
        self.update_info()
        self.show_privacy()

    def pass_round(self) -> None:
        if not self.privacy_open or self.game_over:
            return
        if self.last_play is None:
            messagebox.showinfo("不能放弃", "本回合首位玩家必须先出牌。")
            return
        winner = self.round_winner
        scored = [card for card in self.table_cards if card.points]
        self.captured[winner].extend(scored)
        gained = sum(card.points for card in scored)
        self.round_active = False
        self.update_info()
        messagebox.showinfo("回合结束", f"玩家 {winner + 1} 赢得本回合，收取 {gained} 分的计分牌。")
        if not self.deck and (not self.hands[0] or not self.hands[1]):
            self.finish_by_score()
            return
        self.current = winner
        self.start_round()

    def finish_by_score(self) -> None:
        scores = [sum(card.points for card in pile) for pile in self.captured]
        if scores[0] == scores[1]:
            self.finish_game(None, f"牌堆已空且有玩家出完手牌，双方同为 {scores[0]} 分，平局！")
        else:
            winner = 0 if scores[0] > scores[1] else 1
            self.finish_game(winner, f"牌堆已空且有玩家出完手牌。计分 {scores[0]} : {scores[1]}。")

    def finish_game(self, winner: int | None, reason: str) -> None:
        self.game_over = True
        self.clear_hand()
        self.set_controls(False)
        result = "本局平局" if winner is None else f"玩家 {winner + 1} 获胜！"
        self.status_var.set(result)
        self.table_label.config(text=f"{result}\n{reason}", font=("Microsoft YaHei UI", 20, "bold"))
        self.button(self.hand_frame, "再来一局", self.new_game).pack(expand=True)
        messagebox.showinfo("游戏结束", f"{result}\n{reason}")

    def kind_name(self, kind: str) -> str:
        return {"single": "单张", "pair": "对子", "bomb": "炸弹", "special": "七王五二三"}[kind]

    def set_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.play_btn.config(state=state)
        self.pass_btn.config(state=state)

    def update_info(self) -> None:
        self.info_var.set(f"牌堆剩余：{len(self.deck)} 张  |  玩家1手牌：{len(self.hands[0])} 张  |  玩家2手牌：{len(self.hands[1])} 张")
        scores = [sum(card.points for card in pile) for pile in self.captured]
        self.score_var.set(f"计分牌：玩家1 {scores[0]} 分　玩家2 {scores[1]} 分")


def main() -> None:
    root = tk.Tk()
    Game(root)
    root.mainloop()


if __name__ == "__main__":
    main()
