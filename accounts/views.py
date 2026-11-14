from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from .models import PlayerProfile
from .serializers import RegisterSerializer, PlayerProfileSerializer, LeaderboardSerializer


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            token, _ = Token.objects.get_or_create(user=user)
            profile_serializer = PlayerProfileSerializer(user.profile)
            return Response({
                'token': token.key,
                'user': profile_serializer.data,
                'message': 'Account created successfully!'
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        identifier = str(request.data.get('username') or request.data.get('email') or '').strip()
        password = request.data.get('password')

        if not identifier or not password:
            return Response(
                {'error': 'Both username/email and password are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. First attempt to authenticate directly with identifier as username
        user = authenticate(username=identifier, password=password)

        # 2. If not authenticated, check if identifier matches a registered email
        if not user:
            for candidate in User.objects.filter(email__iexact=identifier):
                user = authenticate(username=candidate.username, password=password)
                if user:
                    break

        if not user:
            return Response(
                {'error': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        token, _ = Token.objects.get_or_create(user=user)
        profile_serializer = PlayerProfileSerializer(user.profile)
        return Response({
            'token': token.key,
            'user': profile_serializer.data,
            'message': f'Welcome aboard, Captain {user.profile.nickname or user.username}!'
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            request.user.auth_token.delete()
        except Exception:
            pass
        return Response({'message': 'Logged out successfully.'})


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = PlayerProfileSerializer(request.user.profile)
        return Response(serializer.data)

    def patch(self, request):
        profile = request.user.profile
        nickname = request.data.get('nickname')
        avatar = request.data.get('avatar')

        if nickname is not None:
            profile.nickname = str(nickname).strip()
        if avatar is not None:
            profile.avatar = str(avatar).strip()

        profile.save()
        serializer = PlayerProfileSerializer(profile)
        return Response(serializer.data)


class LeaderboardView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        limit = min(int(request.query_params.get('limit', 20)), 100)
        top_players = PlayerProfile.objects.order_by('-rating_elo')[:limit]
        serializer = LeaderboardSerializer(top_players, many=True)
        return Response(serializer.data)
