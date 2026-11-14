"""
Server-Authoritative Chess & Royale Mode Engine.
Uses python-chess to validate every move, deployment, and purchase.
The client is NEVER trusted with rule legality or currency transactions.
"""

import random
import chess
from typing import Tuple, Dict, Any, List
from django.utils import timezone

PIECE_PRICES: Dict[str, int] = {
    'p': 1, # Pawn: 1 coin
    'n': 2, # Knight: 2 coins
    'b': 2, # Bishop: 2 coins
    'r': 3, # Rook: 3 coins
    'q': 4, # Queen: 4 coins
}

PIECE_BOUNTIES: Dict[str, int] = {
    'p': 1,
    'n': 1,
    'b': 1,
    'r': 2,
    'q': 2,
    'k': 0,
}

PIECE_NAMES: Dict[str, str] = {
    'p': 'Pawn',
    'n': 'Knight',
    'b': 'Bishop',
    'r': 'Rook',
    'q': 'Queen',
    'k': 'King',
}

SHOP_RELOAD_COST = 1
MATCH_CLOCK_MS = 10 * 60 * 1000


def check_match_clock(match, now=None) -> bool:
    """Finish the match if the active player's server clock has expired."""
    if match.status != 'active' or not match.clock_started_at:
        return match.status == 'active'

    now = now or timezone.now()
    field = 'white_time_ms' if match.turn == 'w' else 'black_time_ms'
    elapsed_ms = max(0, int((now - match.clock_started_at).total_seconds() * 1000))
    if elapsed_ms < getattr(match, field):
        return True

    setattr(match, field, 0)
    match.status = 'completed'
    match.winner = 'b' if match.turn == 'w' else 'w'
    match.end_reason = 'Timeout'
    match.clock_started_at = None
    match.save()
    finalize_match_stats(match)
    return False


def finish_clock_action(match, player: str, now=None) -> None:
    """Charge elapsed time to the mover and start the opponent's clock."""
    if not match.clock_started_at:
        return
    now = now or timezone.now()
    field = 'white_time_ms' if player == 'w' else 'black_time_ms'
    elapsed_ms = max(0, int((now - match.clock_started_at).total_seconds() * 1000))
    setattr(match, field, max(0, getattr(match, field) - elapsed_ms))
    match.clock_started_at = now if match.status == 'active' else None


def _has_any_legal_spawn(board: chess.Board, player: str, shop_slots: list, coins: int) -> bool:
    """
    Returns True if the given player has at least one shop piece they can afford
    and legally place on the board to resolve an active check.
    Used by Royale Mode to prevent false checkmates when a spawn could save the king.
    """
    piece_map = {
        'p': chess.PAWN,
        'n': chess.KNIGHT,
        'b': chess.BISHOP,
        'r': chess.ROOK,
        'q': chess.QUEEN,
    }
    color = chess.WHITE if player == 'w' else chess.BLACK

    for p_type in shop_slots:
        cost = PIECE_PRICES.get(p_type, 99)
        if coins < cost:
            continue

        if p_type == 'p':
            allowed_ranks = [2, 3, 4] if player == 'w' else [5, 6, 7]
        else:
            allowed_ranks = [1, 2, 3, 4] if player == 'w' else [5, 6, 7, 8]

        chess_piece_type = piece_map.get(p_type)
        if chess_piece_type is None:
            continue

        for rank in allowed_ranks:
            for file_idx in range(8):
                sq = chess.square(file_idx, rank - 1)  # chess.square uses 0-indexed rank
                if board.piece_at(sq) is not None:
                    continue
                # Temporarily place the piece and test whether the check is resolved
                test_piece = chess.Piece(chess_piece_type, color)
                board.set_piece_at(sq, test_piece)
                still_in_check = board.is_check()
                board.remove_piece_at(sq)
                if not still_in_check:
                    return True

    return False


def roll_shop_slots(count: int = 3) -> List[str]:
    """
    Rolls 3 random piece cards from the pool.
    Weighted distribution: Pawns common (35%), Knights (25%), Bishops (20%), Rooks (13%), Queens (7%).
    """
    pool = [
        ('p', 35),
        ('n', 25),
        ('b', 20),
        ('r', 13),
        ('q', 7),
    ]
    pieces, weights = zip(*pool)
    return random.choices(pieces, weights=weights, k=count)


def execute_server_move(
    match, from_sq: str, to_sq: str, promotion: str = 'q'
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates and executes a standard or promotion piece move on the server.
    Awards +1 coin for a non-capture, or half the captured piece's price rounded up.
    """
    clock_now = timezone.now()
    if not check_match_clock(match, clock_now):
        return False, "Your time has expired.", {}
    player = match.turn
    board = chess.Board(match.fen)
    
    # Verify it's the correct turn
    expected_turn = chess.WHITE if match.turn == 'w' else chess.BLACK
    if board.turn != expected_turn:
        return False, "It is not your turn.", {}

    from_square = chess.parse_square(from_sq.lower())
    to_square = chess.parse_square(to_sq.lower())
    
    piece = board.piece_at(from_square)
    if not piece:
        return False, f"No piece found at {from_sq.upper()}.", {}
    
    if piece.color != expected_turn:
        return False, "You cannot move the opponent's piece.", {}

    # Check for promotion
    is_promo = (
        piece.piece_type == chess.PAWN
        and (
            (piece.color == chess.WHITE and to_sq.endswith('8'))
            or (piece.color == chess.BLACK and to_sq.endswith('1'))
        )
    )

    promo_type = None
    if is_promo:
        promo_map = {
            'q': chess.QUEEN,
            'r': chess.ROOK,
            'b': chess.BISHOP,
            'n': chess.KNIGHT,
        }
        promo_type = promo_map.get(promotion.lower(), chess.QUEEN)

    move = chess.Move(from_square, to_square, promotion=promo_type)
    if move not in board.legal_moves:
        return False, f"Illegal move from {from_sq.upper()} to {to_sq.upper()}.", {}

    # Check for captures - Kings can NEVER be captured in chess!
    captured_piece = board.piece_at(to_square)
    if captured_piece and captured_piece.piece_type == chess.KING:
        return False, "Kings cannot be captured in chess.", {}

    is_en_passant = board.is_en_passant(move)
    is_castling = board.is_castling(move)
    san = board.san(move)

    # Execute move on the server board
    board.push(move)

    # Award currency in Royale mode
    if match.is_royale_mode:
        if player == 'w':
            if captured_piece:
                symbol = captured_piece.symbol().lower()
                match.white_coins += PIECE_BOUNTIES.get(symbol, 1)
            elif is_en_passant:
                match.white_coins += 1 # captured a pawn
            else:
                match.white_coins += 1
        else:
            if captured_piece:
                symbol = captured_piece.symbol().lower()
                match.black_coins += PIECE_BOUNTIES.get(symbol, 1)
            elif is_en_passant:
                match.black_coins += 1
            else:
                match.black_coins += 1

    # Update match state
    match.fen = board.fen()
    match.turn = 'w' if board.turn == chess.WHITE else 'b'
    match.move_count += 1

    # Resolve Game Over
    is_royale = match.is_royale_mode
    if board.is_checkmate():
        # ── Royale Mode: chess.js / python-chess only considers board moves,
        #    not shop spawns. If the losing player can still afford a spawn that
        #    blocks the check, it is NOT a true checkmate — do not end the match.
        if is_royale:
            loser = 'b' if player == 'w' else 'w'  # player who is now in check
            loser_slots = match.black_shop_slots if loser == 'b' else match.white_shop_slots
            loser_coins = match.black_coins if loser == 'b' else match.white_coins
            if not _has_any_legal_spawn(board, loser, loser_slots, loser_coins):
                match.status = 'completed'
                match.winner = player  # the player who just moved won
                match.end_reason = 'Checkmate'
                finalize_match_stats(match)
            # else: player can still spawn a blocker — game continues
        else:
            match.status = 'completed'
            match.winner = player  # the player who just moved won
            match.end_reason = 'Checkmate'
            finalize_match_stats(match)
    elif board.is_stalemate():
        match.status = 'completed'
        match.winner = 'draw'
        match.end_reason = 'Stalemate'
        finalize_match_stats(match)
    elif not is_royale and board.is_insufficient_material():
        match.status = 'completed'
        match.winner = 'draw'
        match.end_reason = 'Insufficient Material'
        finalize_match_stats(match)
    elif board.is_fivefold_repetition():
        match.status = 'completed'
        match.winner = 'draw'
        match.end_reason = 'Repetition'
        finalize_match_stats(match)

    # Determine description
    mover_name = 'Blue' if player == 'w' else 'Red'
    piece_name = PIECE_NAMES.get(piece.symbol().lower(), 'Piece')
    action_type = 'move'

    if captured_piece or is_en_passant:
        action_type = 'capture'
        cap_sym = captured_piece.symbol().lower() if captured_piece else 'p'
        desc = f"{mover_name} {piece_name} captured {PIECE_NAMES.get(cap_sym, 'Piece')} at {to_sq.upper()}"
    elif is_castling:
        action_type = 'castle'
        desc = f"{mover_name} King castled"
    elif is_promo:
        action_type = 'promotion'
        desc = f"{mover_name} Pawn promoted to {PIECE_NAMES.get(promotion.lower(), 'Queen')} at {to_sq.upper()}"
    else:
        desc = f"{mover_name} moved {piece_name} {from_sq.upper()} → {to_sq.upper()}"

    finish_clock_action(match, player, clock_now)
    match.save()

    return True, "Move executed successfully.", {
        'action_type': action_type,
        'piece_type': piece.symbol().lower(),
        'from_square': from_sq.lower(),
        'to_square': to_sq.lower(),
        'san': san,
        'description': desc,
        'is_check': board.is_check(),
        'is_checkmate': board.is_checkmate(),
    }


def execute_server_deploy(
    match, player: str, piece_type: str, square_name: str
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Server-authoritative unit deployment for Royale Mode.
    Verifies:
      1. Player turn matches
      2. Piece is in player's current 3 shop slots
      3. Player has enough coins
      4. Target square is in legal deployment territory:
         - White pieces: ranks 1 to 4; White pawns: ranks 2 to 4
         - Black pieces: ranks 5 to 8; Black pawns: ranks 5 to 7
      5. Target square is not occupied
    Deducts coins, re-rolls that player's shop, and skips turn to opponent.
    """
    clock_now = timezone.now()
    if not check_match_clock(match, clock_now):
        return False, "Your time has expired.", {}
    if not match.is_royale_mode:
        return False, "Deployments are only allowed in Royale Mode.", {}

    if match.turn != player:
        return False, "It is not your turn to recruit pieces.", {}

    p_type = piece_type.lower()
    cost = PIECE_PRICES.get(p_type)
    if cost is None:
        return False, f"Invalid piece type '{piece_type}'.", {}

    # Verify slot availability
    player_slots = match.white_shop_slots if player == 'w' else match.black_shop_slots
    if p_type not in player_slots:
        return False, f"Piece '{PIECE_NAMES.get(p_type)}' is not currently in your shop slots.", {}

    # Verify funds
    player_coins = match.white_coins if player == 'w' else match.black_coins
    if player_coins < cost:
        return False, f"Insufficient coins (costs {cost}, you have {player_coins}).", {}

    # Verify legal ranks (White: 1-4, Black: 5-8; Pawns cannot be placed on edge ranks 1 or 8)
    sq = square_name.lower()
    if p_type == 'p':
        allowed_ranks = ('2', '3', '4') if player == 'w' else ('5', '6', '7')
    else:
        allowed_ranks = ('1', '2', '3', '4') if player == 'w' else ('5', '6', '7', '8')

    if not any(sq.endswith(r) for r in allowed_ranks):
        return False, f"{PIECE_NAMES.get(p_type)} can only be placed on ranks {', '.join(allowed_ranks)}.", {}

    # Verify square is not occupied
    board = chess.Board(match.fen)
    target_square = chess.parse_square(sq)
    if board.piece_at(target_square) is not None:
        return False, f"Square {sq.upper()} is already occupied.", {}

    # Place piece in python-chess board
    piece_map = {
        'p': chess.PAWN,
        'n': chess.KNIGHT,
        'b': chess.BISHOP,
        'r': chess.ROOK,
        'q': chess.QUEEN,
    }
    chess_color = chess.WHITE if player == 'w' else chess.BLACK
    new_piece = chess.Piece(piece_map[p_type], chess_color)
    board.set_piece_at(target_square, new_piece)

    # Verify that this deployment does NOT leave the player's King in check!
    if board.is_check():
        return False, "Illegal deployment: Your King is in check and this placement does not resolve the check.", {}

    # Toggle active turn in FEN
    tokens = board.fen().split(' ')
    tokens[1] = 'b' if player == 'w' else 'w'
    match.fen = ' '.join(tokens)
    match.turn = tokens[1]
    match.move_count += 1

    # Deduct currency
    if player == 'w':
        match.white_coins -= cost
        match.white_shop_slots = roll_shop_slots(3)
    else:
        match.black_coins -= cost
        match.black_shop_slots = roll_shop_slots(3)

    mover_name = 'Blue' if player == 'w' else 'Red'
    desc = f"{mover_name} spawned {PIECE_NAMES[p_type]} at {sq.upper()}"

    finish_clock_action(match, player, clock_now)
    match.save()

    return True, "Piece deployed successfully.", {
        'action_type': 'deploy',
        'piece_type': p_type,
        'to_square': sq,
        'description': desc,
    }


def execute_server_reroll(
    match, player: str
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Rerolls the active player's independent 3 shop slots for 1 coin.
    Skips that player's turn to the opponent.
    """
    clock_now = timezone.now()
    if not check_match_clock(match, clock_now):
        return False, "Your time has expired.", {}
    if not match.is_royale_mode:
        return False, "Shop rerolls are only available in Royale Mode.", {}

    if match.turn != player:
        return False, "It is not your turn to reroll.", {}

    # Disallow reroll / passing turn while in check
    board = chess.Board(match.fen)
    if board.is_check():
        return False, "Cannot reroll shop while your King is in check. You must resolve the check!", {}

    player_coins = match.white_coins if player == 'w' else match.black_coins
    if player_coins < SHOP_RELOAD_COST:
        return False, f"Need at least {SHOP_RELOAD_COST} coin to reroll.", {}

    # Deduct 1 coin & refresh slots
    if player == 'w':
        match.white_coins -= SHOP_RELOAD_COST
        match.white_shop_slots = roll_shop_slots(3)
    else:
        match.black_coins -= SHOP_RELOAD_COST
        match.black_shop_slots = roll_shop_slots(3)

    # Skip turn to opponent in FEN
    tokens = match.fen.split(' ')
    tokens[1] = 'b' if player == 'w' else 'w'
    match.fen = ' '.join(tokens)
    match.turn = tokens[1]
    match.move_count += 1

    mover_name = 'Blue' if player == 'w' else 'Red'
    desc = f"{mover_name} rerolled shop (-1 🪙, turn passed)"

    finish_clock_action(match, player, clock_now)
    match.save()

    return True, "Shop rerolled successfully.", {
        'action_type': 'reroll',
        'to_square': '--',
        'description': desc,
    }


def execute_server_resign(match, player: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Handles a player resigning the match.
    Awards victory to the opponent and updates profiles.
    """
    if not check_match_clock(match):
        return False, "The match has already ended.", {}
    if match.status != 'active':
        return False, f"Match is {match.status}.", {}

    if player not in ('w', 'b'):
        return False, "Invalid player color.", {}

    winner = 'b' if player == 'w' else 'w'
    match.status = 'completed'
    match.winner = winner
    match.end_reason = 'Resignation'
    match.clock_started_at = None
    match.save()

    finalize_match_stats(match)

    resigner_name = 'Blue' if player == 'w' else 'Red'
    winner_name = 'Red' if player == 'w' else 'Blue'
    desc = f"{resigner_name} resigned. {winner_name} wins by resignation!"

    return True, desc, {
        'action_type': 'resign',
        'winner': winner,
        'resigner': player,
        'description': desc,
    }


def finalize_match_stats(match) -> None:
    """
    Updates player ELO ratings, persistent gold currency, and match records
    when a match concludes.
    """
    try:
        white_profile = match.white_player.profile if match.white_player else None
        black_profile = match.black_player.profile if match.black_player else None

        winner = match.winner

        if white_profile and black_profile:
            # Full ELO calculation between two registered players
            rw = white_profile.rating_elo
            rb = black_profile.rating_elo

            ew = 1.0 / (1.0 + 10.0 ** ((rb - rw) / 400.0))
            eb = 1.0 - ew

            if winner == 'w':
                sw, sb = 1.0, 0.0
            elif winner == 'b':
                sw, sb = 0.0, 1.0
            else:
                sw, sb = 0.5, 0.5

            k = 32
            delta_w = round(k * (sw - ew))
            delta_b = round(k * (sb - eb))

            white_profile.rating_elo = max(100, rw + delta_w)
            black_profile.rating_elo = max(100, rb + delta_b)

        # Update match tallies & persistent coins
        for prof, role in [(white_profile, 'w'), (black_profile, 'b')]:
            if not prof:
                continue
            prof.total_matches += 1
            if winner == role:
                prof.wins += 1
                prof.persistent_coins += 25  # Victory reward
            elif winner == 'draw':
                prof.draws += 1
                prof.persistent_coins += 10  # Draw reward
            else:
                prof.losses += 1
                prof.persistent_coins += 5   # Consolation reward
            prof.save()

    except Exception:
        # Ignore profile update failures (e.g. guest players without profiles)
        pass


