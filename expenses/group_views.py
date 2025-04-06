from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, Count, F, Case, When, Value, DecimalField
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden, HttpResponse
from .models import Group, Expense, ExpenseParticipant, Debt
from django.contrib.auth.models import User
from datetime import datetime
import csv

@login_required
def group_list(request):
    """
    Display all groups the logged-in user is a member of
    """
    user = request.user
    
    # Get all groups the user is a member of with additional stats
    groups = Group.objects.filter(members=user).annotate(
        member_count=Count('members', distinct=True),
        expense_count=Count('expense', distinct=True),
        total_expenses=Coalesce(Sum('expense__amount'), 0),
        # Calculate user's balance in each group
        user_owes=Coalesce(Sum(
            Case(
                When(expense__debt__debtor=user, then=F('expense__debt__amount')),
                default=Value(0),
                output_field=DecimalField()
            )
        ), 0),
        user_owed=Coalesce(Sum(
            Case(
                When(expense__debt__creditor=user, then=F('expense__debt__amount')),
                default=Value(0),
                output_field=DecimalField()
            )
        ), 0)
    ).order_by('name')
    
    # Calculate net balance for each group
    for group in groups:
        group.net_balance = group.user_owed - group.user_owes
    
    context = {
        'groups': groups
    }
    
    return render(request, 'expenses/group_list.html', context)

@login_required
def group_detail(request, group_id):
    """
    Display details for a specific group
    """
    user = request.user
    group = get_object_or_404(Group, pk=group_id)
    
    # Check if user is a member of the group
    if user not in group.members.all():
        return HttpResponseForbidden("You are not a member of this group")
    
    # Get recent expenses for this group
    recent_expenses = Expense.objects.filter(group=group).order_by('-created_at')[:5]
    
    # Get members with their balances
    members = group.members.all()
    member_balances = {}
    
    for member in members:
        # Calculate what member owes
        owes = Debt.objects.filter(
            expense__group=group,
            debtor=member,
            is_settled=False
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total']
        
        # Calculate what member is owed
        owed = Debt.objects.filter(
            expense__group=group,
            creditor=member,
            is_settled=False
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total']
        
        # Calculate net balance
        net_balance = owed - owes
        
        member_balances[member] = {
            'owes': owes,
            'owed': owed,
            'net_balance': net_balance
        }
    
    context = {
        'group': group,
        'recent_expenses': recent_expenses,
        'members': members,
        'member_balances': member_balances
    }
    
    return render(request, 'expenses/group_detail.html', context)

@login_required
def group_expense_history(request, group_id):
    """
    Display expense history for a specific group
    """
    user = request.user
    group = get_object_or_404(Group, pk=group_id)
    
    # Check if user is a member of the group
    if user not in group.members.all():
        return HttpResponseForbidden("You are not a member of this group")
    
    # Get filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    expense_type = request.GET.get('expense_type')
    sort_by = request.GET.get('sort_by', '-created_at')  # Default sort by newest
    
    # Base query for expenses in this group
    expenses = Expense.objects.filter(group=group)
    
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
    expenses = expenses.select_related('paid_by', 'group', 'parent_expense', 'recurring_expense')
    expenses = expenses.prefetch_related('expenseparticipant_set__user', 'debt_set__debtor', 'debt_set__creditor')
    
    # Pagination
    paginator = Paginator(expenses, 10)  # Show 10 expenses per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Export to CSV if requested
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{group.name}_expenses.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Title', 'Amount', 'Paid By', 'Date', 'Split Type'])
        
        for expense in expenses:
            writer.writerow([
                expense.title,
                expense.amount,
                expense.paid_by.username,
                expense.created_at.strftime('%Y-%m-%d'),
                expense.split_type
            ])
        
        return response
    
    context = {
        'group': group,
        'page_obj': page_obj,
        'filter_form': {
            'date_from': date_from,
            'date_to': date_to,
            'expense_type': expense_type,
            'sort_by': sort_by
        }
    }
    
    return render(request, 'expenses/group_expense_history.html', context)