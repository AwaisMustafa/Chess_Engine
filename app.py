"""
Chess Engine — Flask Backend
Supports full chess rules: castling, en passant, promotion, check/checkmate/stalemate.
AI opponent uses random legal move selection.
"""
import random
import copy
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)

# ─────────────────────────────────────────────
# Board Setup
# ─────────────────────────────────────────────

def initial_board():
    board = [['' for _ in range(8)] for _ in range(8)]
    board[0] = ['br', 'bn', 'bb', 'bq', 'bk', 'bb', 'bn', 'br']
    board[1] = ['bp'] * 8
    board[6] = ['wp'] * 8
    board[7] = ['wr', 'wn', 'wb', 'wq', 'wk', 'wb', 'wn', 'wr']
    return board

def fresh_state():
    return {
        'board': initial_board(),
        'turn': 'w',
        'move_history': [],
        'en_passant': None,          # (row, col) of en passant target square
        'castling_rights': {
            'w': {'kingside': True, 'queenside': True},
            'b': {'kingside': True, 'queenside': True},
        },
        'status': 'playing',         # playing | check | checkmate | stalemate
        'captured': {'w': [], 'b': []},
    }

game_state = fresh_state()

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def color_of(piece): return piece[0] if piece else None
def type_of(piece):  return piece[1] if piece else None
def in_bounds(r, c): return 0 <= r < 8 and 0 <= c < 8

# ─────────────────────────────────────────────
# Raw Move Generation (ignores check)
# ─────────────────────────────────────────────

def raw_moves(board, r, c, en_passant=None):
    piece = board[r][c]
    if not piece:
        return []
    color, ptype = color_of(piece), type_of(piece)
    moves = []

    if ptype == 'p':
        d = -1 if color == 'w' else 1            # direction: white moves up (−), black down (+)
        # One step forward
        if in_bounds(r + d, c) and not board[r + d][c]:
            moves.append((r + d, c))
            # Two steps from starting rank
            start = 6 if color == 'w' else 1
            if r == start and not board[r + 2*d][c]:
                moves.append((r + 2*d, c))
        # Diagonal captures + en passant
        for dc in (-1, 1):
            nr, nc = r + d, c + dc
            if in_bounds(nr, nc):
                if board[nr][nc] and color_of(board[nr][nc]) != color:
                    moves.append((nr, nc))
                elif en_passant and (nr, nc) == tuple(en_passant):
                    moves.append((nr, nc))

    elif ptype == 'n':
        for dr, dc in ((-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)):
            nr, nc = r + dr, c + dc
            if in_bounds(nr, nc) and color_of(board[nr][nc]) != color:
                moves.append((nr, nc))

    elif ptype in ('b', 'r', 'q'):
        dirs = []
        if ptype in ('b', 'q'): dirs += [(-1,-1),(-1,1),(1,-1),(1,1)]
        if ptype in ('r', 'q'): dirs += [(-1,0),(1,0),(0,-1),(0,1)]
        for dr, dc in dirs:
            nr, nc = r + dr, c + dc
            while in_bounds(nr, nc):
                if board[nr][nc]:
                    if color_of(board[nr][nc]) != color:
                        moves.append((nr, nc))
                    break
                moves.append((nr, nc))
                nr += dr; nc += dc

    elif ptype == 'k':
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == dc == 0: continue
                nr, nc = r + dr, c + dc
                if in_bounds(nr, nc) and color_of(board[nr][nc]) != color:
                    moves.append((nr, nc))

    return moves

# ─────────────────────────────────────────────
# Check Detection
# ─────────────────────────────────────────────

def find_king(board, color):
    for r in range(8):
        for c in range(8):
            if board[r][c] == color + 'k':
                return r, c
    return None, None

def in_check(board, color):
    kr, kc = find_king(board, color)
    opp = 'b' if color == 'w' else 'w'
    for r in range(8):
        for c in range(8):
            if color_of(board[r][c]) == opp:
                if (kr, kc) in raw_moves(board, r, c):
                    return True
    return False

# ─────────────────────────────────────────────
# Board Mutation Helpers
# ─────────────────────────────────────────────

def apply_move(board, fr, fc, tr, tc, en_passant=None, promo='q'):
    b = copy.deepcopy(board)
    piece = b[fr][fc]
    color, ptype = color_of(piece), type_of(piece)

    # En passant removal
    if ptype == 'p' and en_passant and (tr, tc) == tuple(en_passant):
        b[fr][tc] = ''          # remove captured pawn (same row as mover, dest col)

    # Promotion
    if ptype == 'p' and tr in (0, 7):
        piece = color + promo

    b[tr][tc] = piece
    b[fr][fc] = ''
    return b

def apply_castle(board, color, side):
    b = copy.deepcopy(board)
    row = 7 if color == 'w' else 0
    if side == 'kingside':
        b[row][6], b[row][5] = color + 'k', color + 'r'
        b[row][4], b[row][7] = '', ''
    else:
        b[row][2], b[row][3] = color + 'k', color + 'r'
        b[row][4], b[row][0] = '', ''
    return b

# ─────────────────────────────────────────────
# Legal Move Generation
# ─────────────────────────────────────────────

def legal_moves(state, color):
    board = state['board']
    ep = state['en_passant']
    moves = []

    # Normal moves
    for r in range(8):
        for c in range(8):
            if color_of(board[r][c]) == color:
                for tr, tc in raw_moves(board, r, c, ep):
                    new_b = apply_move(board, r, c, tr, tc, ep)
                    if not in_check(new_b, color):
                        moves.append((r, c, tr, tc, None))

    # Castling
    row = 7 if color == 'w' else 0
    cr = state['castling_rights'][color]

    if cr['kingside'] and not board[row][5] and not board[row][6]:
        if not in_check(board, color):
            mid = apply_move(board, row, 4, row, 5)
            if not in_check(mid, color):
                final = apply_castle(board, color, 'kingside')
                if not in_check(final, color):
                    moves.append((row, 4, row, 6, 'castle_kingside'))

    if cr['queenside'] and not board[row][1] and not board[row][2] and not board[row][3]:
        if not in_check(board, color):
            mid = apply_move(board, row, 4, row, 3)
            if not in_check(mid, color):
                final = apply_castle(board, color, 'queenside')
                if not in_check(final, color):
                    moves.append((row, 4, row, 2, 'castle_queenside'))

    return moves

# ─────────────────────────────────────────────
# Execute Move & Update State
# ─────────────────────────────────────────────

def execute_move(state, fr, fc, tr, tc, promo='q'):
    board = state['board']
    piece = board[fr][fc]
    color, ptype = color_of(piece), type_of(piece)
    ep = state['en_passant']
    captured = board[tr][tc]
    special = None

    # Build new board
    if ptype == 'k' and abs(tc - fc) == 2:
        side = 'kingside' if tc > fc else 'queenside'
        new_board = apply_castle(board, color, side)
        special = f'castle_{side}'
    elif ptype == 'p' and ep and (tr, tc) == tuple(ep):
        captured = board[fr][tc]    # en passant pawn sits at (fr, tc)
        special = 'en_passant'
        new_board = apply_move(board, fr, fc, tr, tc, ep, promo)
    else:
        new_board = apply_move(board, fr, fc, tr, tc, ep, promo)

    # Update castling rights — moving king or rook
    if ptype == 'k':
        state['castling_rights'][color] = {'kingside': False, 'queenside': False}
    elif ptype == 'r':
        row = 7 if color == 'w' else 0
        if fr == row and fc == 7: state['castling_rights'][color]['kingside']  = False
        if fr == row and fc == 0: state['castling_rights'][color]['queenside'] = False

    # Update castling rights — opponent's rook captured
    if captured and type_of(captured) == 'r':
        cap_color = color_of(captured)
        cap_row = 7 if cap_color == 'w' else 0
        if tr == cap_row:
            if tc == 7: state['castling_rights'][cap_color]['kingside']  = False
            if tc == 0: state['castling_rights'][cap_color]['queenside'] = False

    # Update en passant target
    state['en_passant'] = [int((fr + tr) / 2), fc] if ptype == 'p' and abs(tr - fr) == 2 else None

    # Record capture
    if captured:
        state['captured'][color].append(captured)

    # Commit board & history
    state['board'] = new_board
    state['move_history'].append({
        'from': [fr, fc], 'to': [tr, tc],
        'piece': piece, 'captured': captured, 'special': special,
    })

    # Advance turn
    state['turn'] = 'b' if color == 'w' else 'w'

    # Determine game status
    opp = state['turn']
    opp_moves = legal_moves(state, opp)
    if not opp_moves:
        state['status'] = 'checkmate' if in_check(state['board'], opp) else 'stalemate'
    elif in_check(state['board'], opp):
        state['status'] = 'check'
    else:
        state['status'] = 'playing'

    return state

# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# Serve CSS
@app.route('/styles.css')
def styles():
    return send_from_directory('static', 'styles.css')

# Serve JS
@app.route('/script.js')
def script():
    return send_from_directory('static', 'script.js')

@app.route('/board', methods=['GET'])
def get_board():
    return jsonify({
        'board':        game_state['board'],
        'turn':         game_state['turn'],
        'status':       game_state['status'],
        'captured':     game_state['captured'],
        'move_history': game_state['move_history'][-40:],
    })

@app.route('/moves', methods=['POST'])
def get_legal_moves_for_piece():
    data = request.json
    r, c = data['row'], data['col']
    piece = game_state['board'][r][c]
    if not piece or color_of(piece) != game_state['turn']:
        return jsonify({'moves': []})
    moves = [(tr, tc) for fr, fc, tr, tc, _ in legal_moves(game_state, game_state['turn'])
             if fr == r and fc == c]
    return jsonify({'moves': moves})

@app.route('/move', methods=['POST'])
def make_move():
    data = request.json
    fr, fc = data['from_row'], data['from_col']
    tr, tc = data['to_row'],   data['to_col']
    promo  = data.get('promotion', 'q')

    if game_state['status'] in ('checkmate', 'stalemate'):
        return jsonify({'success': False, 'error': 'Game is over'})

    piece = game_state['board'][fr][fc]
    if not piece or color_of(piece) != game_state['turn']:
        return jsonify({'success': False, 'error': 'Not your piece'})

    all_legal = legal_moves(game_state, game_state['turn'])
    if not any(m[0] == fr and m[1] == fc and m[2] == tr and m[3] == tc for m in all_legal):
        return jsonify({'success': False, 'error': 'Illegal move'})

    execute_move(game_state, fr, fc, tr, tc, promo)

    return jsonify({
        'success':      True,
        'board':        game_state['board'],
        'turn':         game_state['turn'],
        'status':       game_state['status'],
        'captured':     game_state['captured'],
        'last_move':    game_state['move_history'][-1],
    })

@app.route('/ai_move', methods=['POST'])
def ai_move():
    if game_state['status'] in ('checkmate', 'stalemate'):
        return jsonify({'success': False, 'error': 'Game is over'})

    moves = legal_moves(game_state, game_state['turn'])
    if not moves:
        return jsonify({'success': False, 'error': 'No legal moves'})

    fr, fc, tr, tc, _ = random.choice(moves)
    execute_move(game_state, fr, fc, tr, tc)

    return jsonify({
        'success':   True,
        'board':     game_state['board'],
        'turn':      game_state['turn'],
        'status':    game_state['status'],
        'captured':  game_state['captured'],
        'last_move': game_state['move_history'][-1],
    })

@app.route('/status', methods=['GET'])
def get_status():
    return jsonify({
        'turn':             game_state['turn'],
        'status':           game_state['status'],
        'in_check':         in_check(game_state['board'], game_state['turn']),
        'legal_move_count': len(legal_moves(game_state, game_state['turn'])),
    })

@app.route('/reset', methods=['POST'])
def reset():
    global game_state
    game_state = fresh_state()
    return jsonify({'success': True})

if __name__ == '__main__':
    print("♟  Chess Engine running at http://localhost:5000")
    app.run(debug=True, port=5000)
