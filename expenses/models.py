from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

# Add the CURRENCY_CHOICES definition
CURRENCY_CHOICES = [
    ('USD', 'US Dollar ($)'),
    ('EUR', 'Euro (€)'),
    ('GBP', 'British Pound (£)'),
    ('INR', 'Indian Rupee (₹)'),
    ('JPY', 'Japanese Yen (¥)'),
    ('CAD', 'Canadian Dollar (C$)'),
    ('AUD', 'Australian Dollar (A$)'),
    ('CNY', 'Chinese Yuan (¥)'),
]

class Group(models.Model):
    """
    Represents a group of users who share expenses together.
    Users can be part of multiple groups, and groups can have multiple users.
    """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(User, related_name='expense_groups')  # Changed related_name from 'groups' to 'expense_groups'
    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='administered_groups')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.name


class ParentExpense(models.Model):
    """
    Represents a parent expense that can have multiple child expenses.
    Used for complex expenses that need to be broken down into smaller parts.
    """
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='parent_expenses')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_parent_expenses')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['group']),
        ]

    def __str__(self):
        return f"{self.title} - {self.group.name}"

    @property
    def total_amount(self):
        """Calculate the total amount based on all child expenses"""
        return self.child_expenses.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')


class Expense(models.Model):
    """
    Represents an individual expense that can be either standalone or part of a parent expense.
    Each expense has a specific split type that determines how it's divided among participants.
    """
    SPLIT_TYPE_CHOICES = [
        ('EQUAL', 'Split Equally'),
        ('PERCENTAGE', 'Split by Percentage'),
        ('DIRECT', 'Split by Direct Amount'),
        ('PARENT_CHILD', 'Parent-Child Split'),
    ]

    title = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='paid_expenses')
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='expenses')
    parent_expense = models.ForeignKey(
        ParentExpense, 
        on_delete=models.CASCADE, 
        related_name='child_expenses',
        null=True, 
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    split_type = models.CharField(max_length=20, choices=SPLIT_TYPE_CHOICES, default='EQUAL')
    recurring_expense = models.ForeignKey('RecurringExpense', null=True, blank=True, on_delete=models.SET_NULL, related_name='expenses')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['group']),
            models.Index(fields=['paid_by']),
            models.Index(fields=['parent_expense']),
        ]

    def __str__(self):
        return f"{self.title} - ${self.amount} - {self.get_split_type_display()}"


class Split(models.Model):
    """
    Represents how an expense is split among users.
    Each split record connects a user to an expense with the specific amount they owe.
    """
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='splits')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expense_splits')
    amount_owed = models.DecimalField(max_digits=10, decimal_places=2)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ('expense', 'user')
        indexes = [
            models.Index(fields=['expense']),
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f"{self.user.username} owes ${self.amount_owed} for {self.expense.title}"


class Debt(models.Model):
    """
    Represents the net debt between two users, possibly within a specific group.
    This model helps track who owes whom and how much.
    """
    creditor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='credits')
    debtor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='debts')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='group_debts', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_settled = models.BooleanField(default=False)
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='debt_set', null=True, blank=True)

    class Meta:
        unique_together = ('creditor', 'debtor', 'group')
        indexes = [
            models.Index(fields=['creditor']),
            models.Index(fields=['debtor']),
            models.Index(fields=['group']),
            models.Index(fields=['updated_at']),
        ]

    def __str__(self):
        group_str = f" in {self.group.name}" if self.group else ""
        return f"{self.debtor.username} owes {self.creditor.username} ${self.amount}{group_str}"


class RecurringExpense(models.Model):
    """
    Represents an expense that repeats at regular intervals.
    When due, this will generate a new regular expense automatically.
    """
    FREQUENCY_CHOICES = [
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
    ]

    SPLIT_TYPE_CHOICES = [
        ('EQUAL', 'Split Equally'),
        ('PERCENTAGE', 'Split by Percentage'),
        ('DIRECT', 'Split by Direct Amount'),
        ('PARENT_CHILD', 'Parent-Child Split'),
    ]

    title = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='paid_recurring_expenses')
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='recurring_expenses')
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)
    next_due_date = models.DateField()
    split_type = models.CharField(max_length=20, choices=SPLIT_TYPE_CHOICES, default='EQUAL')
    participants = models.ManyToManyField(User, related_name='recurring_expenses')
    parent_expense = models.ForeignKey(
        ParentExpense, 
        on_delete=models.CASCADE, 
        related_name='recurring_child_expenses',
        null=True, 
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Fix the syntax error - remove the unexpected parentheses
    split_details = models.TextField(blank=True, null=True)  # Add this field if it doesn't exist

    class Meta:
        ordering = ['next_due_date']
        indexes = [
            models.Index(fields=['next_due_date']),
            models.Index(fields=['group']),
            models.Index(fields=['paid_by']),
            models.Index(fields=['frequency']),
        ]

    def __str__(self):
        return f"{self.title} - ${self.amount} - {self.get_frequency_display()} - Next due: {self.next_due_date}"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    preferred_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='USD')
    notification_preferences = models.JSONField(default=dict)
    
    def __str__(self):
        return f"{self.user.username}'s profile"
