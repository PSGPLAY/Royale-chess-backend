from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class PlayerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    nickname = models.CharField(max_length=50, blank=True)
    avatar = models.CharField(max_length=100, default='pirate_captain')
    
    # Persistent account currency (for purchasing cosmetic skins, boards, pieces)
    persistent_coins = models.PositiveIntegerField(default=100)
    
    # Competitive ranking
    rating_elo = models.PositiveIntegerField(default=1200)
    
    # Statistics
    total_matches = models.PositiveIntegerField(default=0)
    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    draws = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nickname or self.user.username} ({self.rating_elo} ELO)"

    @property
    def win_rate(self) -> float:
        if self.total_matches == 0:
            return 0.0
        return round((self.wins / self.total_matches) * 100, 1)


@receiver(post_save, sender=User)
def create_or_save_user_profile(sender, instance, created, **kwargs):
    if created:
        PlayerProfile.objects.create(
            user=instance,
            nickname=instance.username,
        )
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()
