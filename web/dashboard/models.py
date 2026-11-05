from django.db import models


class Project(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.TextField()
    published_at = models.TextField()
    budget_amount = models.FloatField(null=True)
    budget_currency = models.TextField(null=True)
    budget_uah = models.FloatField(null=True)
    safe_type = models.TextField(null=True)
    skill_ids = models.TextField()
    bid_count = models.IntegerField(null=True)
    employer_id = models.IntegerField(null=True)
    employer_login = models.TextField(null=True)
    matched = models.IntegerField(default=0)
    reject_reason = models.TextField(null=True)
    notified_at = models.TextField(null=True)
    action = models.TextField(null=True)
    raw = models.TextField()
    first_seen_at = models.TextField()
    cross_category = models.IntegerField(default=0)
    score = models.IntegerField(null=True)
    score_reasons = models.TextField(null=True)

    class Meta:
        managed = False
        db_table = "projects"


class BlockedEmployer(models.Model):
    employer_id = models.IntegerField(primary_key=True)
    login = models.TextField(null=True)
    blocked_at = models.TextField()

    class Meta:
        managed = False
        db_table = "blocked_employers"


class Analysis(models.Model):
    project_id = models.IntegerField(primary_key=True)
    result = models.TextField()
    model = models.TextField()
    input_tokens = models.IntegerField()
    output_tokens = models.IntegerField()
    cache_read_tokens = models.IntegerField(default=0)
    created_at = models.TextField()

    class Meta:
        managed = False
        db_table = "analyses"


class Setting(models.Model):
    key = models.TextField(primary_key=True)
    value = models.TextField()

    class Meta:
        managed = False
        db_table = "settings"


class Bid(models.Model):
    project_id = models.IntegerField(primary_key=True)
    status = models.TextField()
    price_uah = models.FloatField(null=True)
    days = models.IntegerField(null=True)
    note = models.TextField(null=True)
    estimated_hours = models.FloatField(null=True)
    actual_hours = models.FloatField(null=True)
    source = models.TextField(default="manual")
    submitted_at = models.TextField()
    updated_at = models.TextField()

    class Meta:
        managed = False
        db_table = "bids"
