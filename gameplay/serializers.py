from rest_framework import serializers
from .models import Match, MatchMove


class MatchMoveSerializer(serializers.ModelSerializer):
    class Meta:
        model = MatchMove
        fields = [
            'id',
            'move_number',
            'player',
            'action_type',
            'piece_type',
            'from_square',
            'to_square',
            'description',
            'san',
            'fen_after',
            'created_at',
        ]


class MatchSerializer(serializers.ModelSerializer):
    moves = MatchMoveSerializer(many=True, read_only=True)
    white_username = serializers.SerializerMethodField()
    black_username = serializers.SerializerMethodField()
    white_time_remaining_ms = serializers.SerializerMethodField()
    black_time_remaining_ms = serializers.SerializerMethodField()

    class Meta:
        model = Match
        fields = [
            'id',
            'mode',
            'status',
            'white_player',
            'black_player',
            'white_guest_name',
            'black_guest_name',
            'white_username',
            'black_username',
            'fen',
            'turn',
            'move_count',
            'white_time_remaining_ms',
            'black_time_remaining_ms',
            'white_coins',
            'black_coins',
            'white_shop_slots',
            'black_shop_slots',
            'winner',
            'end_reason',
            'moves',
            'created_at',
            'updated_at',
        ]

    def get_white_username(self, obj):
        if obj.white_player:
            return getattr(obj.white_player, 'profile', None) and (obj.white_player.profile.nickname or obj.white_player.username)
        return obj.white_guest_name or 'Blue Commander'

    def get_white_time_remaining_ms(self, obj):
        return self._remaining_ms(obj, 'w')

    def get_black_time_remaining_ms(self, obj):
        return self._remaining_ms(obj, 'b')

    @staticmethod
    def _remaining_ms(obj, color):
        remaining = obj.white_time_ms if color == 'w' else obj.black_time_ms
        if obj.status == 'active' and obj.clock_started_at and obj.turn == color:
            from django.utils import timezone
            elapsed = max(0, int((timezone.now() - obj.clock_started_at).total_seconds() * 1000))
            remaining = max(0, remaining - elapsed)
        return remaining

    def get_black_username(self, obj):
        if obj.black_player:
            return getattr(obj.black_player, 'profile', None) and (obj.black_player.profile.nickname or obj.black_player.username)
        return obj.black_guest_name or 'Red Commander'


class CreateMatchSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=Match.MODE_CHOICES, default='royale'
    )
    play_as = serializers.ChoiceField(
        choices=['w', 'b', 'random'], default='w', required=False
    )
    guest_name = serializers.CharField(required=False, allow_blank=True, default='')


class MatchmakeSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=Match.MODE_CHOICES, default='royale'
    )
    guest_name = serializers.CharField(required=False, allow_blank=True, default='')
