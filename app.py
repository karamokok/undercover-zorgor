import eventlet
eventlet.monkey_patch()

import random
import string
import unicodedata
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'zorgor_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Store active rooms and players
rooms = {}
sid_to_room = {}

FR_PAIRS = [
    ["Plage", "Mer"], ["Voiture", "Moto"], ["Soleil", "Lune"], ["Chat", "Chien"],
    ["École", "Université"], ["Pain", "Beurre"], ["Eau", "Jus"], ["Maison", "Appartement"],
    ["Téléphone", "Ordinateur"], ["Ciel", "Terre"], ["Riz", "Attiéké"], ["Vélo", "Trottinette"],
    ["Livre", "Cahier"], ["Médecin", "Infirmier"], ["Avion", "Hélicoptère"], ["Pluie", "Orage"],
    ["Chaussure", "Sandale"], ["Dormir", "Rêver"], ["Manger", "Cuisiner"], ["Rire", "Sourire"]
]

NOUCHI_WORDS = [
    "Mougou", "Mougouli", "Mousso", "Skinny", "Bissab", "Gbailler", "Didi B", "Himra",
    "Maabio", "Riz coucher", "Tuer cabri", "Mougoupan", "Dohi", "Brouteur", "Le père daloa",
    "Anisorgorman", "Mon pied est sur cailloux", "Côcôta", "Djafoule", "Enjaillement",
    "Fraya", "Gaou", "Gbairè", "Woro-woro", "DJOULA", "RHDP", "Souayer"
]

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

def normalize_word(w):
    return ''.join(c for c in unicodedata.normalize('NFD', w) if unicodedata.category(c) != 'Mn').lower().strip()

def broadcast_state(room):
    state = rooms[room]
    safe_players = []
    for p in state["players"]:
        safe_players.append({
            "sid": p["sid"], "name": p["name"], "alive": p["alive"], 
            "role": p["role"] if not p["alive"] or state["status"] == "game_over" else "?"
        })
        
    s = {
        "status": state["status"],
        "players": safe_players,
        "has_voted": list(state["votes"].keys()),
        "winner": state.get("winner"),
        "current_speaker_sid": state.get("current_speaker_sid")
    }
    
    # En fin de partie, on envoie aussi les mots à tout le monde
    if state["status"] == "game_over":
        s["civil_word"] = state.get("civil_word")
        s["zorgor_word"] = state.get("zorgor_word")
        
    socketio.emit('state_update', s, room=room)

def start_description_phase(room):
    state = rooms[room]
    state["status"] = "description_phase"
    alive_players = [p for p in state["players"] if p["alive"]]
    if alive_players:
        state["current_speaker_sid"] = alive_players[0]["sid"]
    else:
        state["current_speaker_sid"] = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/online')
def online():
    return render_template('online.html')

@socketio.on('join_room')
def on_join(data):
    username = data.get('username')
    room_code = data.get('room', '').upper()
    
    if not room_code:
        room_code = generate_room_code()
        rooms[room_code] = {"players": [], "host": request.sid, "status": "lobby", "votes": {}}
    
    if room_code not in rooms:
        emit('room_error', {'msg': 'Salon introuvable !'})
        return
        
    if rooms[room_code]["status"] != "lobby":
        emit('room_error', {'msg': 'Partie déjà en cours !'})
        return
        
    for p in rooms[room_code]["players"]:
        if p["name"] == username:
            emit('room_error', {'msg': 'Pseudo déjà pris dans ce salon !'})
            return

    join_room(room_code)
    sid_to_room[request.sid] = room_code
    
    rooms[room_code]["players"].append({
        "sid": request.sid,
        "name": username,
        "role": None,
        "word": None,
        "alive": True
    })
    
    emit('lobby_update', {
        'room': room_code,
        'host': rooms[room_code]['host'],
        'players': [{'sid': p['sid'], 'name': p['name']} for p in rooms[room_code]['players']]
    }, room=room_code)

@socketio.on('rejoin_room')
def on_rejoin(data):
    username = data.get('username')
    room = data.get('room', '').upper()
    
    if not room or room not in rooms:
        emit('rejoin_failed')
        return
        
    state = rooms[room]
    player = None
    for p in state["players"]:
        if p["name"] == username:
            player = p
            break
            
    if not player:
        emit('rejoin_failed')
        return
        
    old_sid = player["sid"]
    player["sid"] = request.sid
    sid_to_room[request.sid] = room
    
    if old_sid in sid_to_room:
        del sid_to_room[old_sid]
        
    if state["host"] == old_sid:
        state["host"] = request.sid
        
    if state.get("current_speaker_sid") == old_sid:
        state["current_speaker_sid"] = request.sid
        
    new_votes = {}
    for voter_sid, target_sid in state["votes"].items():
        v = request.sid if voter_sid == old_sid else voter_sid
        t = request.sid if target_sid == old_sid else target_sid
        new_votes[v] = t
    state["votes"] = new_votes
    
    if state.get("eliminated_mr_white") == old_sid:
        state["eliminated_mr_white"] = request.sid
        
    join_room(room)
    
    if state["status"] == "lobby":
        emit('lobby_update', {
            'room': room,
            'host': state['host'],
            'players': [{'sid': p['sid'], 'name': p['name']} for p in state['players']]
        }, room=room)
    else:
        emit('game_started', {'role': player['role'], 'word': player['word']})
        broadcast_state(room)

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in sid_to_room:
        del sid_to_room[request.sid]

@socketio.on('leave_game')
def on_leave_game():
    room = sid_to_room.get(request.sid)
    if room and room in rooms:
        player = next((p for p in rooms[room]["players"] if p["sid"] == request.sid), None)
        if player:
            rooms[room]["players"] = [p for p in rooms[room]["players"] if p["sid"] != request.sid]
            socketio.emit('sys_msg', {'msg': f'{player["name"]} a quitté la salle.'}, room=room)
            
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
                    player["alive"] = False
                    winner = check_victory(room)
                    if winner:
                        rooms[room]["winner"] = winner
                        rooms[room]["status"] = "game_over"
                    broadcast_state(room)
        leave_room(room)
        del sid_to_room[request.sid]

@socketio.on('close_room')
def on_close_room():
    room = sid_to_room.get(request.sid)
    if room and rooms[room]["host"] == request.sid:
        socketio.emit('room_closed', room=room)
        del rooms[room]

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
    
    rooms[room]["settings"] = data
    start_game_logic(room, data)
    
@socketio.on('play_again')
def on_play_again():
    room = sid_to_room.get(request.sid)
    if room and rooms[room]["host"] == request.sid:
        settings = rooms[room].get("settings", {})
        start_game_logic(room, settings)

def start_game_logic(room, settings):
    players = rooms[room]["players"]
    n = len(players)
    if n < 3 or n > 12:
        socketio.emit('sys_msg', {'msg': 'Il faut entre 3 et 12 joueurs pour jouer.'}, room=room)
        return
        
    mode = settings.get("mode", "Français Classique")
    num_zorgor = int(settings.get("num_zorgor", 1))
    num_mr_white = int(settings.get("num_mr_white", 0))
    has_bras_long = settings.get("has_bras_long", False)
    dict_choice = settings.get("dictionary", "Français")
    
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
    rooms[room]["votes"] = {}
    rooms[room]["civil_word"] = civil_word
    rooms[room]["zorgor_word"] = zorgor_word

    for i, p in enumerate(players):
        r = roles[i]
        p["role"] = r
        p["alive"] = True
        if r == "mr_white": w = "Tu es Mr. White ! Tu n'as pas de mot secret."
        elif r == "zorgor": w = zorgor_word
        else: w = civil_word
        p["word"] = w
        
        socketio.emit('game_started', {'word': w, 'role': r}, room=p["sid"])
        
    start_description_phase(room)
    broadcast_state(room)

@socketio.on('next_turn')
def on_next_turn():
    room = sid_to_room.get(request.sid)
    if not room or rooms[room]["status"] != "description_phase": return
    state = rooms[room]
    
    if request.sid != state["host"] and request.sid != state.get("current_speaker_sid"):
        return
        
    alive_players = [p for p in state["players"] if p["alive"]]
    current_sid = state.get("current_speaker_sid")
    
    try:
        idx = next(i for i, p in enumerate(alive_players) if p["sid"] == current_sid)
        if idx + 1 < len(alive_players):
            state["current_speaker_sid"] = alive_players[idx + 1]["sid"]
            broadcast_state(room)
        else:
            state["status"] = "voting_phase"
            state["votes"] = {}
            broadcast_state(room)
    except StopIteration:
        pass

@socketio.on('trigger_vote')
def on_trigger_vote():
    room = sid_to_room.get(request.sid)
    if room and rooms[room]["host"] == request.sid:
        rooms[room]["status"] = "voting_phase"
        rooms[room]["votes"] = {}
        broadcast_state(room)

@socketio.on('restart_vote')
def on_restart_vote():
    room = sid_to_room.get(request.sid)
    if room and rooms[room]["host"] == request.sid and rooms[room]["status"] == "voting_phase":
        rooms[room]["votes"] = {}
        socketio.emit('sys_msg', {'msg': "L'hôte a relancé le vote."}, room=room)
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
            
    elim = None
    for p in state["players"]:
        if p["sid"] == elim_sid:
            p["alive"] = False
            elim = p
            break
            
    socketio.emit('sys_msg', {'msg': f'{elim["name"]} a été éliminé ! Son rôle était : {elim["role"]}'}, room=room)
    
    if elim["role"] == "mr_white":
        state["status"] = "mr_white_guess"
        state["eliminated_mr_white"] = elim_sid
    else:
        winner = check_victory(room)
        if winner:
            state["winner"] = winner
            state["status"] = "game_over"
        else:
            start_description_phase(room)
            
    broadcast_state(room)

@socketio.on('submit_guess')
def on_submit_guess(data):
    room = sid_to_room.get(request.sid)
    if not room or rooms[room]["status"] != "mr_white_guess": return
    
    state = rooms[room]
    if request.sid != state.get("eliminated_mr_white"): return
    
    guess = data.get("guess", "")
    player = next((p for p in state["players"] if p["sid"] == request.sid), None)
    civil_word = state.get("civil_word", "")
    
    if normalize_word(guess) == normalize_word(civil_word):
        socketio.emit('sys_msg', {'msg': f'Incroyable ! Mr. White ({player["name"]}) a trouvé le mot : {civil_word} ! Victoire des forces cachées !'}, room=room)
        state["winner"] = "mr_white"
        state["status"] = "game_over"
    else:
        socketio.emit('sys_msg', {'msg': f'Raté ! Mr. White pensait à "{guess}" au lieu de "{civil_word}". Son élimination est confirmée.'}, room=room)
        winner = check_victory(room)
        if winner:
            state["winner"] = winner
            state["status"] = "game_over"
        else:
            start_description_phase(room)
            
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
