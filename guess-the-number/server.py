import json
import os
import secrets
from datetime import datetime, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data.json"
WORDS_FILE = ROOT / "words.json"
PORT = int(os.environ.get("PORT", "3000"))
CREATOR_USERNAME = os.environ.get("RANGEFINDER_CREATOR", "creator").strip().casefold()
CREATOR_CODE = os.environ.get("RANGEFINDER_CREATOR_CODE", "daily-arcade-owner")
WORDS = json.loads(WORDS_FILE.read_text(encoding="utf-8"))


def today():
    return datetime.now(timezone.utc).date().isoformat()


def read_data():
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"challenge": None, "players": {}}


def write_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_data():
    data = read_data()
    if not data.get("challenge") or data["challenge"].get("date") != today():
        data["challenge"] = {"date": today(), "target": secrets.randbelow(100) + 1}
        for player in data["players"].values():
            player["daily"] = None
        write_data(data)
    return data


def higher_lower_leaderboard(data):
    scores = []
    for player in data["players"].values():
        game = player.get("higherLower")
        if game and game.get("date") == today():
            values = (game.get("scores", [game["score"]] if game.get("completed") else []))[:1]
            scores.extend({"name": player["name"], "score": score} for score in values)
    scores.sort(key=lambda score: (-score["score"], score["name"].lower()))
    return [
        {"rank": index + 1, "name": score["name"], "score": score["score"]}
        for index, score in enumerate(scores[:100])
    ]


def leaderboard(data):
    scores = []
    for player in data["players"].values():
        daily = player.get("daily")
        if daily and daily.get("date") == today():
            values = (daily.get("scores", [daily["moves"]] if daily.get("completed") else []))[:1]
            scores.extend({"name": player["name"], "moves": moves} for moves in values)
    scores.sort(key=lambda score: (score["moves"], score["name"].lower()))
    return [
        {"rank": index + 1, "name": score["name"], "moves": score["moves"]}
        for index, score in enumerate(scores[:100])
    ]


def word_leaderboard(data):
    scores = []
    for player in data["players"].values():
        game = player.get("wordGame")
        if game and game.get("date") == today():
            values = (game.get("scores", [game["score"]] if game.get("completed") else []))[:1]
            scores.extend({"name": player["name"], "score": score} for score in values)
    scores.sort(key=lambda score: (-score["score"], score["name"].lower()))
    return [
        {"rank": index + 1, "name": score["name"], "score": score["score"]}
        for index, score in enumerate(scores[:100])
    ]


def new_word_game(scores=None):
    return {"date": today(), "current": secrets.choice(WORDS), "seen": [], "newSinceRepeat": 0, "currentIsRepeat": False, "history": [], "score": 0, "scores": scores or [], "completed": False}


def public_state(data, player_id):
    player = data["players"].get(player_id)
    daily = player.get("daily") if player else None
    if not daily or daily.get("date") != today():
        daily = None
    return {
        "date": today(),
        "name": player["name"] if player else "",
        "moves": daily["moves"] if daily else 0,
        "guesses": daily["guesses"] if daily else [],
        "completed": bool(daily and daily.get("completed")),
        "isCreator": bool(player and (player.get("isCreator") or player["name"].casefold() in ("creator", CREATOR_USERNAME))),
        "leaderboard": leaderboard(data),
        "higherLower": public_higher_lower_state(data, player_id),
        "wordGame": public_word_state(data, player_id),
    }


def public_higher_lower_state(data, player_id):
    player = data["players"].get(player_id)
    game = player.get("higherLower") if player else None
    if not game or game.get("date") != today():
        game = None
    return {
        "current": game["current"] if game else None,
        "score": game["score"] if game else 0,
        "history": game["history"] if game else [],
        "completed": bool(game and game.get("completed")),
        "isCreator": bool(player and (player.get("isCreator") or player["name"].casefold() == CREATOR_USERNAME)),
        "leaderboard": higher_lower_leaderboard(data),
    }


def public_word_state(data, player_id):
    player = data["players"].get(player_id)
    game = player.get("wordGame") if player else None
    if not game or game.get("date") != today():
        game = None
    return {
        "current": game["current"] if game else None,
        "score": game["score"] if game else 0,
        "history": [],
        "lastResult": game["history"][-1] if game and game.get("history") else None,
        "completed": bool(game and game.get("completed")),
        "leaderboard": word_leaderboard(data),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def player_id(self):
        self.new_cookie = None
        parsed = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        if parsed.get("rangefinder_player"):
            return parsed["rangefinder_player"].value
        player_id = secrets.token_urlsafe(18)
        self.new_cookie = f"rangefinder_player={player_id}; Path=/; SameSite=Lax; Max-Age=31536000"
        return player_id

    def json_response(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if self.new_cookie:
            self.send_header("Set-Cookie", self.new_cookie)
        self.end_headers()
        self.wfile.write(payload)

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        data = get_data()
        player_id = self.player_id()
        request_path = urlparse(self.path).path.rstrip("/") or "/"
        if request_path == "/api/state":
            player = data["players"].get(player_id)
            if player and (not player.get("higherLower") or player["higherLower"].get("date") != today()):
                player["higherLower"] = {"date": today(), "current": secrets.randbelow(100) + 1, "score": 0, "history": [], "completed": False}
                write_data(data)
            if player and (not player.get("wordGame") or player["wordGame"].get("date") != today()):
                old_word_game = player.get("wordGame") or {}
                old_scores = old_word_game.get("scores", [])
                player["wordGame"] = new_word_game(old_scores)
                write_data(data)
            self.json_response(200, public_state(data, player_id))
            return
        static_files = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"), "/manifest.json": ("manifest.json", "application/manifest+json"), "/icon.svg": ("icon.svg", "image/svg+xml"), "/sw.js": ("sw.js", "application/javascript"), "/robots.txt": ("robots.txt", "text/plain; charset=utf-8")}
        if request_path in static_files:
            file_name, content_type = static_files[request_path]
            payload = (ROOT / file_name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if self.new_cookie:
                self.send_header("Set-Cookie", self.new_cookie)
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def do_POST(self):
        data = get_data()
        player_id = self.player_id()
        request_path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            body = self.body()
            if request_path == "/api/profile":
                name = str(body.get("name", "")).strip()[:18]
                if not name:
                    self.json_response(400, {"error": "Choose a name first."})
                    return
                taken = any(
                    other_id != player_id and player.get("name", "").casefold() == name.casefold()
                    for other_id, player in data["players"].items()
                )
                if taken:
                    self.json_response(409, {"error": "That username is already taken."})
                    return
                if name.casefold() == CREATOR_USERNAME and any(other_id != player_id and player.get("name", "").casefold() == CREATOR_USERNAME for other_id, player in data["players"].items()):
                    self.json_response(409, {"error": "That creator username is already taken."})
                    return
                player = data["players"].setdefault(player_id, {"name": name, "daily": None})
                if player.get("name", "").casefold() in ("creator", CREATOR_USERNAME):
                    player["isCreator"] = True
                if body.get("creatorCode") == CREATOR_CODE:
                    player["isCreator"] = True
                player["name"] = name
                write_data(data)
                self.json_response(200, public_state(data, player_id))
                return
            if request_path == "/api/word-game":
                player = data["players"].get(player_id)
                if not player:
                    self.json_response(400, {"error": "Choose a name first."})
                    return
                game = player.get("wordGame")
                if not game or game.get("date") != today():
                    game = new_word_game()
                    player["wordGame"] = game
                if game["completed"]:
                    game = new_word_game(game.get("scores", []))
                    player["wordGame"] = game
                answer = body.get("answer")
                if answer not in ("new", "seen"):
                    self.json_response(400, {"error": "Choose new or already seen."})
                    return
                expected = "seen" if game["currentIsRepeat"] else "new"
                correct = answer == expected
                word = game["current"]
                game["history"].append({"word": word, "answer": answer, "correct": correct})
                if word not in game["seen"]:
                    game["seen"].append(word)
                if correct:
                    game["score"] += 1
                    if game["currentIsRepeat"]:
                        game["newSinceRepeat"] = 0
                    else:
                        game["newSinceRepeat"] += 1
                    if game["newSinceRepeat"] >= 2 and game["seen"]:
                        game["current"] = secrets.choice(game["seen"])
                        game["currentIsRepeat"] = True
                    else:
                        unseen = [word for word in WORDS if word not in game["seen"]]
                        game["current"] = secrets.choice(unseen or WORDS)
                        game["currentIsRepeat"] = False
                else:
                    game["completed"] = True
                    if not game.get("scores"):
                        game["scores"] = [game["score"]]
                write_data(data)
                self.json_response(200, {"correct": correct, "state": public_word_state(data, player_id)})
                return
            if request_path == "/api/word-game/retry":
                player = data["players"].get(player_id)
                if not player:
                    self.json_response(400, {"error": "Choose a name first."})
                    return
                game = player.get("wordGame")
                if not game or game.get("date") != today() or not game.get("completed"):
                    self.json_response(400, {"error": "Finish the current round before retrying."})
                    return
                player["wordGame"] = new_word_game(game.get("scores", []))
                write_data(data)
                self.json_response(200, public_word_state(data, player_id))
                return
            if request_path == "/api/higher-lower":
                player = data["players"].get(player_id)
                if not player:
                    self.json_response(400, {"error": "Choose a name first."})
                    return
                game = player.get("higherLower")
                if not game or game.get("date") != today():
                    game = {"date": today(), "current": secrets.randbelow(100) + 1, "score": 0, "history": [], "scores": [], "completed": False}
                    player["higherLower"] = game
                if game["completed"]:
                    game = {"date": today(), "current": secrets.randbelow(100) + 1, "score": 0, "history": [], "scores": game.get("scores", []), "completed": False}
                    player["higherLower"] = game
                prediction = body.get("prediction")
                if prediction not in ("higher", "lower"):
                    self.json_response(400, {"error": "Choose higher or lower."})
                    return
                next_number = secrets.randbelow(100) + 1
                correct = (prediction == "higher" and next_number > game["current"]) or (prediction == "lower" and next_number < game["current"])
                game["history"].append({"from": game["current"], "to": next_number, "prediction": prediction, "correct": correct})
                if correct:
                    game["score"] += 1
                    game["current"] = next_number
                else:
                    game["completed"] = True
                    game.setdefault("scores", []).append(game["score"])
                write_data(data)
                self.json_response(200, {"correct": correct, "next": next_number, "state": public_higher_lower_state(data, player_id)})
                return
            if request_path == "/api/higher-lower/retry":
                player = data["players"].get(player_id)
                if not player:
                    self.json_response(400, {"error": "Choose a name first."})
                    return
                game = player.get("higherLower")
                if not game or game.get("date") != today() or not game.get("completed"):
                    self.json_response(400, {"error": "Finish the current chain before retrying."})
                    return
                player["higherLower"] = {"date": today(), "current": secrets.randbelow(100) + 1, "score": 0, "history": [], "scores": game.get("scores", []), "completed": False}
                write_data(data)
                self.json_response(200, public_higher_lower_state(data, player_id))
                return
            if request_path == "/api/guess":
                guess = body.get("guess")
                if not isinstance(guess, int) or isinstance(guess, bool) or not 1 <= guess <= 100:
                    self.json_response(400, {"error": "Enter a whole number from 1 to 100."})
                    return
                player = data["players"].get(player_id)
                if not player:
                    self.json_response(400, {"error": "Choose a name first."})
                    return
                daily = player.get("daily")
                if not daily or daily.get("date") != today():
                    daily = {"date": today(), "moves": 0, "guesses": [], "completed": False}
                    player["daily"] = daily
                if daily["completed"]:
                    daily = {"date": today(), "moves": 0, "guesses": [], "scores": daily.get("scores", []), "completed": False}
                    player["daily"] = daily
                daily["moves"] += 1
                correct = guess == data["challenge"]["target"]
                hint = "Correct" if correct else "Go higher" if guess < data["challenge"]["target"] else "Go lower"
                daily["guesses"].append({"value": guess, "hint": hint})
                daily["completed"] = correct
                if correct and not daily.get("scores"):
                    daily.setdefault("scores", []).append(daily["moves"])
                write_data(data)
                self.json_response(200, {"correct": correct, "hint": hint, "state": public_state(data, player_id)})
                return
        except (ValueError, TypeError, json.JSONDecodeError):
            self.json_response(400, {"error": "Invalid request."})
            return
        self.send_error(404)


if __name__ == "__main__":
    print(f"Daily Arcade is running on port {PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
