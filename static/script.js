
'use strict';

// ── Constants ──────────────────────────────────────────────────
const UNICODE = {
    wk: '♔', wq: '♕', wr: '♖', wb: '♗', wn: '♘', wp: '♙',
    bk: '♚', bq: '♛', br: '♜', bb: '♝', bn: '♞', bp: '♟'
};
const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
const RANKS = ['8', '7', '6', '5', '4', '3', '2', '1'];

// ── State ──────────────────────────────────────────────────────
let G = null;           // latest gameData from server
let selected = null;    // [r,c] of selected square
let legalTargets = [];  // [[r,c], ...]
let lastMove = null;    // {from:[r,c], to:[r,c]}
let mode = 'ai';
let aiThinking = false;
let pendingPromo = null;

// ── Init ───────────────────────────────────────────────────────
function initLabels() {
    const ranks = document.getElementById('rank-labels');
    const files = document.getElementById('file-labels');
    ranks.innerHTML = RANKS.map(r => `<span>${r}</span>`).join('');
    files.innerHTML = FILES.map(f => `<span>${f}</span>`).join('');
}

function setMode(m) {
    mode = m;
    document.getElementById('tog-ai').classList.toggle('active', m === 'ai');
    document.getElementById('tog-human').classList.toggle('active', m === 'human');
    document.getElementById('ai-btn').style.display = m === 'ai' ? 'block' : 'none';
}

// ── Board Render ───────────────────────────────────────────────
function renderBoard() {
    if (!G) return;
    const boardEl = document.getElementById('board');
    boardEl.innerHTML = '';

    const board = G.board;
    const inCheckColor = (G.status === 'check' || G.status === 'checkmate') ? G.turn : null;
    let kingCheckPos = null;
    if (inCheckColor) {
        for (let r = 0; r < 8; r++)
            for (let c = 0; c < 8; c++)
                if (board[r][c] === inCheckColor + 'k') kingCheckPos = `${r},${c}`;
    }

    for (let r = 0; r < 8; r++) {
        for (let c = 0; c < 8; c++) {
            const sq = document.createElement('div');
            sq.className = `sq ${(r + c) % 2 === 0 ? 'light' : 'dark'}`;

            // Highlight overlays
            if (selected && selected[0] === r && selected[1] === c)
                sq.classList.add('selected');
            if (lastMove) {
                if (lastMove.from[0] === r && lastMove.from[1] === c) sq.classList.add('last-from');
                if (lastMove.to[0] === r && lastMove.to[1] === c) sq.classList.add('last-to');
            }
            if (kingCheckPos === `${r},${c}`) sq.classList.add('in-check');

            const isTarget = legalTargets.some(([tr, tc]) => tr === r && tc === c);
            if (isTarget) {
                sq.classList.add(board[r][c] ? 'legal-capture' : 'legal-empty');
            }

            // Piece
            if (board[r][c]) {
                const p = document.createElement('span');
                p.className = `piece ${board[r][c][0] === 'w' ? 'white' : 'black'}`;
                p.textContent = UNICODE[board[r][c]] || '?';
                sq.appendChild(p);
            }

            sq.addEventListener('click', () => handleClick(r, c));
            boardEl.appendChild(sq);
        }
    }
}

// ── Click Handler ──────────────────────────────────────────────
async function handleClick(r, c) {
    if (!G) return;
    if (G.status === 'checkmate' || G.status === 'stalemate') return;
    if (aiThinking) return;
    if (mode === 'ai' && G.turn === 'b') return;

    const board = G.board;

    // If a legal target is clicked → move
    if (selected && legalTargets.some(([tr, tc]) => tr === r && tc === c)) {
        await doMove(selected[0], selected[1], r, c);
        return;
    }

    // Click own piece → select
    if (board[r][c] && board[r][c][0] === G.turn) {
        selected = [r, c];
        try {
            const res = await fetch('/moves', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ row: r, col: c })
            });
            legalTargets = (await res.json()).moves;
        } catch { legalTargets = []; }
        renderBoard();
        return;
    }

    // Deselect
    selected = null;
    legalTargets = [];
    renderBoard();
}

// ── Execute Move ───────────────────────────────────────────────
async function doMove(fr, fc, tr, tc, promo) {
    const piece = G.board[fr][fc];

    // Pawn promotion check
    if (piece && piece[1] === 'p' && !promo) {
        const promoRank = piece[0] === 'w' ? 0 : 7;
        if (tr === promoRank) {
            pendingPromo = { fr, fc, tr, tc };
            const icons = piece[0] === 'w'
                ? ['♕', '♖', '♗', '♘']
                : ['♛', '♜', '♝', '♞'];
            const btns = document.querySelectorAll('#promo-grid .promo-piece');
            btns.forEach((b, i) => b.textContent = icons[i]);
            document.getElementById('promo-overlay').classList.add('open');
            return;
        }
    }

    selected = null;
    legalTargets = [];

    try {
        const res = await fetch('/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ from_row: fr, from_col: fc, to_row: tr, to_col: tc, promotion: promo || 'q' })
        });
        const data = await res.json();

        if (data.success) {
            applyServerResponse(data);
            if (mode === 'ai' && data.turn === 'b' && data.status !== 'checkmate' && data.status !== 'stalemate') {
                setTimeout(triggerAI, 500);
            }
        } else {
            showToast(data.error || 'Illegal move');
            renderBoard();
        }
    } catch (e) { console.error('Move failed', e); }
}

function choosePromo(piece) {
    document.getElementById('promo-overlay').classList.remove('open');
    if (pendingPromo) {
        const { fr, fc, tr, tc } = pendingPromo;
        pendingPromo = null;
        doMove(fr, fc, tr, tc, piece);
    }
}

// ── AI ─────────────────────────────────────────────────────────
async function triggerAI() {
    if (aiThinking) return;
    if (G?.status === 'checkmate' || G?.status === 'stalemate') return;

    aiThinking = true;
    const btn = document.getElementById('ai-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Thinking…';

    try {
        const res = await fetch('/ai_move', { method: 'POST' });
        const data = await res.json();
        if (data.success) applyServerResponse(data);
    } catch (e) { console.error('AI failed', e); }

    aiThinking = false;
    btn.disabled = false;
    btn.innerHTML = 'AI Move';
}

// ── Apply Server Response ──────────────────────────────────────
function applyServerResponse(data) {
    const prev = G ? [...(G.move_history || [])] : [];

    G = {
        board: data.board,
        turn: data.turn,
        status: data.status,
        captured: data.captured,
        move_history: [...prev, ...(data.last_move ? [data.last_move] : [])]
    };

    if (data.last_move) {
        lastMove = { from: data.last_move.from, to: data.last_move.to };
    }

    selected = null;
    legalTargets = [];
    renderBoard();
    updateSidebar();

    const msgs = {
        checkmate: () => `Checkmate! ${data.turn === 'b' ? 'White' : 'Black'} wins! 🏆`,
        stalemate: () => "Stalemate — it's a draw.",
        check: () => `${data.turn === 'w' ? 'White' : 'Black'} is in check!`
    };
    if (msgs[data.status]) showToast(msgs[data.status]());
}

// ── Sidebar Updates ────────────────────────────────────────────
function updateSidebar() {
    if (!G) return;

    const dot = document.getElementById('status-dot');
    const main = document.getElementById('status-main');
    const sub = document.getElementById('status-sub');
    const alert = document.getElementById('status-alert');
    const wLabel = document.getElementById('white-label');
    const bLabel = document.getElementById('black-label');

    const turnName = G.turn === 'w' ? 'White' : 'Black';
    dot.className = `status-dot ${G.turn === 'w' ? 'white' : 'black'}`;

    wLabel.className = `player-name${G.turn === 'w' ? ' active-turn' : ''}`;
    bLabel.className = `player-name${G.turn === 'b' ? ' active-turn' : ''}`;

    if (G.status === 'checkmate') {
        const winner = G.turn === 'b' ? 'White' : 'Black';
        main.textContent = `${winner} wins`;
        sub.textContent = 'Checkmate';
        alert.textContent = '♚ Checkmate';
        alert.style.display = 'block';
    } else if (G.status === 'stalemate') {
        main.textContent = 'Draw';
        sub.textContent = 'Stalemate — no legal moves';
        alert.textContent = '= Stalemate';
        alert.style.display = 'block';
    } else if (G.status === 'check') {
        main.textContent = `${turnName} to move`;
        sub.textContent = 'Currently in check';
        alert.textContent = '⚠ Check!';
        alert.style.display = 'block';
    } else {
        main.textContent = `${turnName} to move`;
        sub.textContent = mode === 'ai' && G.turn === 'w' ? 'Your turn — click a piece'
            : mode === 'ai' ? 'AI is playing…'
                : 'Click a piece';
        alert.style.display = 'none';
    }

    updateHistory();
    updateCaptures();
}

// ── Move History ───────────────────────────────────────────────
function toAlgebraic(m) {
    if (!m) return '';
    if (m.special === 'castle_kingside') return 'O-O';
    if (m.special === 'castle_queenside') return 'O-O-O';
    const f = 'abcdefgh';
    const r = '87654321';
    let s = '';
    if (m.piece[1] !== 'p') s += m.piece[1].toUpperCase();
    if (m.captured || m.special === 'en_passant') s += 'x';
    s += f[m.to[1]] + r[m.to[0]];
    return s;
}

function updateHistory() {
    const el = document.getElementById('history');
    const hist = G.move_history || [];
    if (!hist.length) {
        el.innerHTML = '<div class="history-empty">No moves yet</div>';
        return;
    }
    let html = '';
    for (let i = 0; i < hist.length; i += 2) {
        const num = i / 2 + 1;
        const wm = hist[i];
        const bm = hist[i + 1];
        const last = hist.length - 1;
        const wCls = (i === last) ? 'latest' : '';
        const bCls = (i + 1 === last) ? 'latest' : '';
        html += `<div class="move-row">
      <span class="n">${num}.</span>
      <span class="w ${wCls}">${toAlgebraic(wm)}</span>
      <span class="b ${bCls}">${bm ? toAlgebraic(bm) : ''}</span>
    </div>`;
    }
    el.innerHTML = html;
    el.scrollTop = el.scrollHeight;
}

// ── Captured Pieces ────────────────────────────────────────────
function updateCaptures() {
    const capW = document.getElementById('cap-by-white');
    const capB = document.getElementById('cap-by-black');
    capW.innerHTML = (G.captured?.w || []).map(p => `<span>${UNICODE[p] || ''}</span>`).join('');
    capB.innerHTML = (G.captured?.b || []).map(p => `<span>${UNICODE[p] || ''}</span>`).join('');
}

// ── Reset ──────────────────────────────────────────────────────
async function resetGame() {
    await fetch('/reset', { method: 'POST' });
    G = null;
    selected = null;
    legalTargets = [];
    lastMove = null;
    aiThinking = false;
    const btn = document.getElementById('ai-btn');
    btn.disabled = false;
    btn.innerHTML = 'AI Move';
    await loadBoard();
    showToast('New game — White to move');
}

// ── Initial Load ───────────────────────────────────────────────
async function loadBoard() {
    const res = await fetch('/board');
    const data = await res.json();
    G = data;
    renderBoard();
    updateSidebar();
}

// ── Toast ──────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 3200);
}

// ── Boot ───────────────────────────────────────────────────────
initLabels();
loadBoard();
