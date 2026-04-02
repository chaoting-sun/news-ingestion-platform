from django.db import models


class News(models.Model):
    title = models.CharField(max_length=500)
    author = models.CharField(max_length=200, blank=True)
    published_at = models.DateTimeField()
    source_name = models.CharField(max_length=100)
    source_url = models.URLField(unique=True)
    content = models.TextField()
    hero_image_url = models.URLField(blank=True)
    hero_image_caption = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at"]
        verbose_name_plural = "news"
        indexes = [
            models.Index(fields=["-published_at"]),
        ]

    def __str__(self):
        return self.title
