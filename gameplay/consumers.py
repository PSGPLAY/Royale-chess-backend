import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Match, MatchMove
from .serializers import MatchSerializer
from .services.chess_rules import (
    execute_server_move,
    execute_server_deploy,
    execute_server_reroll,
    execute_server_resign,
    finalize_match_stats,
    check_match_clock,
)


class MatchConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.match_id = str(self.scope['url_route']['kwargs']['match_id'])
        self.room_group_name = f"match_{self.match_id}"
        self.player_role = None

        # Join match room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

        # Send current match state upon connection
        match_data = await self.get_match_data()
        if match_data:
            await self.send_json({
                'type': 'sync_state',
                'match': match_data,
            })

    async def disconnect(self, close_code):
        # Leave match room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        # If an active player abruptly disconnects or closes tab, forfeit match
        if self.player_role in ('w', 'b'):
            abandon_match = await self.process_disconnect_abandon(self.player_role)
            if abandon_match:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'match_update',
                        'event': 'player_left',
                        'match': abandon_match,
                    }
                )

    async def receive_json(self, content):
        action = content.get('action')

        if action == 'make_move':
            from_sq = content.get('from')
            to_sq = content.get('to')
            promotion = content.get('promotion', 'q')
            success, msg, details = await self.process_move(from_sq, to_sq, promotion)
            if success:
                match_data = await self.get_match_data()
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'match_update',
                        'event': 'move',
                        'details': details,
                        'match': match_data,
                    }
                )
            else:
                await self.send_json({'type': 'error', 'message': msg})

        elif action == 'deploy_piece':
            player = content.get('player')
            piece_type = content.get('piece_type')
            square = content.get('square')
            success, msg, details = await self.process_deploy(player, piece_type, square)
            if success:
                match_data = await self.get_match_data()
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'match_update',
                        'event': 'deploy',
                        'details': details,
                        'match': match_data,
                    }
                )
            else:
                await self.send_json({'type': 'error', 'message': msg})

        elif action == 'reroll_shop':
            player = content.get('player')
            success, msg, details = await self.process_reroll(player)
            if success:
                match_data = await self.get_match_data()
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'match_update',
                        'event': 'reroll',
                        'details': details,
                        'match': match_data,
                    }
                )
            else:
                await self.send_json({'type': 'error', 'message': msg})

        elif action == 'join_match':
            self.player_role = content.get('player')

        elif action == 'check_clock':
            match_data = await self.process_clock_check()
            if match_data:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {'type': 'match_update', 'event': 'clock', 'match': match_data},
                )

        elif action in ('resign', 'leave'):
            player = content.get('player') or self.player_role
            if not player:
                await self.send_json({'type': 'error', 'message': 'Player identifier missing.'})
                return
            success, msg, details = await self.process_resign(player)
            if success:
                match_data = await self.get_match_data()
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'match_update',
                        'event': 'resign',
                        'details': details,
                        'match': match_data,
                    }
                )
            else:
                await self.send_json({'type': 'error', 'message': msg})

        elif action == 'chat':
            sender = content.get('sender', 'Anonymous')
            text = content.get('text', '')
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'sender': sender,
                    'text': text,
                }
            )

    async def match_update(self, event):
        await self.send_json(event)

    async def match_start(self, event):
        await self.send_json(event)

    async def chat_message(self, event):
        await self.send_json(event)

    # ── Database Sync Helpers ────────────────────────────────────────────────

    @database_sync_to_async
    def get_match_data(self):
        try:
            match = Match.objects.get(id=self.match_id)
            return MatchSerializer(match).data
        except Match.DoesNotExist:
            return None

    @database_sync_to_async
    def process_clock_check(self):
        try:
            match = Match.objects.get(id=self.match_id)
            check_match_clock(match)
            return MatchSerializer(match).data
        except Match.DoesNotExist:
            return None

    @database_sync_to_async
    def process_move(self, from_sq, to_sq, promotion):
        try:
            match = Match.objects.get(id=self.match_id)
            if match.status != 'active':
                return False, f"Match is {match.status}.", {}

            success, msg, details = execute_server_move(match, from_sq, to_sq, promotion)
            if success:
                MatchMove.objects.create(
                    match=match,
                    move_number=match.move_count,
                    player='w' if match.turn == 'b' else 'b',
                    action_type=details['action_type'],
                    piece_type=details['piece_type'],
                    from_square=details['from_square'],
                    to_square=details['to_square'],
                    san=details.get('san', ''),
                    description=details['description'],
                    fen_after=match.fen,
                )
            return success, msg, details
        except Exception as e:
            return False, str(e), {}

    @database_sync_to_async
    def process_deploy(self, player, piece_type, square):
        try:
            match = Match.objects.get(id=self.match_id)
            if match.status != 'active':
                return False, f"Match is {match.status}.", {}

            success, msg, details = execute_server_deploy(match, player, piece_type, square)
            if success:
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
            return success, msg, details
        except Exception as e:
            return False, str(e), {}

    @database_sync_to_async
    def process_reroll(self, player):
        try:
            match = Match.objects.get(id=self.match_id)
            if match.status != 'active':
                return False, f"Match is {match.status}.", {}

            success, msg, details = execute_server_reroll(match, player)
            if success:
                MatchMove.objects.create(
                    match=match,
                    move_number=match.move_count,
                    player=player,
                    action_type='reroll',
                    to_square='--',
                    description=details['description'],
                    fen_after=match.fen,
                )
            return success, msg, details
        except Exception as e:
            return False, str(e), {}

    @database_sync_to_async
    def process_resign(self, player):
        try:
            match = Match.objects.get(id=self.match_id)
            if match.status != 'active':
                return False, f"Match is {match.status}.", {}

            success, msg, details = execute_server_resign(match, player)
            if success:
                MatchMove.objects.create(
                    match=match,
                    move_number=match.move_count,
                    player=player,
                    action_type='resign',
                    to_square='--',
                    description=details['description'],
                    fen_after=match.fen,
                )
            return success, msg, details
        except Exception as e:
            return False, str(e), {}

    @database_sync_to_async
    def process_disconnect_abandon(self, player):
        try:
            match = Match.objects.get(id=self.match_id)
            if match.status == 'active':
                winner = 'b' if player == 'w' else 'w'
                match.status = 'completed'
                match.winner = winner
                match.end_reason = 'Abandonment'
                match.save()
                finalize_match_stats(match)

                leaver_name = 'Blue' if player == 'w' else 'Red'
                winner_name = 'Red' if winner == 'b' else 'Blue'
                desc = f"{leaver_name} disconnected. {winner_name} wins by abandonment!"

                MatchMove.objects.create(
                    match=match,
                    move_number=match.move_count,
                    player=player,
                    action_type='resign',
                    to_square='--',
                    description=desc,
                    fen_after=match.fen,
                )
                return MatchSerializer(match).data
        except Exception:
            pass
        return None


