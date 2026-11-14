import random
from datetime import timedelta
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Match, MatchMove
from .serializers import MatchSerializer, CreateMatchSerializer, MatchmakeSerializer
from .services.chess_rules import (
    execute_server_move,
    execute_server_deploy,
    execute_server_reroll,
    execute_server_resign,
    roll_shop_slots,
)


class MatchmakeView(APIView):
    """
    Chess.com-style quick matchmaking.
    Searches for an open match waiting for an opponent.
    If found, connects the two players and sets match to active.
    If none found, creates a waiting room.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MatchmakeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        mode = serializer.validated_data.get('mode', 'royale')
        guest_name = serializer.validated_data.get('guest_name', '').strip()
        user = request.user if request.user.is_authenticated else None

        # 1. Clean up stale waiting matches (older than 2 minutes) so ghost rooms never block matching
        stale_threshold = timezone.now() - timedelta(minutes=2)
        Match.objects.filter(status='waiting', created_at__lt=stale_threshold).update(status='abandoned')

        # 2. Look for open matches waiting in this mode
        waiting_matches = Match.objects.filter(mode=mode, status='waiting').order_by('created_at')

        # In production, prevent user from matching themselves; in DEBUG mode, allow matching for multi-device testing
        if not settings.DEBUG:
            if user:
                waiting_matches = waiting_matches.exclude(white_player=user)
            elif guest_name:
                waiting_matches = waiting_matches.exclude(white_guest_name=guest_name)

        matched = waiting_matches.first()

        if matched:
            # Player 1 is the player who created the waiting room
            p1_user = matched.white_player
            p1_guest = matched.white_guest_name

            # Player 2 is the player joining now
            p2_user = user
            p2_guest = guest_name or f"Guest_{random.randint(1000, 9999)}"

            # 50/50 Random pick for who gets White ('w') and Black ('b')
            p1_gets_white = random.choice([True, False])

            if p1_gets_white:
                matched.white_player = p1_user
                matched.white_guest_name = p1_guest
                matched.black_player = p2_user
                matched.black_guest_name = p2_guest
                p1_role = 'w'
                p2_role = 'b'
            else:
                matched.white_player = p2_user
                matched.white_guest_name = p2_guest
                matched.black_player = p1_user
                matched.black_guest_name = p1_guest
                p1_role = 'b'
                p2_role = 'w'

            matched.status = 'active'
            matched.clock_started_at = timezone.now()
            matched.save()

            # Broadcast to waiting player via Channels WebSocket
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f"match_{matched.id}",
                    {
                        'type': 'match_start',
                        'creator_role': p1_role,
                        'joiner_role': p2_role,
                        'match': MatchSerializer(matched).data,
                    }
                )

            return Response({
                'status': 'connected',
                'role': p2_role,
                'match': MatchSerializer(matched).data,
                'message': 'Connected to opponent!',
            }, status=status.HTTP_200_OK)

        # No match waiting -> Create new match and wait
        is_royale = mode in ('royale', 'unranked_royale', 'ranked_royale')
        starting_fen = (
            '4k3/8/8/8/8/8/8/4K3 w - - 0 1'
            if is_royale
            else 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
        )

        match = Match.objects.create(
            mode=mode,
            fen=starting_fen,
            turn='w',
            white_player=user,
            white_guest_name='' if user else (guest_name or f"Guest_{random.randint(1000, 9999)}"),
            white_coins=4 if is_royale else 0,
            black_coins=4 if is_royale else 0,
            white_shop_slots=roll_shop_slots(3) if is_royale else [],
            black_shop_slots=roll_shop_slots(3) if is_royale else [],
            status='waiting',
        )

        return Response({
            'status': 'waiting',
            'role': 'w',
            'match': MatchSerializer(match).data,
            'message': 'Searching for an opponent...',
        }, status=status.HTTP_201_CREATED)


class CancelMatchmakingView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, match_id):
        match = get_object_or_404(Match, id=match_id)
        if match.status == 'waiting':
            match.status = 'abandoned'
            match.save()
            return Response({'message': 'Matchmaking cancelled.'})
        return Response({'message': 'Match is not in waiting state.'}, status=status.HTTP_400_BAD_REQUEST)


class CreateMatchView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CreateMatchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        mode = serializer.validated_data.get('mode', 'royale')
        play_as = serializer.validated_data.get('play_as', 'w')
        guest_name = serializer.validated_data.get('guest_name', '').strip()
        if play_as == 'random':
            play_as = random.choice(['w', 'b'])

        user = request.user if request.user.is_authenticated else None

        is_royale = mode in ('royale', 'unranked_royale', 'ranked_royale')
        starting_fen = (
            '4k3/8/8/8/8/8/8/4K3 w - - 0 1'
            if is_royale
            else 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
        )

        match = Match.objects.create(
            mode=mode,
            fen=starting_fen,
            turn='w',
            white_player=user if play_as == 'w' else None,
            black_player=user if play_as == 'b' else None,
            white_guest_name=guest_name if (play_as == 'w' and not user) else '',
            black_guest_name=guest_name if (play_as == 'b' and not user) else '',
            white_coins=4 if is_royale else 0,
            black_coins=4 if is_royale else 0,
            white_shop_slots=roll_shop_slots(3),
            black_shop_slots=roll_shop_slots(3),
            status='active',
            clock_started_at=timezone.now(),
        )

        return Response(MatchSerializer(match).data, status=status.HTTP_201_CREATED)


class MatchDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, match_id):
        match = get_object_or_404(Match, id=match_id)
        return Response(MatchSerializer(match).data)


class CheckMatchClockView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, match_id):
        match = get_object_or_404(Match, id=match_id)
        from .services.chess_rules import check_match_clock
        was_active = match.status == 'active'
        check_match_clock(match)
        if was_active and match.status != 'active':
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f"match_{match.id}",
                    {'type': 'match_update', 'event': 'clock', 'match': MatchSerializer(match).data},
                )
        return Response(MatchSerializer(match).data)


class SubmitMoveView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, match_id):
        match = get_object_or_404(Match, id=match_id)
        if match.status != 'active':
            return Response(
                {'error': f'Match is already {match.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from_square = request.data.get('from')
        to_square = request.data.get('to')
        promotion = request.data.get('promotion', 'q')

        if not from_square or not to_square:
            return Response(
                {'error': "Both 'from' and 'to' squares are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        success, msg, details = execute_server_move(
            match, from_square, to_square, promotion
        )
        if not success:
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

        # Record action in match moves
        MatchMove.objects.create(
            match=match,
            move_number=match.move_count,
            player='w' if match.turn == 'b' else 'b', # player who just moved
            action_type=details['action_type'],
            piece_type=details['piece_type'],
            from_square=details['from_square'],
            to_square=details['to_square'],
            san=details.get('san', ''),
            description=details['description'],
            fen_after=match.fen,
        )

        match_data = MatchSerializer(match).data

        # Broadcast move via WebSocket
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"match_{match.id}",
                {
                    'type': 'match_update',
                    'event': 'move',
                    'details': details,
                    'match': match_data,
                }
            )

        return Response({
            'message': msg,
            'details': details,
            'match': match_data,
        })


class DeployPieceView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, match_id):
        match = get_object_or_404(Match, id=match_id)
        if match.status != 'active':
            return Response(
                {'error': f'Match is already {match.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        player = request.data.get('player', match.turn)
        piece_type = request.data.get('piece_type')
        square = request.data.get('square')

        if not piece_type or not square:
            return Response(
                {'error': "Both 'piece_type' and 'square' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        success, msg, details = execute_server_deploy(
            match, player, piece_type, square
        )
        if not success:
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

        MatchMove.objects.create(
            match=match,
            move_number=match.move_count,
            player=player,
            action_type='deploy',
            piece_type=details['piece_type'],
            to_square=details['to_square'],
            description=details['description'],
            fen_after=match.fen,
        )

        match_data = MatchSerializer(match).data

        # Broadcast deployment via WebSocket
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"match_{match.id}",
                {
                    'type': 'match_update',
                    'event': 'deploy',
                    'details': details,
                    'match': match_data,
                }
            )

        return Response({
            'message': msg,
            'details': details,
            'match': match_data,
        })


class RerollShopView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, match_id):
        match = get_object_or_404(Match, id=match_id)
        if match.status != 'active':
            return Response(
                {'error': f'Match is already {match.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        player = request.data.get('player', match.turn)
        success, msg, details = execute_server_reroll(match, player)
        if not success:
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

        MatchMove.objects.create(
            match=match,
            move_number=match.move_count,
            player=player,
            action_type='reroll',
            to_square='--',
            description=details['description'],
            fen_after=match.fen,
        )

        match_data = MatchSerializer(match).data

        # Broadcast reroll via WebSocket
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"match_{match.id}",
                {
                    'type': 'match_update',
                    'event': 'reroll',
                    'details': details,
                    'match': match_data,
                }
            )

        return Response({
            'message': msg,
            'details': details,
            'match': match_data,
        })


class ResignMatchView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, match_id):
        match = get_object_or_404(Match, id=match_id)
        player = request.data.get('player')
        if not player and request.user.is_authenticated:
            if match.white_player == request.user:
                player = 'w'
            elif match.black_player == request.user:
                player = 'b'

        if player not in ('w', 'b'):
            return Response({'error': 'Player color ("w" or "b") is required.'}, status=status.HTTP_400_BAD_REQUEST)

        success, msg, details = execute_server_resign(match, player)
        if not success:
            return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

        match_data = MatchSerializer(match).data

        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"match_{match.id}",
                {
                    'type': 'match_update',
                    'event': 'resign',
                    'details': details,
                    'match': match_data,
                }
            )

        return Response({
            'message': msg,
            'details': details,
            'match': match_data,
        })



class UserMatchesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        matches = Match.objects.filter(
            white_player=user
        ) | Match.objects.filter(
            black_player=user
        )
        serializer = MatchSerializer(matches[:25], many=True)
        return Response(serializer.data)
