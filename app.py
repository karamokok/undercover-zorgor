import eventlet
eventlet.monkey_patch()

import random
import string
import os
from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, join_room, leave_room, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'zorgor_secret_online!')
socketio = SocketIO(app, cors_allowed_origins="*")

FR_PAIRS = [
    ("Plage", "Mer"), ("Voiture", "Moto"), ("Soleil", "Lune"), ("Chat", "Chien"),
    ("École", "Université"), ("Pain", "Beurre"), ("Eau", "Jus"), ("Maison", "Appartement"),
    ("Téléphone", "Ordinateur"), ("Ciel", "Terre"), ("Riz", "Attiéké"), ("Vélo", "Trottinette"),
    ("Livre", "Cahier"), ("Médecin", "Infirmier"), ("Avion", "Hélicoptère"), ("Pluie", "Orage"),
    ("Chaussure", "Sandale"), ("Dormir", "Rêver"), ("Manger", "Cuisiner"), ("Rire", "Sourire")
]

NOUCHI_WORDS = [
    "Mougou", "Mougouli", "Mousso", "Skinny", "Bissab", "Gbailler", "Didi B", "Himra",
    "Maabio", "Riz coucher", "Tuer cabri", "Mougoupan", "Dohi", "Brouteur", "Le père daloa",
    "Anisorgorman", "Mon pied est sur cailloux", "Côcôta", "Djafoule", "Enjaillement",
    "Fraya", "Gaou", "Gbairè", "Woro-woro", "DJOULA", "RHDP", "Souayer"
]

rooms = {} # { room_code: { host: sid, players: [{sid, name, role, word, alive}], status: str, ... } }
sid_to_room = {}

def generate_room_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        if code not in rooms:
            return code

def broadcast_state(room_code):
    if room_code not in rooms: return
    state = rooms[room_code]
    # Remove secret words for broadcasting
    public_players = []
    for p in state["players"]:
        public_players.append({
            "sid": p["sid"], "name": p["name"], "alive": p["alive"], 
            "role": p["role"] if not p["alive"] or state["status"] == "game_over" else "?"
        })
        
    public_state = {
        "status": state["status"],
        "players": public_players,
        "has_voted": list(state.get("votes", {}).keys()),
        "winner": state.get("winner")
    }
    socketio.emit('state_update', public_state, room=room_code)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/online")
def online():
    return render_template("online.html")

@app.route("/sw.js")
def sw():
    return send_from_directory("static", "sw.js", mimetype="application/javascript")

@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json", mimetype="application/json")

@socketio.on('join_room')
def on_join(data):
    username = data['username']
    room = data.get('room', '').upper()
    
    if not room:
        room = generate_room_code()
        rooms[room] = {
            "host": request.sid,
            "players": [],
            "status": "lobby",
            "votes": {}
        }
    elif room not in rooms:
        emit('room_error', {'msg': 'Salon introuvable.'})
        return
        
    if rooms[room]["status"] != "lobby" and rooms[room]["status"] != "game_over":
        emit('room_error', {'msg': 'Partie en cours.'})
        return
        
    join_room(room)
    sid_to_room[request.sid] = room
    
    # Check if name exists, add number
    name = username
    c = 1
    while any(p['name'] == name for p in rooms[room]['players']):
        name = f"{username}{c}"
        c += 1
        
    rooms[room]["players"].append({
        "sid": request.sid, "name": name, "role": "", "word": "", "alive": True
    })
    
    socketio.emit('sys_msg', {'msg': f'{name} a rejoint le salon.'}, room=room)
    
    emit('lobby_update', {
        'room': room,
        'host': rooms[room]['host'],
        'players': [{'sid': p['sid'], 'name': p['name']} for p in rooms[room]['players']]
    }, room=room)

@socketio.on('disconnect')
def on_disconnect():
    room = sid_to_room.get(request.sid)
    if room and room in rooms:
        player = next((p for p in rooms[room]["players"] if p["sid"] == request.sid), None)
        if player:
            rooms[room]["players"] = [p for p in rooms[room]["players"] if p["sid"] != request.sid]
            socketio.emit('sys_msg', {'msg': f'{player["name"]} a quitté le salon.'}, room=room)
            
            if len(rooms[room]["players"]) == 0:
                del rooms[room]
            else:
                if rooms[room]["host"] == request.sid:
                    rooms[room]["host"] = rooms[room]["players"][0]["sid"]
                if rooms[room]["status"] == "lobby":
                    emit('lobby_update', {
                        'room': room,
                        'host': rooms[room]['host'],
                        'players': [{'sid': p['sid'], 'name': p['name']} for p in rooms[room]['players']]
                    }, room=room)
                else:
                    broadcast_state(room)
    if request.sid in sid_to_room:
        del sid_to_room[request.sid]

@socketio.on('send_chat')
def on_chat(data):
    room = sid_to_room.get(request.sid)
    if room and room in rooms:
        player = next((p for p in rooms[room]["players"] if p["sid"] == request.sid), None)
        if player:
            socketio.emit('chat_msg', {'sid': request.sid, 'sender': player["name"], 'msg': data["msg"]}, room=room)

@socketio.on('start_game')
def on_start(data):
    room = sid_to_room.get(request.sid)
    if not room or room not in rooms: return
    if rooms[room]["host"] != request.sid: return
    
    players = rooms[room]["players"]
    n = len(players)
    if n < 3 or n > 12:
        socketio.emit('sys_msg', {'msg': 'Il faut entre 3 et 12 joueurs pour jouer.'}, room=room)
        return
        
    mode = data.get("mode", "Français Classique")
    num_zorgor = int(data.get("num_zorgor", 1))
    num_mr_white = int(data.get("num_mr_white", 0))
    has_bras_long = data.get("has_bras_long", False)
    dict_choice = data.get("dictionary", "Français")
    
    roles = []
    if mode == "Français Classique":
        w = num_mr_white
        b = 1 if has_bras_long else 0
        z = num_zorgor
        c = n - z - w - b
        if c < 1:
            socketio.emit('sys_msg', {'msg': 'Trop de rôles spéciaux pour ce nombre de joueurs.'}, room=room)
            return
        roles = ["zorgor"] * z + ["mr_white"] * w + ["bras_long"] * b + ["civil"] * c
        random.shuffle(roles)
        
        if dict_choice == "Français": pair = random.choice(FR_PAIRS)
        elif dict_choice == "Nouchi": pair = random.sample(NOUCHI_WORDS, 2)
        else: pair = random.choice(FR_PAIRS) if random.random() < 0.5 else random.sample(NOUCHI_WORDS, 2)
                
        civil_word, zorgor_word = pair
        if random.choice([True, False]):
            civil_word, zorgor_word = zorgor_word, civil_word
    else:
        w = num_mr_white
        if w < 1: w = 1
        b = 1 if has_bras_long else 0
        c = n - w - b
        if c < 1:
            socketio.emit('sys_msg', {'msg': 'Pas assez de joueurs pour ce mode.'}, room=room)
            return
        roles = ["mr_white"] * w + ["bras_long"] * b + ["civil"] * c
        random.shuffle(roles)
        civil_word = random.choice(NOUCHI_WORDS)
        zorgor_word = ""

    rooms[room]["mode"] = mode
    rooms[room]["status"] = "description_phase"
    rooms[room]["votes"] = {}

    for i, p in enumerate(players):
        r = roles[i]
        p["role"] = r
        p["alive"] = True
        if r == "mr_white": w = "Tu es Mr. White ! Tu n'as pas de mot secret."
        elif r == "zorgor": w = zorgor_word
        else: w = civil_word
        p["word"] = w
        
        socketio.emit('game_started', {'word': w, 'role': r}, room=p["sid"])
        
    broadcast_state(room)

@socketio.on('trigger_vote')
def on_trigger_vote():
    room = sid_to_room.get(request.sid)
    if room and rooms[room]["host"] == request.sid:
        rooms[room]["status"] = "voting_phase"
        rooms[room]["votes"] = {}
        broadcast_state(room)

@socketio.on('submit_vote')
def on_submit_vote(data):
    room = sid_to_room.get(request.sid)
    if not room or rooms[room]["status"] != "voting_phase": return
    
    target_sid = data.get('target')
    if request.sid not in rooms[room]["votes"]:
        rooms[room]["votes"][request.sid] = target_sid
        
    alive_players = [p for p in rooms[room]["players"] if p["alive"]]
    
    if len(rooms[room]["votes"]) >= len(alive_players):
        process_votes(room)
    else:
        broadcast_state(room)

def process_votes(room):
    state = rooms[room]
    tally = {}
    bras_long_vote = None
    
    for voter_sid, target_sid in state["votes"].items():
        voter = next(p for p in state["players"] if p["sid"] == voter_sid)
        target = next(p for p in state["players"] if p["sid"] == target_sid)
        weight = 1
        if voter["role"] == "bras_long" and target["role"] == "zorgor": weight = 2
        if voter["role"] == "bras_long": bras_long_vote = target_sid
            
        tally[target_sid] = tally.get(target_sid, 0) + weight
        
    max_votes = max(tally.values())
    tied = [sid for sid, v in tally.items() if v == max_votes]
    
    elim_sid = None
    if len(tied) == 1:
        elim_sid = tied[0]
    else:
        if bras_long_vote and bras_long_vote in tied: elim_sid = bras_long_vote
        else: elim_sid = random.choice(tied)
            
    for p in state["players"]:
        if p["sid"] == elim_sid:
            p["alive"] = False
            elim = p
            break
            
    socketio.emit('sys_msg', {'msg': f'{elim["name"]} a été éliminé ! Son rôle était : {elim["role"]}'}, room=room)
    
    winner = check_victory(room)
    if winner:
        state["winner"] = winner
        state["status"] = "game_over"
    else:
        if state["mode"] == "Nouchi" and elim["role"] == "mr_white":
            state["status"] = "vengeance_phase"
            state["eliminated_mr_white"] = elim_sid
        else:
            state["status"] = "description_phase"
            
    broadcast_state(room)

@socketio.on('submit_vengeance')
def on_submit_vengeance(data):
    room = sid_to_room.get(request.sid)
    if not room or rooms[room]["status"] != "vengeance_phase": return
    
    target_sid = data.get('target')
    state = rooms[room]
    if request.sid != state.get("eliminated_mr_white"): return
    
    for p in state["players"]:
        if p["sid"] == target_sid:
            p["alive"] = False
            socketio.emit('sys_msg', {'msg': f'Dernier Souffle ! Mr. White a emporté {p["name"]} ! Son rôle était : {p["role"]}'}, room=room)
            break
            
    winner = check_victory(room)
    if winner:
        state["winner"] = winner
        state["status"] = "game_over"
    else:
        state["status"] = "description_phase"
        
    broadcast_state(room)

@socketio.on('back_to_lobby')
def on_back_to_lobby():
    room = sid_to_room.get(request.sid)
    if room and rooms[room]["host"] == request.sid:
        rooms[room]["status"] = "lobby"
        rooms[room]["votes"] = {}
        socketio.emit('lobby_update', {
            'room': room,
            'host': rooms[room]['host'],
            'players': [{'sid': p['sid'], 'name': p['name']} for p in rooms[room]['players']]
        }, room=room)

def check_victory(room):
    players = rooms[room]["players"]
    mode = rooms[room]["mode"]
    alive_civils = sum(1 for p in players if p["alive"] and p["role"] in ["civil", "bras_long"])
    alive_zorgors = sum(1 for p in players if p["alive"] and p["role"] == "zorgor")
    alive_white = sum(1 for p in players if p["alive"] and p["role"] == "mr_white")
    total_alive = alive_civils + alive_zorgors + alive_white
    
    if total_alive == 0: return "Égalité"

    if mode == "Français Classique":
        if total_alive == 2 and alive_white == 1 and alive_zorgors == 1: return "mr_white"
        if alive_zorgors >= (alive_civils + alive_white) and alive_zorgors > 0: return "zorgor"
        if alive_zorgors == 0:
            if alive_white == 0: return "civil"
            elif total_alive <= 2: return "mr_white"
    else:
        if alive_white == 0: return "civil"
        if alive_white == 1 and alive_civils <= 1: return "mr_white"
            
    return None

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
