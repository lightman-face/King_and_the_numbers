from __future__ import annotations

import json
import os
import random
import secrets
import string
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from main import Card, Play, beats, classify, make_deck


ROOT = Path(__file__).parent
ROOMS: dict[str, "Room"] = {}
LOCK = threading.RLock()
KIND_NAMES = {"single": "单张", "pair": "对子", "bomb": "炸弹", "special": "七王五二三"}


def card_json(card: Card) -> dict:
    return {"rank": card.rank, "suit": card.suit, "label": card.label, "red": card.color == "#d73535"}


@dataclass
class Player:
    token: str
    name: str
    connected: bool = True


@dataclass
class Room:
    code: str
    players: list[Player] = field(default_factory=list)
    deck: list[Card] = field(default_factory=list)
    hands: list[list[Card]] = field(default_factory=lambda: [[], []])
    captured: list[list[Card]] = field(default_factory=lambda: [[], []])
    current: int | None = None
    round_winner: int | None = None
    last_play: Play | None = None
    table_cards: list[Card] = field(default_factory=list)
    phase: str = "waiting"
    parity_owner: int | None = None
    parity_choice: int | None = None
    die: int | None = None
    winner: int | None = None
    result: str = ""
    notice: str = "等待第二名玩家加入"
    version: int = 0

    def touch(self) -> None:
        self.version += 1

    def player_index(self, token: str) -> int:
        for index, player in enumerate(self.players):
            if secrets.compare_digest(player.token, token):
                return index
        raise ValueError("无效的玩家身份，请重新进入房间")

    def start(self) -> None:
        self.deck = make_deck()
        self.hands = [[], []]
        self.captured = [[], []]
        for _ in range(5):
            self.hands[0].append(self.deck.pop())
            self.hands[1].append(self.deck.pop())
        self.current = None
        self.round_winner = None
        self.last_play = None
        self.table_cards = []
        self.parity_owner = None
        self.parity_choice = None
        self.die = None
        self.winner = None
        self.result = ""
        self.phase = "parity"
        self.notice = "请抢先选择奇数或偶数"
        self.touch()

    def choose_parity(self, player: int, parity: int) -> None:
        if self.phase != "parity" or self.parity_choice is not None:
            raise ValueError("奇偶已经被选择")
        self.parity_choice = parity
        self.parity_owner = player if parity == 1 else 1 - player
        self.die = random.randint(1, 6)
        winner = self.parity_owner if self.die % 2 else 1 - self.parity_owner
        self.current = self.round_winner = winner
        choice = "奇数" if parity else "偶数"
        self.notice = f"{self.players[player].name} 选择{choice}，骰子为 {self.die}，{self.players[winner].name} 先出牌"
        self.phase = "playing"
        self.touch()

    def play(self, player: int, indexes: list[int]) -> None:
        if self.phase != "playing" or player != self.current:
            raise ValueError("现在还没有轮到你")
        if not indexes or len(set(indexes)) != len(indexes):
            raise ValueError("请选择要出的牌")
        hand = self.hands[player]
        if any(not isinstance(i, int) or i < 0 or i >= len(hand) for i in indexes):
            raise ValueError("选择的牌无效，请刷新页面")
        cards = [hand[i] for i in indexes]
        play = classify(cards)
        if play is None:
            raise ValueError("只能出单张、同点数对子、三张同点数炸弹或七王五二三")
        if not beats(play, self.last_play):
            raise ValueError("必须用同类型且更大的牌压制，炸弹可以压单牌或对子")
        for index in sorted(indexes, reverse=True):
            hand.pop(index)
        self.table_cards.extend(cards)
        self.last_play = play
        self.round_winner = player
        self.notice = f"{self.players[player].name} 打出 {play.text}（{KIND_NAMES[play.kind]}）"
        if play.kind == "special":
            self.finish(player, "打出七王五二三，立即获胜")
            return
        if not self.deck and not hand:
            self.finish_by_score()
            return
        self.current = 1 - player
        self.touch()

    def pass_turn(self, player: int) -> None:
        if self.phase != "playing" or player != self.current:
            raise ValueError("现在还没有轮到你")
        if self.last_play is None or self.round_winner is None:
            raise ValueError("本回合首位玩家必须先出牌")
        winner = self.round_winner
        scored = [card for card in self.table_cards if card.points]
        self.captured[winner].extend(scored)
        gained = sum(card.points for card in scored)
        if not self.deck and (not self.hands[0] or not self.hands[1]):
            self.finish_by_score()
            return
        self.draw_to_five(winner)
        self.draw_to_five(1 - winner)
        self.current = self.round_winner = winner
        self.last_play = None
        self.table_cards = []
        self.notice = f"{self.players[player].name} 放弃；{self.players[winner].name} 赢得回合并收取 {gained} 分"
        self.touch()

    def draw_to_five(self, player: int) -> None:
        while len(self.hands[player]) < 5 and self.deck:
            self.hands[player].append(self.deck.pop())

    def finish_by_score(self) -> None:
        scores = self.scores
        if scores[0] == scores[1]:
            self.finish(None, f"双方均为 {scores[0]} 分，本局平局")
        else:
            winner = 0 if scores[0] > scores[1] else 1
            self.finish(winner, f"计分牌为 {scores[0]} : {scores[1]}")

    def finish(self, winner: int | None, reason: str) -> None:
        self.phase = "finished"
        self.winner = winner
        self.result = ("本局平局" if winner is None else f"{self.players[winner].name} 获胜") + f"：{reason}"
        self.notice = self.result
        self.touch()

    @property
    def scores(self) -> list[int]:
        return [sum(card.points for card in pile) for pile in self.captured]

    def view(self, player: int) -> dict:
        last = None
        if self.last_play:
            last = {"cards": [card_json(c) for c in self.last_play.cards], "kind": KIND_NAMES[self.last_play.kind]}
        return {
            "code": self.code,
            "you": player,
            "players": [p.name for p in self.players],
            "phase": self.phase,
            "current": self.current,
            "hand": [card_json(c) for c in self.hands[player]],
            "handCounts": [len(h) for h in self.hands],
            "deckCount": len(self.deck),
            "scores": self.scores,
            "lastPlay": last,
            "notice": self.notice,
            "die": self.die,
            "result": self.result,
            "version": self.version,
        }


def room_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if code not in ROOMS:
            return code


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def json_response(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            raise ValueError("请求格式无效")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.json_response({"ok": True, "rooms": len(ROOMS)})
            return
        super().do_GET()

    def do_POST(self) -> None:
        try:
            data = self.read_json()
            path = urlparse(self.path).path
            with LOCK:
                if path == "/api/create":
                    self.create_room(data)
                elif path == "/api/join":
                    self.join_room(data)
                elif path == "/api/state":
                    room, player = self.authorize(data)
                    self.json_response({"ok": True, "state": room.view(player)})
                elif path == "/api/parity":
                    room, player = self.authorize(data)
                    room.choose_parity(player, int(data.get("parity", -1)))
                    self.json_response({"ok": True, "state": room.view(player)})
                elif path == "/api/play":
                    room, player = self.authorize(data)
                    room.play(player, data.get("indexes", []))
                    self.json_response({"ok": True, "state": room.view(player)})
                elif path == "/api/pass":
                    room, player = self.authorize(data)
                    room.pass_turn(player)
                    self.json_response({"ok": True, "state": room.view(player)})
                elif path == "/api/restart":
                    room, player = self.authorize(data)
                    if room.phase != "finished":
                        raise ValueError("本局尚未结束")
                    room.start()
                    self.json_response({"ok": True, "state": room.view(player)})
                else:
                    self.json_response({"ok": False, "error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.json_response({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            print("服务器错误:", repr(exc))
            self.json_response({"ok": False, "error": "服务器内部错误"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def create_room(self, data: dict) -> None:
        name = clean_name(data.get("name"))
        code = room_code()
        token = secrets.token_urlsafe(24)
        room = Room(code)
        room.players.append(Player(token, name))
        ROOMS[code] = room
        self.json_response({"ok": True, "code": code, "token": token, "player": 0})

    def join_room(self, data: dict) -> None:
        name = clean_name(data.get("name"))
        code = str(data.get("code", "")).strip().upper()
        room = ROOMS.get(code)
        if room is None:
            raise ValueError("找不到这个房间，请检查房间码")
        if len(room.players) >= 2:
            raise ValueError("房间已经满员")
        token = secrets.token_urlsafe(24)
        room.players.append(Player(token, name))
        room.start()
        self.json_response({"ok": True, "code": code, "token": token, "player": 1})

    def authorize(self, data: dict) -> tuple[Room, int]:
        code = str(data.get("code", "")).strip().upper()
        room = ROOMS.get(code)
        if room is None:
            raise ValueError("房间不存在或服务器已重启")
        return room, room.player_index(str(data.get("token", "")))


def clean_name(value) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("请输入玩家昵称")
    return name[:12]


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"七王五二三网页服务器已启动：http://localhost:{port}")
    print("同一 Wi-Fi 的玩家可使用：http://你的电脑局域网IP:" + str(port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
