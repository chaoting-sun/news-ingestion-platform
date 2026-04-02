from django.urls import path

from .views import (
    NewsDetailView,
    NewsListView,
    metrics_view,
    news_detail_page,
    news_list_page,
)

urlpatterns = [
    path("", news_list_page, name="news-list-page"),
    path("news/<int:pk>/", news_detail_page, name="news-detail-page"),
    path("api/news/", NewsListView.as_view(), name="news-list"),
    path("api/news/<int:pk>/", NewsDetailView.as_view(), name="news-detail"),
    path("metrics/", metrics_view, name="prometheus-metrics"),
]
