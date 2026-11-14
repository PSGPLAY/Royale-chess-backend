from django.urls import path
from .views import (
    MatchmakeView,
    CancelMatchmakingView,
    CreateMatchView,
    MatchDetailView,
    SubmitMoveView,
    DeployPieceView,
    RerollShopView,
    ResignMatchView,
    UserMatchesView,
    CheckMatchClockView,
)

urlpatterns = [
    path('matches/matchmake/', MatchmakeView.as_view(), name='match-matchmake'),
    path('matches/<uuid:match_id>/cancel/', CancelMatchmakingView.as_view(), name='match-cancel'),
    path('matches/create/', CreateMatchView.as_view(), name='match-create'),
    path('matches/history/', UserMatchesView.as_view(), name='match-history'),
    path('matches/<uuid:match_id>/', MatchDetailView.as_view(), name='match-detail'),
    path('matches/<uuid:match_id>/clock/', CheckMatchClockView.as_view(), name='match-clock'),
    path('matches/<uuid:match_id>/move/', SubmitMoveView.as_view(), name='match-move'),
    path('matches/<uuid:match_id>/deploy/', DeployPieceView.as_view(), name='match-deploy'),
    path('matches/<uuid:match_id>/reroll/', RerollShopView.as_view(), name='match-reroll'),
    path('matches/<uuid:match_id>/resign/', ResignMatchView.as_view(), name='match-resign'),
]
