from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count, F, Case, When, Value, DecimalField
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden, HttpResponse
from django.contrib.auth.models import User
from .models import Group, Expense, Split, Debt
from .forms import GroupForm  # Add this import
from datetime import datetime
import csv

@login_required
def group_list(request):
    """
    Display all groups the logged-in user is a member of
    """
    user = request.user
    
    # Get all groups the user is a member of using raw SQL to avoid admin field issues
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT g.id, g.name, g.description, g.created_at
            FROM expenses_group g
            INNER JOIN expenses_group_members gm ON g.id = gm.group_id
            WHERE gm.user_id = %s
        """, [user.id])
        group_data = cursor.fetchall()
    
    # Create Group objects from raw data
    groups = []
    for row in group_data:
        group = Group(id=row[0], name=row[1], description=row[2], created_at=row[3])
        
        # Member count
        group.member_count = Group.objects.get(id=group.id).members.count()
        
        # Expense count and total
        expenses = Expense.objects.filter(group_id=group.id)
        group.expense_count = expenses.count()
        group.total_expenses = expenses.aggregate(total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField())))['total']
        
        # Calculate user's balance in this group
        # Amount owed by this user
        user_owes = Debt.objects.filter(
            debtor=user,
            expense__group_id=group.id,
            is_settled=False
        ).aggregate(
            total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
        )['total']
        
        # Amount to be received by this user
        user_owed = Debt.objects.filter(
            creditor=user,
            expense__group_id=group.id,
            is_settled=False
        ).aggregate(
            total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
        )['total']
        
        # Calculate net balance
        group.user_owes = user_owes
        group.user_owed = user_owed
        group.net_balance = user_owed - user_owes
        
        # Set is_admin attribute to False by default
        group.is_admin = False
        
        groups.append(group)
    
    # Sort groups by name
    groups = sorted(groups, key=lambda g: g.name)
    
    context = {
        'groups': groups
    }
    
    return render(request, 'expenses/group_list.html', context)

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
    # Fix: Use the correct related name for splits and debts
    expenses = expenses.prefetch_related('splits__user', 'debt_set__debtor', 'debt_set__creditor')
    
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
        Q(split__user=user) | Q(paid_by=user)
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
    expenses = expenses.prefetch_related('split_set__user', 'debt_set')
    
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

@login_required
def group_detail(request, group_id):
    """View to display details of a specific group"""
    try:
        # Try to get the group using the ORM first
        group = get_object_or_404(Group, pk=group_id)
        
        # Check if user is a member of the group
        if request.user not in group.members.all():
            messages.error(request, "You don't have permission to view this group.")
            return redirect('group_list')
        
        # Get all members of the group
        members = group.members.all()
        
        # Get all expenses in this group
        expenses = Expense.objects.filter(group=group).order_by('-created_at')[:10]
        
        # Calculate balances for each member
        member_balances = {}
        for member in members:
            # Amount paid by this member
            paid_amount = Expense.objects.filter(
                group=group,
                paid_by=member
            ).aggregate(
                total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
            )['total']
            
            # Amount owed by this member
            owed_amount = Debt.objects.filter(
                debtor=member,
                expense__group=group,
                is_settled=False
            ).aggregate(
                total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
            )['total']
            
            # Amount to be received by this member
            to_receive_amount = Debt.objects.filter(
                creditor=member,
                expense__group=group,
                is_settled=False
            ).aggregate(
                total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
            )['total']
            
            # Calculate net balance
            net_balance = to_receive_amount - owed_amount
            
            member_balances[member] = {
                'paid': paid_amount,
                'owed': owed_amount,
                'to_receive': to_receive_amount,
                'net_balance': net_balance
            }
        
        # Set is_admin attribute safely - avoid using the admin field directly
        is_admin = False
        
        context = {
            'group': group,
            'members': members,
            'expenses': expenses,
            'member_balances': member_balances,
            'is_admin': is_admin
        }
        
        return render(request, 'expenses/group_detail.html', context)
        
    except Exception as e:
        # Log the error
        import traceback
        print(f"Error in group_detail view: {e}")
        print(traceback.format_exc())
        messages.error(request, "An error occurred while loading the group details. Please try again later.")
        return redirect('group_list')

@login_required
def create_group(request):
    """View to create a new group"""
    if request.method == 'POST':
        form = GroupForm(request.POST)
        if form.is_valid():
            # Create the group but don't save it yet
            group = form.save(commit=False)
            
            # Set the creator as the admin
            group.admin = request.user
            group.save()
            
            # Add the creator as a member
            group.members.add(request.user)
            
            # Add selected members
            members = form.cleaned_data.get('members')
            if members:
                group.members.add(*members)
            
            messages.success(request, f"Group '{group.name}' was created successfully!")
            return redirect('group_detail', group_id=group.id)
    else:
        form = GroupForm()
    
    return render(request, 'expenses/create_group.html', {'form': form})

# Add this function after the create_group function

@login_required
def edit_group(request, group_id):
    """View to edit an existing group"""
    group = get_object_or_404(Group, id=group_id)
    
    # Set is_admin to False by default
    is_admin = False
    
    # Check if the user is the admin (if the field exists)
    try:
        if hasattr(group, 'admin') and group.admin == request.user:
            is_admin = True
    except:
        pass
    
    if not is_admin:
        messages.error(request, "You don't have permission to edit this group.")
        return redirect('group_detail', group_id=group.id)
    
    if request.method == 'POST':
        form = GroupForm(request.POST, instance=group)
        if form.is_valid():
            # Update the group
            form.save()
            
            # Update members
            current_members = set(group.members.all())
            new_members = set(form.cleaned_data.get('members', []))
            
            # Always keep the admin as a member
            if group.admin not in new_members:
                new_members.add(group.admin)
            
            # Add new members
            for member in new_members - current_members:
                group.members.add(member)
            
            # Remove members who were removed
            for member in current_members - new_members:
                # Don't remove the admin
                if member != group.admin:
                    group.members.remove(member)
            
            messages.success(request, f"Group '{group.name}' was updated successfully!")
            return redirect('group_detail', group_id=group.id)
    else:
        form = GroupForm(instance=group)
    
    context = {
        'form': form,
        'group': group
    }
    
    return render(request, 'expenses/edit_group.html', context)

# Add this function after the edit_group function

@login_required
def delete_group(request, group_id):
    """View to delete an existing group"""
    group = get_object_or_404(Group, id=group_id)
    
    # Check if user is the admin of the group
    if group.admin != request.user:
        messages.error(request, "You don't have permission to delete this group.")
        return redirect('group_detail', group_id=group.id)
    
    if request.method == 'POST':
        group_name = group.name
        group.delete()
        messages.success(request, f"Group '{group_name}' was deleted successfully!")
        return redirect('group_list')
    
    context = {
        'group': group
    }
    
    return render(request, 'expenses/delete_group.html', context)

# Add this function after the delete_group function

@login_required
def add_group_members(request, group_id):
    """View to add members to an existing group"""
    group = get_object_or_404(Group, id=group_id)
    
    # Check if user is the admin of the group
    if group.admin != request.user:
        messages.error(request, "You don't have permission to add members to this group.")
        return redirect('group_detail', group_id=group.id)
    
    if request.method == 'POST':
        # Get the list of user IDs to add
        user_ids = request.POST.getlist('users')
        
        if not user_ids:
            messages.error(request, "Please select at least one user to add.")
            return redirect('add_group_members', group_id=group.id)
        
        # Get the users from the database
        users_to_add = User.objects.filter(id__in=user_ids)
        
        # Add the users to the group
        for user in users_to_add:
            if user not in group.members.all():
                group.members.add(user)
        
        messages.success(request, f"{len(users_to_add)} members were added to the group successfully!")
        return redirect('group_detail', group_id=group.id)
    
    # Get all users who are not already members of the group
    non_members = User.objects.exclude(id__in=group.members.values_list('id', flat=True))
    
    context = {
        'group': group,
        'non_members': non_members
    }
    
    return render(request, 'expenses/add_group_members.html', context)

# Add this function after the add_group_members function

@login_required
def export_group_expenses(request, group_id):
    """View to export all expenses for a group as CSV"""
    group = get_object_or_404(Group, id=group_id)
    
    # Check if user is a member of the group
    if request.user not in group.members.all():
        messages.error(request, "You don't have permission to export this group's expenses.")
        return redirect('group_list')
    
    # Get all expenses in this group
    expenses = Expense.objects.filter(group=group).order_by('-created_at')
    
    # Prefetch related data to optimize queries
    expenses = expenses.select_related('paid_by', 'group')
    expenses = expenses.prefetch_related('split_set__user')
    
    # Create the HTTP response with CSV content
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{group.name}_expenses.csv"'
    
    # Create CSV writer
    writer = csv.writer(response)
    
    # Write header row
    writer.writerow([
        'Title', 
        'Amount', 
        'Paid By', 
        'Date', 
        'Split Type', 
        'Category',
        'Description'
    ])
    
    # Write data rows
    for expense in expenses:
        writer.writerow([
            expense.title,
            expense.amount,
            expense.paid_by.username,
            expense.created_at.strftime('%Y-%m-%d'),
            expense.split_type,
            expense.category if hasattr(expense, 'category') else '',
            expense.description if hasattr(expense, 'description') else ''
        ])
    
    return response

# Add this function after the export_group_expenses function

@login_required
def group_settlement_summary(request, group_id):
    """View to display settlement summary for a group"""
    group = get_object_or_404(Group, id=group_id)
    
    # Check if user is a member of the group
    if request.user not in group.members.all():
        messages.error(request, "You don't have permission to view this group's settlements.")
        return redirect('group_list')
    
    # Get all members of the group
    members = group.members.all()
    
    # Calculate net balances for each member
    member_balances = {}
    for member in members:
        # Amount paid by this member
        paid_amount = Expense.objects.filter(
            group=group,
            paid_by=member
        ).aggregate(
            total=Coalesce(Sum('amount', output_field=DecimalField()), 0)
        )['total']
        
        # Amount owed by this member
        owed_amount = Debt.objects.filter(
            debtor=member,
            expense__group=group,
            is_settled=False
        ).aggregate(
            total=Coalesce(Sum('amount', output_field=DecimalField()), 0)
        )['total']
        
        # Amount to be received by this member
        to_receive_amount = Debt.objects.filter(
            creditor=member,
            expense__group=group,
            is_settled=False
        ).aggregate(
            total=Coalesce(Sum('amount', output_field=DecimalField()), 0)
        )['total']
        
        # Calculate net balance
        net_balance = to_receive_amount - owed_amount
        
        member_balances[member] = {
            'paid': paid_amount,
            'owed': owed_amount,
            'to_receive': to_receive_amount,
            'net_balance': net_balance
        }
    
    # Generate settlement plan
    settlement_plan = []
    
    # Separate members into debtors and creditors
    debtors = [(m, b['net_balance']) for m, b in member_balances.items() if b['net_balance'] < 0]
    creditors = [(m, b['net_balance']) for m, b in member_balances.items() if b['net_balance'] > 0]
    
    # Sort by absolute amount (largest first)
    debtors.sort(key=lambda x: x[1])
    creditors.sort(key=lambda x: x[1], reverse=True)
    
    # Generate settlement transactions
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor, debt = debtors[i]
        creditor, credit = creditors[j]
        
        # The amount to settle is the minimum of the absolute values
        amount = min(abs(debt), credit)
        
        if amount > 0:
            settlement_plan.append({
                'from_user': debtor,
                'to_user': creditor,
                'amount': amount
            })
        
        # Update balances
        debtors[i] = (debtor, debt + amount)
        creditors[j] = (creditor, credit - amount)
        
        # Move to next user if their balance is settled
        if abs(debtors[i][1]) < 0.01:  # Using a small threshold to handle floating point errors
            i += 1
        if abs(creditors[j][1]) < 0.01:
            j += 1
    
    context = {
        'group': group,
        'member_balances': member_balances,
        'settlement_plan': settlement_plan,
        'is_admin': group.admin == request.user
    }
    
    return render(request, 'expenses/group_settlement_summary.html', context)

# Add this function after the group_settlement_summary function

@login_required
def invite_to_group(request, group_id):
    """View to invite users to a group via email"""
    group = get_object_or_404(Group, id=group_id)
    
    # Check if user is the admin of the group
    if group.admin != request.user:
        messages.error(request, "You don't have permission to invite users to this group.")
        return redirect('group_detail', group_id=group.id)
    
    if request.method == 'POST':
        email = request.POST.get('email')
        
        if not email:
            messages.error(request, "Please enter an email address.")
            return redirect('invite_to_group', group_id=group.id)
        
        # Check if user with this email already exists
        try:
            user = User.objects.get(email=email)
            
            # Check if user is already a member
            if user in group.members.all():
                messages.info(request, f"{user.username} is already a member of this group.")
                return redirect('group_detail', group_id=group.id)
            
            # Add user to the group
            group.members.add(user)
            messages.success(request, f"{user.username} has been added to the group.")
            
        except User.DoesNotExist:
            # In a real application, you would send an email invitation here
            # For now, just show a message
            messages.info(request, f"Invitation would be sent to {email} (not implemented in this demo).")
        
        return redirect('group_detail', group_id=group.id)
    
    context = {
        'group': group
    }
    
    return render(request, 'expenses/invite_to_group.html', context)

# Add this function after the invite_to_group function

@login_required
def user_profile(request):
    """View to display and edit user profile"""
    user = request.user
    
    # Get all groups the user is a member of
    user_groups = Group.objects.filter(members=user)
    
    # Get user's expense statistics
    total_paid = Expense.objects.filter(paid_by=user).aggregate(
        total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
    )['total']
    
    # Amount owed by this user across all groups
    user_owes = Debt.objects.filter(
        debtor=user,
        is_settled=False
    ).aggregate(
        total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
    )['total']
    
    # Amount to be received by this user across all groups
    user_owed = Debt.objects.filter(
        creditor=user,
        is_settled=False
    ).aggregate(
        total=Coalesce(Sum('amount', output_field=DecimalField()), Value(0, output_field=DecimalField()))
    )['total']
    
    # Calculate net balance
    net_balance = user_owed - user_owes
    
    # Get recent expenses - change 'split__user' to 'splits__user'
    recent_expenses = Expense.objects.filter(
        Q(paid_by=user) | Q(splits__user=user)
    ).distinct().order_by('-created_at')[:5]
    
    context = {
        'user': user,
        'user_groups': user_groups,
        'total_paid': total_paid,
        'user_owes': user_owes,
        'user_owed': user_owed,
        'net_balance': net_balance,
        'recent_expenses': recent_expenses
    }
    
    return render(request, 'expenses/user_profile.html', context)