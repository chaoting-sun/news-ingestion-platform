from django.contrib import admin

from .models import News


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "published_at", "source_name", "created_at")
    list_filter = ("source_name", "published_at")
    search_fields = ("title", "author", "content")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-published_at",)
