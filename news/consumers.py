from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer

GROUP_NAME = "news_updates"


class NewsConsumer(JsonWebsocketConsumer):
    def connect(self):
        async_to_sync(self.channel_layer.group_add)(GROUP_NAME, self.channel_name)
        self.accept()

    def disconnect(self, close_code):
        async_to_sync(self.channel_layer.group_discard)(GROUP_NAME, self.channel_name)

    def new_article(self, event):
        self.send_json(event)
