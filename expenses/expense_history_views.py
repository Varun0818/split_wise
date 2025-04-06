from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.http import HttpResponse
from .models import Group, Expense
from datetime import datetime
import csv

@login_required
def user_expense_history(request):
    """
    Display all expenses the user has participated in across all groups
    """
    user = request.user
    
    # Get filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    group_id = request.GET.get('group_id')
    expense_type = request.GET.get('expense_type')
    sort_by = request.GET.get('sort_by', '-created_at')  # Default sort by newest
    
    # Get all expenses where the user is a participant
    expenses = Expense.objects.filter(
        Q(expenseparticipant__user=user) | Q(paid_by=user)
    ).distinct()
    
    # Apply filters if provided
    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d')
            expenses = expenses.filter(created_at__gte=date_from)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d')
            expenses = expenses.filter(created_at__lte=date_to)
        except ValueError:
            pass
    
    if group_id:
        expenses = expenses.filter(group_id=group_id)
    
    if expense_type:
        if expense_type == 'basic':
            expenses = expenses.filter(parent_expense__isnull=True, recurring_expense__isnull=True)
        elif expense_type == 'child':
            expenses = expenses.filter(parent_expense__isnull=False)
        elif expense_type == 'recurring':
            expenses = expenses.filter(recurring_expense__isnull=False)
    
    # Apply sorting
    expenses = expenses.order_by(sort_by)
    
    # Prefetch related data to optimize queries
    expenses = expenses.select_related('paid_by', 'group')
    expenses = expenses.prefetch_related('expenseparticipant_set__user', 'debt_set')
    
    # Enhance expense objects with user-specific data
    for expense in expenses:
        # Calculate what the user paid
        if expense.paid_by == user:
            expense.user_paid = expense.amount
        else:
            expense.user_paid = 0
        
        # Calculate what the user owes
        user_debts = expense.debt_set.filter(debtor=user)
        expense.user_owes = sum(debt.amount for debt in user_debts)
        
        # Calculate what others owe the user
        others_debts = expense.debt_set.filter(creditor=user)
        expense.user_owed = sum(debt.amount for debt in others_debts)
        
        # Calculate net contribution
        expense.net_contribution = expense.user_paid - expense.user_owes
    
    # Get all groups the user is a member of (for filter dropdown)
    user_groups = Group.objects.filter(members=user)
    
    # Pagination
    paginator = Paginator(expenses, 15)  # Show 15 expenses per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Export to CSV if requested
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="my_expenses.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Group', 'Title', 'Amount', 'Paid By', 'You Paid', 'You Owe', 'You Are Owed', 'Net', 'Date'])
        
        for expense in expenses:
            writer.writerow([
                expense.group.name,
                expense.title,
                expense.amount,
                expense.paid_by.username,
                expense.user_paid,
                expense.user_owes,
                expense.user_owed,
                expense.net_contribution,
                expense.created_at.strftime('%Y-%m-%d')
            ])
        
        return response
    
    context = {
        'page_obj': page_obj,
        'user_groups': user_groups,
        'filter_form': {
            'date_from': date_from,
            'date_to': date_to,
            'group_id': group_id,
            'expense_type': expense_type,
            'sort_by': sort_by
        }
    }
    
    return render(request, 'expenses/user_expense_history.html', context)