import uuid
from django.db import models
from django.contrib.auth.models import User


def default_shop_slots():
    return ['p', 'n', 'b']


class Match(models.Model):
    MODE_CHOICES = [
        ('normal', 'Normal Chess (Casual)'),
        ('ranked_normal', 'Ranked Normal Chess'),
        ('unranked_normal', 'Unranked Normal Chess'),
        ('royale', 'Royale Strategy (Ranked)'),
        ('ranked_royale', 'Ranked Royale'),
        ('unranked_royale', 'Unranked Royale (Casual)'),
    ]

    STATUS_CHOICES = [
        ('waiting', 'Waiting for Opponent'),
        ('active', 'Active Match'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mode = models.CharField(max_length=30, choices=MODE_CHOICES, default='royale')
    
    # Participants
    white_player = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='white_matches'
    )
    black_player = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='black_matches'
    )
    white_guest_name = models.CharField(max_length=50, blank=True, default='')
    black_guest_name = models.CharField(max_length=50, blank=True, default='')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    # Board state
    fen = models.CharField(max_length=120, default='4k3/8/8/8/8/8/8/4K3 w - - 0 1')
    turn = models.CharField(max_length=1, default='w') # 'w' or 'b'
    move_count = models.PositiveIntegerField(default=0)

    # Online match clocks: each player starts with 10 minutes (10+0).
    white_time_ms = models.PositiveIntegerField(default=600000)
    black_time_ms = models.PositiveIntegerField(default=600000)
    clock_started_at = models.DateTimeField(null=True, blank=True)
    
    # Match currency (Royale Mode)
    white_coins = models.PositiveIntegerField(default=4)
    black_coins = models.PositiveIntegerField(default=4)
    
    # Independent 3-slot shops
    white_shop_slots = models.JSONField(default=default_shop_slots)
    black_shop_slots = models.JSONField(default=default_shop_slots)
    
    # Resolution
    winner = models.CharField(max_length=10, blank=True, null=True) # 'w', 'b', or 'draw'
    end_reason = models.CharField(max_length=60, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Match {str(self.id)[:8]} [{self.mode}] - {self.status}"

    @property
    def is_royale_mode(self) -> bool:
        return self.mode in ('royale', 'unranked_royale', 'ranked_royale')


class MatchMove(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='moves')
    move_number = models.PositiveIntegerField()
    player = models.CharField(max_length=1) # 'w' or 'b'
    action_type = models.CharField(max_length=20) # 'move', 'deploy', 'capture', 'reroll', 'castle', 'promotion'
    
    piece_type = models.CharField(max_length=2, blank=True)
    from_square = models.CharField(max_length=4, blank=True)
    to_square = models.CharField(max_length=4, blank=True)
    
    description = models.CharField(max_length=200)
    san = models.CharField(max_length=20, blank=True)
    fen_after = models.CharField(max_length=120)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['move_number']

    def __str__(self):
        return f"Match {str(self.match.id)[:8]} #{self.move_number}: {self.description}"
