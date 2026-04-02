from django.http import HttpResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    generate_latest,
    multiprocess,
)
from rest_framework.generics import ListAPIView, RetrieveAPIView

from .models import News
from .serializers import NewsDetailSerializer, NewsListSerializer


class NewsListView(ListAPIView):
    # # Avoid loading large content field in list API to reduce query size and memory usage
    queryset = News.objects.defer("content")
    serializer_class = NewsListSerializer

    @method_decorator(cache_page(60))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class NewsDetailView(RetrieveAPIView):
    queryset = News.objects.all()
    serializer_class = NewsDetailSerializer


def news_list_page(request):
    return render(request, "news/news_list.html")


def news_detail_page(request, pk):
    return render(request, "news/news_detail.html", {"pk": pk})


def metrics_view(request):
    """Expose Prometheus metrics at /metrics."""
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
