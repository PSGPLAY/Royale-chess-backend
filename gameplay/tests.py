from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from .models import Match, MatchMove
from .services.chess_rules import _has_any_legal_spawn
import chess


class RoyalChessBackendTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='captain_jack', email='jack@sparrow.com', password='securepassword123'
        )

    def test_auth_registration(self):
        response = self.client.post('/api/auth/register/', {
            'username': 'blackbeard',
            'email': 'blackbeard@pirate.com',
            'password': 'piratepassword123',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertEqual(response.data['user']['username'], 'blackbeard')
        self.assertEqual(response.data['user']['rating_elo'], 1200)

    def test_auth_login(self):
        response = self.client.post('/api/auth/login/', {
            'username': 'captain_jack',
            'password': 'securepassword123',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)

    def test_auth_login_with_email(self):
        response = self.client.post('/api/auth/login/', {
            'username': 'jack@sparrow.com',
            'password': 'securepassword123',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        self.assertEqual(response.data['user']['username'], 'captain_jack')

    def test_create_royale_match(self):
        response = self.client.post('/api/matches/create/', {
            'mode': 'royale',
            'play_as': 'w',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        match_id = response.data['id']
        self.assertEqual(response.data['mode'], 'royale')
        self.assertEqual(response.data['white_coins'], 4)
        self.assertEqual(response.data['black_coins'], 4)
        self.assertEqual(len(response.data['white_shop_slots']), 3)

        # Retrieve match
        get_res = self.client.get(f'/api/matches/{match_id}/')
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)

    def test_server_authoritative_deploy(self):
        match = Match.objects.create(
            mode='royale',
            fen='4k3/8/8/8/8/8/8/4K3 w - - 0 1',
            turn='w',
            white_coins=4,
            white_shop_slots=['p', 'n', 'b'],
        )

        # Deploy pawn on e2 (costs 1 coin)
        response = self.client.post(f'/api/matches/{match.id}/deploy/', {
            'player': 'w',
            'piece_type': 'p',
            'square': 'e2',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        match.refresh_from_db()
        self.assertEqual(match.white_coins, 3) # 4 - 1
        self.assertEqual(match.turn, 'b') # turn passed to black
        self.assertIn('4k3', match.fen)
        self.assertIn('4P3', match.fen)

        # Deploy pawn on e4 (rank 4, center of board)
        match.turn = 'w'
        match.white_coins = 4
        match.white_shop_slots = ['p', 'n', 'b']
        match.save()
        res_rank4 = self.client.post(f'/api/matches/{match.id}/deploy/', {
            'player': 'w',
            'piece_type': 'p',
            'square': 'e4',
        })
        self.assertEqual(res_rank4.status_code, status.HTTP_200_OK)

        # Black deploys knight on d5 (rank 5, center of board)
        match.refresh_from_db()
        match.turn = 'b'
        match.black_coins = 4
        match.black_shop_slots = ['n', 'b', 'q']
        match.save()
        res_rank5 = self.client.post(f'/api/matches/{match.id}/deploy/', {
            'player': 'b',
            'piece_type': 'n',
            'square': 'd5',
        })
        self.assertEqual(res_rank5.status_code, status.HTTP_200_OK)

        # White cannot deploy beyond center (rank 5)
        match.refresh_from_db()
        match.turn = 'w'
        match.white_coins = 4
        match.white_shop_slots = ['p', 'n', 'b']
        match.save()
        res_illegal = self.client.post(f'/api/matches/{match.id}/deploy/', {
            'player': 'w',
            'piece_type': 'p',
            'square': 'e5',
        })
        self.assertEqual(res_illegal.status_code, status.HTTP_400_BAD_REQUEST)

    def test_server_authoritative_reroll(self):
        match = Match.objects.create(
            mode='royale',
            fen='4k3/8/8/8/8/8/8/4K3 w - - 0 1',
            turn='w',
            white_coins=4,
            white_shop_slots=['p', 'p', 'p'],
        )

        response = self.client.post(f'/api/matches/{match.id}/reroll/', {
            'player': 'w',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        match.refresh_from_db()
        self.assertEqual(match.white_coins, 3) # 4 - 1
        self.assertEqual(match.turn, 'b') # turn passed to black
        self.assertEqual(len(match.white_shop_slots), 3)

    def test_server_authoritative_move(self):
        match = Match.objects.create(
            mode='normal',
            fen='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
            turn='w',
        )

        # Move e2 to e4
        response = self.client.post(f'/api/matches/{match.id}/move/', {
            'from': 'e2',
            'to': 'e4',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        match.refresh_from_db()
        self.assertEqual(match.turn, 'b')
        self.assertIn('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR', match.fen)

    def test_quick_matchmaking_flow(self):
        user2 = User.objects.create_user(username='admiral_nelson', password='password123')

        # Player 1 searches for match
        self.client.force_authenticate(user=self.user)
        res1 = self.client.post('/api/matches/matchmake/', {'mode': 'royale'})
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res1.data['status'], 'waiting')
        self.assertEqual(res1.data['role'], 'w')
        match_id = res1.data['match']['id']

        # Player 2 searches for match -> paired immediately
        self.client.force_authenticate(user=user2)
        res2 = self.client.post('/api/matches/matchmake/', {'mode': 'royale'})
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data['status'], 'connected')
        self.assertIn(res2.data['role'], ('w', 'b'))
        p2_role = res2.data['role']
        p1_role = 'b' if p2_role == 'w' else 'w'
        self.assertEqual(res2.data['match']['id'], match_id)
        self.assertEqual(res2.data['match']['status'], 'active')

        # Player 2 resigns
        res_resign = self.client.post(f'/api/matches/{match_id}/resign/', {'player': p2_role})
        self.assertEqual(res_resign.status_code, status.HTTP_200_OK)
        self.assertEqual(res_resign.data['match']['status'], 'completed')
        self.assertEqual(res_resign.data['match']['winner'], p1_role)

        # Check profiles
        self.user.profile.refresh_from_db()
        user2.profile.refresh_from_db()
        self.assertEqual(self.user.profile.wins, 1)
        self.assertEqual(self.user.profile.persistent_coins, 125) # 100 starting + 25 win
        self.assertGreater(self.user.profile.rating_elo, 1200) # rating increased
        self.assertEqual(user2.profile.losses, 1)
        self.assertEqual(user2.profile.persistent_coins, 105) # 100 starting + 5 consolation
        self.assertLess(user2.profile.rating_elo, 1200) # rating decreased

    def test_royale_false_checkmate_blocked_by_spawn(self):
        """
        Royale Mode: When python-chess declares checkmate but the losing player
        still has a shop piece they can afford that blocks the check, the match
        must NOT be ended — the player should get a chance to spawn.

        Position: Black king on a8, Black rook on g8, Black queen on h8.
        White king on h1.
        In standard chess: Kh1 has no moves (g1, g2 attacked by Rg8; h2 attacked by Qh8).
        Qh8 checks Kh1 along the h-file. python-chess declares checkmate!
        In Royale mode: White can spawn a Rook on h2 (or h3/h4) to block the check!
        """
        fen = 'k5rq/8/8/8/8/8/8/7K w - - 0 1'
        board = chess.Board(fen)
        self.assertTrue(board.is_check(), "White king should be in check")
        self.assertTrue(board.is_checkmate(), "python-chess should report checkmate")

        # _has_any_legal_spawn: White has rook (cost 3) in shop with 4 coins
        # A rook placed on h2 would block the queen's check along h-file
        can_spawn = _has_any_legal_spawn(board, 'w', ['r'], 4)
        self.assertTrue(can_spawn, "White should be able to spawn a rook on h2 to block the check")

        # Now simulate match in Royale mode
        match = Match.objects.create(
            mode='royale',
            fen=fen,
            turn='w',
            white_coins=4,
            white_shop_slots=['r', 'n', 'b'],
            black_coins=4,
            black_shop_slots=['p', 'p', 'p'],
            status='active',
        )
        spawn_check = _has_any_legal_spawn(
            chess.Board(match.fen), 'w',
            match.white_shop_slots, match.white_coins
        )
        self.assertTrue(spawn_check, "Match: white should be able to escape via spawn")

    def test_royale_true_checkmate_no_affordable_spawn(self):
        """
        Royale Mode: When the king is in check, has no legal moves, and cannot
        afford any shop piece (or no shop piece can block), it IS a true checkmate.
        """
        fen = 'k5rq/8/8/8/8/8/8/7K w - - 0 1'
        board = chess.Board(fen)
        self.assertTrue(board.is_checkmate())

        # With 0 coins, no spawn is possible
        can_spawn_broke = _has_any_legal_spawn(board, 'w', ['r', 'n', 'q'], 0)
        self.assertFalse(can_spawn_broke, "With 0 coins white cannot spawn anything")

        # With empty shop white cannot spawn anything
        can_spawn_empty = _has_any_legal_spawn(board, 'w', [], 10)
        self.assertFalse(can_spawn_empty, "With empty shop white cannot spawn anything")

    def test_has_any_legal_spawn_helper(self):
        """Unit tests for the _has_any_legal_spawn helper function."""
        # King on e1, Queen on e8 gives check along e-file.
        # Placing any piece on e2, e3, e4 blocks the check.
        fen = 'k3q3/8/8/8/8/8/8/4K3 w - - 0 1'
        board = chess.Board(fen)
        self.assertTrue(board.is_check())

        # White with a pawn (cost 1) and 2 coins can block on e2/e3/e4
        self.assertTrue(_has_any_legal_spawn(board, 'w', ['p'], 2))

        # With 0 coins cannot afford anything
        self.assertFalse(_has_any_legal_spawn(board, 'w', ['p'], 0))

        # Empty shop returns False
        self.assertFalse(_has_any_legal_spawn(board, 'w', [], 99))
