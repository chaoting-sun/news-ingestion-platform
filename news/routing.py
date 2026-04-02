from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/news/", consumers.NewsConsumer.as_asgi()),
]
